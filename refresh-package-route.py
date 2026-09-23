#!/usr/bin/env python3
"""Keep a persistent runner's package route aligned with host LAN DNS.

The private .env supplies PACKAGES_LAN_HOST. Resolve it on the Docker host,
verify the canonical HTTPS endpoint, then recreate an idle container if its
Docker /etc/hosts entry is stale. A busy runner is left for the next timer tick.
"""

import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile


DEPLOY = Path(__file__).resolve().parent
ENV = DEPLOY / ".env"
COMPOSE = DEPLOY / "compose.persistent.yaml"
PACKAGE_HOST = "packages.instanto.io"
DOCKER = ("sudo", "-n", "docker") if os.environ.get("DOCKER_USE_SUDO") == "1" else ("docker",)


def run(*args, check=True):
    result = subprocess.run(args, cwd=DEPLOY, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()}")
    return result


def docker(*args, check=True):
    return run(*DOCKER, *args, check=check)


def private_env():
    values = {}
    for line in ENV.read_text().splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value.strip().strip('"').strip("'")
    if not values.get("PACKAGES_LAN_HOST"):
        raise RuntimeError("PACKAGES_LAN_HOST is missing from private .env")
    return values


def verified_address(hostname):
    addresses = sorted({
        result[4][0] for result in socket.getaddrinfo(
            hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        if ipaddress.IPv4Address(result[4][0]).is_private
    })
    if not addresses:
        raise RuntimeError("Package LAN hostname has no private IPv4 address")
    for address in addresses:
        result = run("curl", "--noproxy", "*", "--fail", "--silent",
                     "--show-error", "--max-time", "10", "--resolve",
                     f"{PACKAGE_HOST}:443:{address}",
                     f"https://{PACKAGE_HOST}/api/v1/version", check=False)
        if result.returncode == 0:
            return address
    raise RuntimeError("Package LAN hostname resolved but HTTPS verification failed")


def write_address(address):
    lines = ENV.read_text().splitlines()
    updated = False
    for index, line in enumerate(lines):
        if line.startswith("PACKAGES_LAN_IP="):
            lines[index] = "PACKAGES_LAN_IP=" + address
            updated = True
    if not updated:
        lines.append("PACKAGES_LAN_IP=" + address)
    content = "\n".join(lines) + "\n"
    if content == ENV.read_text():
        return
    with tempfile.NamedTemporaryFile(mode="w", dir=DEPLOY, prefix=".env.",
                                     delete=False) as staged:
        staged.write(content)
        staged_path = Path(staged.name)
    staged_path.chmod(0o600)
    staged_path.replace(ENV)


def current_container():
    result = docker("compose", "-f", str(COMPOSE), "ps", "-a", "-q",
                    "runner-1")
    return result.stdout.strip()


def running(container):
    data = json.loads(docker("inspect", container).stdout)[0]
    return bool(data["State"]["Running"])


def route_in_container(container):
    data = json.loads(docker("inspect", container).stdout)[0]
    for entry in data["HostConfig"].get("ExtraHosts") or []:
        if entry.startswith(PACKAGE_HOST + ":"):
            return entry.split(":", 1)[1]
    return None


def busy(container):
    result = docker("top", container)
    return "Runner.Worker" in result.stdout


def verify_container(container, address):
    if not container or route_in_container(container) != address:
        raise RuntimeError("Runner container has no current package LAN mapping")
    result = docker("exec", container, "curl", "--noproxy", "*",
                    "--fail", "--silent", "--show-error", "--max-time", "10",
                    f"https://{PACKAGE_HOST}/api/v1/version", check=False)
    if result.returncode:
        raise RuntimeError("Runner container cannot reach package proxy over HTTPS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true",
                        help="resolve and write .env before Compose starts")
    parser.add_argument("--check", action="store_true",
                        help="verify the running container without changing it")
    parser.add_argument("--recreate", action="store_true",
                        help="apply a newly built image during provisioning")
    args = parser.parse_args()
    if sum((args.prepare, args.check, args.recreate)) > 1:
        parser.error("choose only one mode")
    with (DEPLOY / ".package-route.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        address = verified_address(private_env()["PACKAGES_LAN_HOST"])
        if args.check:
            verify_container(current_container(), address)
            print("Package LAN route verified")
            return
        write_address(address)
        if args.prepare:
            print("Package LAN route prepared")
            return
        container = current_container()
        is_running = bool(container and running(container))
        if is_running and route_in_container(container) == address and not args.recreate:
            verify_container(container, address)
            print("Package LAN route current")
            return
        if is_running and busy(container):
            if args.recreate:
                raise RuntimeError("Runner is busy; rerun provisioning after its job finishes")
            print("Runner is busy; package route refresh deferred")
            return
        docker("compose", "-f", str(COMPOSE), "up", "-d", "--no-build",
               "--force-recreate", "runner-1")
        verify_container(current_container(), address)
        print("Package LAN route refreshed")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"package route: {error}", file=sys.stderr)
        sys.exit(1)
