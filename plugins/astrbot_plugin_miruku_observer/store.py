"""Small, content-free event store for one or more explicitly selected peers."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _subject(platform_id: str, qq: str) -> str:
    return hashlib.sha256(f"{platform_id}:{qq}".encode("utf-8")).hexdigest()


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS message_events (
                    id INTEGER PRIMARY KEY,
                    subject_hash TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK(direction IN ('peer', 'bot')),
                    source_hash TEXT,
                    reply_after_seconds REAL,
                    low_mode_triggered INTEGER,
                    crisis_mode_triggered INTEGER,
                    CHECK(low_mode_triggered IS NULL OR low_mode_triggered IN (0, 1)),
                    CHECK(crisis_mode_triggered IS NULL OR crisis_mode_triggered IN (0, 1))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_peer_source
                  ON message_events(subject_hash, source_hash)
                  WHERE direction = 'peer' AND source_hash IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS uq_bot_source
                  ON message_events(subject_hash, source_hash)
                  WHERE direction = 'bot' AND source_hash IS NOT NULL;
                CREATE TABLE IF NOT EXISTS reply_state (
                    subject_hash TEXT PRIMARY KEY,
                    last_bot_at_utc TEXT,
                    awaiting_reply INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS history_cursor (
                    subject_hash TEXT PRIMARY KEY,
                    last_id INTEGER NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def record(
        self,
        platform_id: str,
        qq: str,
        direction: str,
        *,
        source_id: str | None = None,
        at: datetime | None = None,
    ) -> bool:
        """Store a direction/timestamp event; return False for a duplicate inbound ID.

        Mode columns remain NULL because AstrBot's prompt-level mode choice is not
        exposed as a structured event. NULL means unknown, never false.
        """
        if direction not in {"peer", "bot"}:
            raise ValueError("direction must be peer or bot")
        moment = at or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise ValueError("at must include a timezone")
        moment = moment.astimezone(timezone.utc)
        subject = _subject(platform_id, qq)
        source_hash = (
            hashlib.sha256(str(source_id).encode("utf-8")).hexdigest()
            if source_id
            else None
        )
        with closing(self._connect()) as db, db:
            state = db.execute(
                "SELECT last_bot_at_utc, awaiting_reply FROM reply_state WHERE subject_hash=?",
                (subject,),
            ).fetchone()
            reply_after = None
            if direction == "peer" and state and state[0] and state[1]:
                last_bot = datetime.fromisoformat(state[0])
                reply_after = max(0.0, (moment - last_bot).total_seconds())
            cursor = db.execute(
                "INSERT OR IGNORE INTO message_events "
                "(subject_hash, observed_at_utc, direction, source_hash, reply_after_seconds) "
                "VALUES (?, ?, ?, ?, ?)",
                (subject, moment.isoformat(), direction, source_hash, reply_after),
            )
            if not cursor.rowcount:
                return False
            if direction == "bot":
                db.execute(
                    "INSERT INTO reply_state(subject_hash, last_bot_at_utc, awaiting_reply) "
                    "VALUES (?, ?, 1) ON CONFLICT(subject_hash) DO UPDATE SET "
                    "last_bot_at_utc=excluded.last_bot_at_utc, awaiting_reply=1",
                    (subject, moment.isoformat()),
                )
            elif reply_after is not None:
                db.execute(
                    "UPDATE reply_state SET awaiting_reply=0 WHERE subject_hash=?",
                    (subject,),
                )
        return True

    def history_cursor(self, platform_id: str, qq: str) -> int | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT last_id FROM history_cursor WHERE subject_hash=?",
                (_subject(platform_id, qq),),
            ).fetchone()
        return row[0] if row else None

    def set_history_cursor(self, platform_id: str, qq: str, last_id: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO history_cursor(subject_hash, last_id) VALUES (?, ?) "
                "ON CONFLICT(subject_hash) DO UPDATE SET last_id=excluded.last_id",
                (_subject(platform_id, qq), last_id),
            )
