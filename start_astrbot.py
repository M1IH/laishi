"""Start the configured AstrBot core once from a Windows logon task.

Run this script with the same Launcher instance's Python environment. It
keeps stdout and stderr in ignored local logs so a detached process can log
Unicode text without a Windows console encoding failure.
"""

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

import psutil


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    args = parser.parse_args()
    core = args.core.resolve(strict=True)
    entry = core / "main.py"
    python = core.parent / "venv" / "Scripts" / "python.exe"
    if not entry.is_file() or not python.is_file():
        raise RuntimeError("AstrBot Launcher instance is incomplete")

    entry_text = str(entry).casefold()
    for process in psutil.process_iter(["cmdline"]):
        try:
            if any(str(arg).casefold() == entry_text for arg in process.info["cmdline"] or []):
                return
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue

    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"astrbot-{datetime.now():%Y%m%d}.log"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    with log_path.open("ab") as output:
        subprocess.Popen(
            [str(python), str(entry)],
            cwd=core,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )


if __name__ == "__main__":
    main()
