#!/usr/bin/env python3
"""Start isolated, one-job LAN runners for queued cstainton repository jobs.

The signed-in GitHub CLI owns the management credential. Only a one-hour,
repository-specific registration token is mounted in a job container.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


LABEL = "instanto-container"
CONTROLLER_LABEL = "io.instanto.runner-controller=cstainton"


def command(*args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(" ".join(args[:3]) + ": " + result.stderr.strip())
    return result.stdout


def github(method, endpoint):
    return json.loads(command("gh", "api", "--method", method, endpoint))


def repositories(owner):
    page = 1
    found = []
    while True:
        items = github("GET", "user/repos?affiliation=owner&per_page=100&page=" + str(page))
        found.extend(
            item["full_name"] for item in items
            if item["owner"]["login"].lower() == owner.lower()
            and not item["archived"] and not item["disabled"]
        )
        if len(items) < 100:
            return sorted(found)
        page += 1


def queued_job_time(repo):
    try:
        runs = github("GET", "repos/" + repo + "/actions/runs?per_page=20")["workflow_runs"]
    except RuntimeError as error:
        print("Skipping " + repo + ": " + str(error), file=sys.stderr, flush=True)
        return None
    for run in runs:
        if run["status"] not in ("queued", "in_progress", "waiting", "pending"):
            continue
        # Fork PR code must not run on a machine with access to the LAN.
        head = run.get("head_repository") or {}
        if run["event"] == "pull_request" and head.get("full_name") != repo:
            continue
        jobs = github("GET", "repos/" + repo + "/actions/runs/"
                      + str(run["id"]) + "/jobs?per_page=100")["jobs"]
        if any(job["status"] == "queued" and LABEL in job.get("labels", []) for job in jobs):
            return run["created_at"]
    return None


def docker(host, *args):
    if host.get("ssh"):
        return command("ssh", "-o", "BatchMode=yes", host["ssh"],
                       shlex.join(("docker",) + args))
    return command("docker", *args)


def running_containers(host):
    output = docker(host, "ps", "--filter", "label=" + CONTROLLER_LABEL,
                    "--format", "{{.Names}}")
    return set(output.splitlines())


def memory_available_mb(host):
    if not host.get("ssh"):
        return None
    output = command("ssh", "-o", "BatchMode=yes", host["ssh"],
                     "cat /proc/meminfo")
    match = re.search(r"^MemAvailable:\s+(\d+) kB$", output, re.MULTILINE)
    if not match:
        raise RuntimeError("Cannot read available memory on " + host["name"])
    return int(match.group(1)) // 1024


def registry_address(host):
    name = host.get("registry_host_name")
    if not name:
        return host["registry_host"]
    if not host.get("ssh"):
        raise ValueError("registry_host_name needs an SSH host for lookup")
    output = command("ssh", "-o", "BatchMode=yes", host["ssh"],
                     shlex.join(("getent", "ahostsv4", name)))
    addresses = []
    for line in output.splitlines():
        try:
            address = ipaddress.IPv4Address(line.split()[0])
        except (IndexError, ipaddress.AddressValueError):
            continue
        if address.is_private and address not in addresses:
            addresses.append(address)
    if not addresses:
        raise RuntimeError("No private IPv4 address for the package proxy on "
                           + host["name"])
    for address in addresses:
        try:
            command("ssh", "-o", "BatchMode=yes", host["ssh"],
                    shlex.join(("curl", "--noproxy", "*", "--fail", "--silent",
                                "--show-error", "--max-time", "10", "--resolve",
                                "packages.instanto.io:443:" + str(address),
                                "https://packages.instanto.io/api/v1/version")))
            return str(address)
        except RuntimeError:
            continue
    raise RuntimeError("Package proxy name resolved but no address passed HTTPS verification on "
                       + host["name"])


def container_name(repo):
    name = re.sub(r"[^a-z0-9-]", "-", repo.lower().split("/", 1)[1])
    return "instanto-cstainton-" + name[:40]


def hosts_from(state_dir, image, registry_host):
    path = state_dir / "hosts.json"
    if not path.exists():
        return [{"name": "local", "image": image, "registry_host": registry_host}]
    hosts = json.loads(path.read_text())["hosts"]
    if not hosts or len({host["name"] for host in hosts}) != len(hosts):
        raise ValueError("hosts.json needs a nonempty list of uniquely named hosts")
    for host in hosts:
        if not re.fullmatch(r"[a-z0-9-]+", host["name"]):
            raise ValueError("invalid host name in hosts.json")
        if host.get("ssh") and not host.get("token_dir"):
            raise ValueError("remote hosts need a private token_dir")
        host.setdefault("image", image)
        if not host.get("registry_host_name"):
            host.setdefault("registry_host", registry_host)
    return hosts


def cleanup_tokens(state_dir, hosts, running):
    by_name = {host["name"]: host for host in hosts}
    for token_path in state_dir.glob("*.token"):
        if token_path.stem not in running.get("local", set()):
            token_path.unlink()
    for marker in state_dir.glob("*.active"):
        recorded = json.loads(marker.read_text())
        host = by_name.get(recorded["host"])
        if host and recorded["name"] not in running.get(host["name"], set()):
            command("ssh", "-o", "BatchMode=yes", host["ssh"],
                    shlex.join(("rm", "-f", recorded["token_path"])))
            marker.unlink()


def start_runner(repo, name, state_dir, host):
    registry_host = registry_address(host)
    registration = github("POST", "repos/" + repo + "/actions/runners/registration-token")
    token_path = state_dir / (name + ".token")
    fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as token_file:
            token_file.write(registration["token"])
        mount_path = token_path.resolve()
        marker = None
        if host.get("ssh"):
            remote_dir = host["token_dir"]
            remote_path = remote_dir + "/" + name + ".token"
            marker = state_dir / (host["name"] + "--" + name + ".active")
            marker.write_text(json.dumps({"host": host["name"], "name": name,
                                          "token_path": remote_path}))
            os.chmod(marker, 0o600)
            command("ssh", "-o", "BatchMode=yes", host["ssh"],
                    shlex.join(("install", "-d", "-m", "700", remote_dir)))
            command("scp", "-p", str(token_path), host["ssh"] + ":" + remote_path)
            token_path.unlink()
            mount_path = remote_path
        entrypoint_mount = []
        if host.get("entrypoint_path"):
            entrypoint_mount = [
                "--mount", "type=bind,source=" + host["entrypoint_path"]
                + ",target=/usr/local/bin/ci-runner,readonly"
            ]
        docker(
            host, "run", "--detach", "--rm", "--name", name,
            "--label", CONTROLLER_LABEL, "--label", "io.instanto.repository=" + repo,
            "--cpus", "2", "--memory", "3g", "--pids-limit", "512",
            "--shm-size", "2g", "--add-host", "packages.instanto.io:" + registry_host,
            "--mount", "type=bind,source=" + str(mount_path)
            + ",target=/run/secrets/runner_registration_token,readonly",
            *entrypoint_mount,
            "--env", "GITHUB_REPO=" + repo,
            "--env", "RUNNER_NAME=" + name,
            "--env", "RUNNER_LABELS=" + LABEL,
            "--env", "RUNNER_EPHEMERAL=true",
            "--env", "RUNNER_REGISTRATION_TOKEN_FILE=/run/secrets/runner_registration_token",
            "--env", "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright",
            "--env", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1",
            host["image"],
        )
    except Exception:
        token_path.unlink(missing_ok=True)
        if host.get("ssh"):
            command("ssh", "-o", "BatchMode=yes", host["ssh"],
                    shlex.join(("rm", "-f", remote_path)))
            marker.unlink(missing_ok=True)
        raise
    print("Started " + name + " for " + repo + " on " + host["name"], flush=True)


def poll(owner, state_dir, image, registry_host, max_runners, dry_run):
    repos = repositories(owner)
    hosts = hosts_from(state_dir, image, registry_host)
    running = {}
    for host in hosts:
        try:
            running[host["name"]] = set() if dry_run else running_containers(host)
        except RuntimeError as error:
            print("Skipping unavailable host " + host["name"] + ": "
                  + str(error), file=sys.stderr, flush=True)
    if not running:
        return
    if not dry_run:
        cleanup_tokens(state_dir, [host for host in hosts if host["name"] in running], running)
        count = sum(len(names) for names in running.values())
        if count >= max_runners:
            print("Capacity full: " + str(count) + " runners", flush=True)
            return
    else:
        count = 0
    available = []
    for host in hosts:
        if host["name"] not in running or running[host["name"]]:
            continue
        try:
            if host.get("min_available_mb") and memory_available_mb(host) < host["min_available_mb"]:
                continue
        except RuntimeError as error:
            print("Skipping unavailable host " + host["name"] + ": "
                  + str(error), file=sys.stderr, flush=True)
            continue
        available.append(host)
    if not available:
        return
    rotation = state_dir / "next-host"
    next_host = int(rotation.read_text()) if rotation.exists() else 0
    available.sort(key=lambda host: (hosts.index(host) - next_host) % len(hosts))
    pending = []
    for repo in repos:
        name = container_name(repo)
        if any(name in names for names in running.values()):
            continue
        pending.append((repo, name))
    candidates = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for (repo, name), queued_at in zip(
                pending, executor.map(queued_job_time, (repo for repo, _ in pending))):
            if queued_at:
                candidates.append((queued_at, repo, name))
    for (_, repo, name), host in zip(
            sorted(candidates)[:max(0, max_runners - count)], available):
        if dry_run:
            print("Would start " + name + " for " + repo + " on " + host["name"], flush=True)
        else:
            start_runner(repo, name, state_dir, host)
            rotation.write_text(str((hosts.index(host) + 1) % len(hosts)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="cstainton")
    parser.add_argument("--image", default="instanto-ci-runner:local")
    parser.add_argument("--registry-host", default="host-gateway")
    parser.add_argument("--max-runners", type=int, default=1)
    parser.add_argument("--poll-seconds", type=int, default=120)
    parser.add_argument("--state-dir", type=Path, default=Path(__file__).parent / ".controller-state")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_runners < 1 or args.poll_seconds < 30:
        parser.error("max-runners must be positive and poll-seconds at least 30")
    if not args.dry_run:
        args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(str(args.state_dir), 0o700)
        command("docker", "image", "inspect", args.image)
    while True:
        try:
            poll(args.owner, args.state_dir, args.image, args.registry_host,
                 args.max_runners, args.dry_run)
        except Exception as error:
            print("Controller poll failed: " + str(error), file=sys.stderr, flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
