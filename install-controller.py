#!/usr/bin/env python3
"""Install the cstainton repository runner controller as a macOS LaunchAgent."""

from pathlib import Path
import os
import plistlib
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".controller-state"
LABEL = "io.instanto.cstainton-runner-controller"


def main():
    STATE.mkdir(mode=0o700, exist_ok=True)
    os.chmod(str(STATE), 0o700)
    for name in ("controller.log", "controller.err"):
        path = STATE / name
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.close(fd)
    agent_dir = Path.home() / "Library" / "LaunchAgents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    plist = agent_dir / (LABEL + ".plist")
    definition = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(ROOT / "controller.py")],
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        },
        "StandardOutPath": str(STATE / "controller.log"),
        "StandardErrorPath": str(STATE / "controller.err"),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
    }
    with plist.open("wb") as output:
        plistlib.dump(definition, output)
    os.chmod(str(plist), 0o600)
    domain = "gui/" + str(os.getuid())
    subprocess.run(["launchctl", "bootout", domain, str(plist)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print("Installed and started " + LABEL)


if __name__ == "__main__":
    main()
