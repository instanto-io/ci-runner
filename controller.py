#!/usr/bin/env python3
"""Start isolated, one-job LAN runners for queued cstainton repository jobs.

The signed-in GitHub CLI owns the management credential. Only a one-hour,
repository-specific registration token is mounted in a job container.
"""

import argparse
import json
import os
from pathlib import Path
import re
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


def running_containers():
    output = command("docker", "ps", "--filter", "label=" + CONTROLLER_LABEL,
                     "--format", "{{.Names}}")
    return set(output.splitlines())


def container_name(repo):
    name = re.sub(r"[^a-z0-9-]", "-", repo.lower().split("/", 1)[1])
    return "instanto-cstainton-" + name[:40]


def start_runner(repo, name, state_dir, image, registry_host):
    registration = github("POST", "repos/" + repo + "/actions/runners/registration-token")
    token_path = state_dir / (name + ".token")
    fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as token_file:
            token_file.write(registration["token"])
        command(
            "docker", "run", "--detach", "--rm", "--name", name,
            "--label", CONTROLLER_LABEL, "--label", "io.instanto.repository=" + repo,
            "--cpus", "2", "--memory", "4g", "--pids-limit", "512",
            "--shm-size", "2g", "--add-host", "packages.instanto.io:" + registry_host,
            "--mount", "type=bind,source=" + str(token_path.resolve())
            + ",target=/run/secrets/runner_registration_token,readonly",
            "--env", "GITHUB_REPO=" + repo,
            "--env", "RUNNER_NAME=" + name,
            "--env", "RUNNER_LABELS=" + LABEL,
            "--env", "RUNNER_EPHEMERAL=true",
            "--env", "RUNNER_REGISTRATION_TOKEN_FILE=/run/secrets/runner_registration_token",
            "--env", "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright",
            "--env", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1",
            image,
        )
    except Exception:
        token_path.unlink(missing_ok=True)
        raise
    print("Started " + name + " for " + repo, flush=True)


def poll(owner, state_dir, image, registry_host, max_runners, dry_run):
    repos = repositories(owner)
    running = set() if dry_run else running_containers()
    if not dry_run:
        for token_path in state_dir.glob("*.token"):
            if token_path.stem not in running:
                token_path.unlink()
        if len(running) >= max_runners:
            print("Capacity full: " + str(len(running)) + " runners", flush=True)
            return
    candidates = []
    for repo in repos:
        name = container_name(repo)
        if name in running:
            continue
        queued_at = queued_job_time(repo)
        if queued_at:
            candidates.append((queued_at, repo, name))
    for _, repo, name in sorted(candidates)[:max(0, max_runners - len(running))]:
        if dry_run:
            print("Would start " + name + " for " + repo, flush=True)
        else:
            start_runner(repo, name, state_dir, image, registry_host)


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
