"""Run with sudo to allow BlueZ's pairing agent to confirm repeat pairing."""

import os
from pathlib import Path
import re
import subprocess


def updated_config(text):
    pattern = r"(?m)^[ \t]*#?[ \t]*JustWorksRepairing[ \t]*=.*$"
    if not re.search(pattern, text):
        raise ValueError("Expected JustWorksRepairing setting was not found; no changes made")
    return re.sub(pattern, "JustWorksRepairing = confirm", text)


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("Run this script with sudo")
    config = Path("/etc/bluetooth/main.conf")
    original = config.read_text()
    updated = updated_config(original)
    backup = config.with_name("main.conf.yeegate-backup")
    if not backup.exists():
        with backup.open("x") as stream:
            stream.write(original)
        backup.chmod(config.stat().st_mode & 0o777)
    config.write_text(updated)
    subprocess.run(["systemctl", "restart", "bluetooth.service"], check=True)
    print("BlueZ repeat pairing now requires agent confirmation.")
    print("Backup:", backup)
