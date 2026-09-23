#!/usr/bin/env python3
"""Maintain the package proxy entry in a Linux host's /etc/hosts.

The private hostname lives in /etc/instanto-package-route.conf, not in git.
Run this as root from the accompanying systemd timer. --source-check can be
used before installation to test name resolution and TLS without changing the
host.
"""

import argparse
import ipaddress
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile


PACKAGE_HOST = "packages.instanto.io"
HOSTS = Path("/etc/hosts")
DEFAULT_CONFIG = Path("/etc/instanto-package-route.conf")
MARKER = "# instanto-package-route"


def source_name(config):
    name = config.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]+", name):
        raise ValueError("Invalid private package hostname")
    return name


def verified_address(name):
    addresses = sorted({
        result[4][0] for result in socket.getaddrinfo(
            name, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        if ipaddress.IPv4Address(result[4][0]).is_private
    })
    if not addresses:
        raise RuntimeError("Private package hostname has no LAN IPv4 address")
    for address in addresses:
        result = subprocess.run(
            ("curl", "--noproxy", "*", "--fail", "--silent", "--show-error",
             "--max-time", "10", "--resolve", f"{PACKAGE_HOST}:443:{address}",
             f"https://{PACKAGE_HOST}/api/v1/version"),
            capture_output=True, text=True)
        if result.returncode == 0:
            return address
    raise RuntimeError("LAN address did not pass package HTTPS verification")


def updated_hosts(address, original):
    lines = original.splitlines(keepends=True)
    for line in lines:
        if MARKER not in line and PACKAGE_HOST in line.split("#", 1)[0].split():
            raise RuntimeError("/etc/hosts already has an unmanaged package entry")
    remaining = [line for line in lines if MARKER not in line]
    return f"{address} {PACKAGE_HOST} {MARKER}\n" + "".join(remaining)


def install(address):
    original = HOSTS.read_text()
    desired = updated_hosts(address, original)
    if desired == original:
        return False
    stat = HOSTS.stat()
    with tempfile.NamedTemporaryFile(mode="w", dir=HOSTS.parent,
                                     prefix=".instanto-hosts.", delete=False) as staged:
        staged.write(desired)
        staged.flush()
        os.fsync(staged.fileno())
        path = Path(staged.name)
    try:
        os.chown(path, stat.st_uid, stat.st_gid)
        os.chmod(path, stat.st_mode & 0o777)
        path.replace(HOSTS)
    finally:
        path.unlink(missing_ok=True)
    result = subprocess.run(("getent", "ahostsv4", PACKAGE_HOST),
                            capture_output=True, text=True)
    if result.returncode or not result.stdout.startswith(address + " "):
        raise RuntimeError("Host lookup did not use the new LAN route")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-check", action="store_true")
    args = parser.parse_args()
    address = verified_address(source_name(args.config))
    if args.source_check:
        print("Package LAN source verified")
        return
    if os.geteuid() != 0:
        raise RuntimeError("Root is required to update /etc/hosts")
    print("Package LAN route updated" if install(address) else "Package LAN route current")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"package route: {error}", file=sys.stderr)
        sys.exit(1)
