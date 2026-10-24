"""Start NapCat quick login once without showing the mixed-encoding console.

Run with the AstrBot Launcher instance Python. If QQ requires a fresh QR scan,
use napcat.quick.bat interactively; this script does not bypass QQ validation.
"""

import argparse
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--napcat", type=Path, required=True)
    parser.add_argument("--qq", required=True)
    args = parser.parse_args()
    base = args.napcat.resolve(strict=True)
    if (base / ".manual-login-reserved").exists():
        raise RuntimeError("This NapCat copy is reserved for visible manual login")
    launcher = base / "NapCatWinBootMain.exe"
    if not launcher.is_file() or not args.qq.isdecimal():
        raise RuntimeError("NapCat path or QQ account is invalid")

    def connected() -> bool:
        try:
            return any(
                c.status == psutil.CONN_ESTABLISHED and c.laddr.port == 6199
                for c in psutil.net_connections(kind="tcp")
            )
        except (psutil.AccessDenied, OSError):
            return False

    if connected():
        return

    for process in psutil.process_iter(["name", "exe"]):
        try:
            if (
                process.info["name"] == launcher.name
                and process.info["exe"]
                and Path(process.info["exe"]).resolve() == launcher
            ):
                break
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    else:
        log_dir = Path(__file__).resolve().parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"napcat-console-{datetime.now():%Y%m%d}.log"
        with log_path.open("ab") as output:
            subprocess.Popen(
                [str(launcher), args.qq],
                cwd=base,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )

    qr_opened = False
    for _ in range(12):
        time.sleep(3)
        try:
            if connected():
                return
        except (psutil.AccessDenied, OSError):
            pass
        if not qr_opened:
            candidates = sorted(
                (base / "versions").glob("*/resources/app/napcat/cache/qrcode.png"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates and candidates[0].stat().st_mtime >= time.time() - 90:
                try:
                    os.startfile(candidates[0])
                except OSError:
                    pass
                qr_opened = True
    raise RuntimeError("NapCat did not connect to AstrBot port 6199 within 36 seconds")


if __name__ == "__main__":
    main()
