"""Back up Miruku runtime data with the AstrBot Launcher instance Python.

Backups stay under the ignored project data/ directory. This script never
copies dashboard credentials or prints chat content.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from miruku_client import INSTANCE, ROOT


def backup_sqlite(source: Path, target: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"Missing runtime database: {source.name}")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"Backup integrity check failed: {target.name}")


def main() -> None:
    runtime = INSTANCE / "data"
    destination = ROOT / "data" / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    if destination.exists():
        raise RuntimeError("Backup destination already exists; retry after one second")
    destination.mkdir(parents=True)
    backup_sqlite(runtime / "data_v4.db", destination / "data_v4.db")
    observer = runtime / "plugin_data" / "astrbot_plugin_miruku_observer" / "events.sqlite3"
    if observer.is_file():
        backup_sqlite(observer, destination / "observer_events.sqlite3")
    schedule = runtime / "plugin_data" / "astrbot_plugin_proactive_chat" / "session_data.json"
    if schedule.is_file():
        payload = schedule.read_bytes()
        json.loads(payload)
        (destination / "proactive_session_data.json").write_bytes(payload)
    print(f"Runtime backup verified: {destination}")


if __name__ == "__main__":
    main()
