"""Read-only AstrBot hooks that persist message metadata for one QQ peer."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.config.astrbot_config import AstrBotConfig

from .store import EventStore


class MirukuObserver(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.store = EventStore(
            StarTools.get_data_dir("astrbot_plugin_miruku_observer") / "events.sqlite3"
        )
        self.history_db = StarTools.get_data_dir("astrbot_plugin_miruku_observer").parents[1] / "data_v4.db"
        self.lock = asyncio.Lock()
        self.poll_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        async with self.lock:
            await self._sync_history()
        self.poll_task = asyncio.create_task(self._poll_history())

    async def terminate(self) -> None:
        if self.poll_task:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass

    def _history_rows(self, platform_id: str, qq: str, after_id: int):
        with closing(sqlite3.connect(self.history_db.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute(
                "SELECT id, created_at FROM platform_message_history "
                "WHERE id > ? AND platform_id = ? AND user_id = ? AND sender_id = 'bot' "
                "ORDER BY id LIMIT 100",
                (after_id, platform_id, qq),
            ).fetchall()

    def _latest_history_id(self) -> int:
        with closing(sqlite3.connect(self.history_db.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT COALESCE(MAX(id), 0) FROM platform_message_history").fetchone()[0]

    async def _sync_history(self) -> None:
        qq = str(self.config.get("target_qq", "")).strip()
        if not qq or not self.history_db.is_file():
            return
        platform_id = self.config.get("platform_id", "miruku")
        cursor = await asyncio.to_thread(self.store.history_cursor, platform_id, qq)
        if cursor is None:
            latest = await asyncio.to_thread(self._latest_history_id)
            await asyncio.to_thread(self.store.set_history_cursor, platform_id, qq, latest)
            return
        while True:
            rows = await asyncio.to_thread(self._history_rows, platform_id, qq, cursor)
            if not rows:
                return
            for history_id, created_at in rows:
                moment = datetime.fromisoformat(str(created_at))
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=timezone.utc)
                await asyncio.to_thread(
                    self.store.record,
                    platform_id,
                    qq,
                    "bot",
                    source_id=f"platform_history:{history_id}",
                    at=moment,
                )
                await asyncio.to_thread(self.store.set_history_cursor, platform_id, qq, history_id)
                cursor = history_id
            if len(rows) < 100:
                return

    async def _poll_history(self) -> None:
        while True:
            try:
                async with self.lock:
                    await self._sync_history()
            except Exception as exc:
                logger.error(f"[Miruku observer] history sync failed: {type(exc).__name__}")
            await asyncio.sleep(10)

    def _matches(self, event: AstrMessageEvent) -> bool:
        qq = str(self.config.get("target_qq", "")).strip()
        return bool(qq) and event.get_platform_id() == self.config.get(
            "platform_id", "miruku"
        ) and event.get_sender_id() == qq

    async def _record(self, event: AstrMessageEvent, direction: str) -> None:
        if not self._matches(event):
            return
        source_id = getattr(event.message_obj, "message_id", None)
        try:
            async with self.lock:
                if direction == "peer":
                    await self._sync_history()
                await asyncio.to_thread(
                    self.store.record,
                    event.get_platform_id(),
                    event.get_sender_id(),
                    direction,
                    source_id=str(source_id) if source_id is not None else None,
                )
        except Exception as exc:
            logger.error(
                f"[Miruku observer] metadata write failed: {type(exc).__name__}"
            )

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=-100)
    async def on_private_message(self, event: AstrMessageEvent) -> None:
        await self._record(event, "peer")

    @filter.after_message_sent()
    async def on_after_message_sent(self, event: AstrMessageEvent) -> None:
        await self._record(event, "bot")
