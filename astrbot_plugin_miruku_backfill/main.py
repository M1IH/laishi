# -*- coding: utf-8 -*-
"""Miruku 空窗补拉（D4-⑦ 场景 B）。

问题：AstrBot 停摆/重启期间，QQ 一直在线、SnowLuma 一直收消息，但对方发来的
消息没进 AstrBot 管线。重启后这些消息永远丢了（对方的质问悬在空中）。

做法：启动完成后，拿每个受监视用户的「最后处理时间」去问 SnowLuma 要最近历史
（`get_friend_msg_history`），把空窗期内**对方发来且未处理**的消息重新构造成
`AstrBotMessage`，交回 `platform.handle_msg()` 走完整正常管线
（LLM → 装饰 → 表情包 → 出站闸门），效果等同于对方刚刚发来。

四条硬约束：
1. 只补对方发的消息。自己发的跳过，否则会和历史回复打架。
2. 只补一次。补过的 message_id 落盘，重启不重复补；否则每次重启都追认一遍。
3. 只在空窗内补。太老（默认 120 分钟）不补——半天前的质问现在回更奇怪。
4. 单次有上限（默认 3 条，取最新的）。5 条一起注入 = 5 次 LLM + 5 条回复刷屏。

场景 A（QQ 掉线）不需要这个插件：QQ 自己会把离线消息推过来。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType

PLUGIN_DATA_DIR = "/AstrBot/data/plugin_data/miruku_backfill"
STATE_PATH = Path(PLUGIN_DATA_DIR) / "state.json"
# SnowLuma 的 OneBot HTTP 服务在 docker 网络内的地址（不在宿主映射，防外部访问）
DEFAULT_API_BASE = "http://snowluma:3000"
# 全局 onebot.json 里的 httpServers[0].accessToken（账号级 token 是 WS 反连用的，用了 401）
# 这个文件在 SnowLuma 的 docker 卷里，astrbot 容器看不见 → 用下面那个缓存文件
DEFAULT_TOKEN_FILE = "/var/lib/docker/volumes/qq-gateway-data/_data/config/onebot.json"
# 容器内可读的 token 缓存，由宿主侧心跳脚本定期同步
DEFAULT_TOKEN_CACHE = "/AstrBot/data/plugin_data/miruku_backfill/onebot_token.txt"


class BackfillPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.api_base = str(cfg.get("api_base") or DEFAULT_API_BASE).rstrip("/")
        self.token_file = str(cfg.get("token_file") or DEFAULT_TOKEN_FILE)
        self.token_cache_file = str(
            cfg.get("token_cache_file") or DEFAULT_TOKEN_CACHE)
        raw_users = cfg.get("watch_users") or []
        if isinstance(raw_users, str):
            raw_users = [x.strip() for x in raw_users.replace(",", "\n").split("\n")]
        self.watch_users = [str(u).strip() for u in raw_users if str(u).strip()]
        self.platform_id = str(cfg.get("platform_id") or "miruku")
        self.max_age_minutes = int(cfg.get("max_age_minutes") or 120)
        self.max_inject_per_user = int(cfg.get("max_inject_per_user") or 3)
        self.fetch_count = int(cfg.get("fetch_count") or 30)
        self.startup_delay_sec = float(cfg.get("startup_delay_sec") or 8)
        self.stats = {"runs": 0, "injected": 0, "skipped_dup": 0, "skipped_old": 0,
                      "skipped_cap": 0, "failed": 0, "no_platform": 0}
        self._state = self._load_state()
        logger.info(
            f"[miruku_backfill] armed: enabled={self.enabled} "
            f"platform={self.platform_id} watch={len(self.watch_users)} "
            f"age<={self.max_age_minutes}min cap={self.max_inject_per_user} "
            f"api={self.api_base}"
        )

    # ------------------------------------------------------------- state
    def _load_state(self) -> dict:
        try:
            if STATE_PATH.exists():
                with STATE_PATH.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("users"), dict):
                    return data
        except Exception as e:
            logger.error(f"[miruku_backfill] 读状态失败，按空状态继续: {e!r}")
        return {"users": {}}

    def _save_state(self) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_PATH.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, STATE_PATH)
        except Exception as e:
            logger.error(f"[miruku_backfill] 写状态失败: {e!r}")

    def _user_state(self, uid: str) -> dict:
        users = self._state.setdefault("users", {})
        st = users.setdefault(uid, {})
        st.setdefault("last_handled_ts", 0)
        st.setdefault("injected_ids", [])
        return st

    # ------------------------------------------------------------- 历史拉取
    def _read_token(self) -> str:
        """读 HTTP accessToken。

        优先读容器内的 token 缓存文件（token_cache_file）——因为 onebot.json 在
        SnowLuma 的 docker 卷里，astrbot 容器看不见那个宿主路径。缓存由宿主侧
        心跳脚本每 5 分钟同步一次（token 只在 SnowLuma 重新生成配置时才变）。
        缓存没有时再按 token_file 直读（同容器/同挂载的场景）。
        """
        token = ""
        try:
            p = Path(self.token_cache_file)
            if p.exists():
                token = p.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.error(f"[miruku_backfill] 读 token 缓存失败: {e!r}")
        if token:
            return token
        try:
            with open(self.token_file, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
            servers = ((cfg.get("networks") or {}).get("httpServers") or [])
            for s in servers:
                tok = str(s.get("accessToken") or "").strip()
                if tok:
                    return tok
        except Exception as e:
            logger.error(f"[miruku_backfill] 读 token 文件失败: {e!r}")
        return ""

    async def _fetch_history(self, uid: str) -> list[dict]:
        """调 SnowLuma 的 get_friend_msg_history。返回 messages 列表（旧→新）。"""
        token = self._read_token()
        if not token:
            logger.error("[miruku_backfill] 没有 HTTP accessToken，跳过补拉")
            return []
        try:
            import aiohttp
        except Exception as e:  # pragma: no cover
            logger.error(f"[miruku_backfill] aiohttp 不可用: {e!r}")
            return []
        url = f"{self.api_base}/get_friend_msg_history"
        payload = {"user_id": int(uid), "count": max(1, self.fetch_count)}
        headers = {"Authorization": f"Bearer {token}",
                   "Content-Type": "application/json"}
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        logger.error(
                            f"[miruku_backfill] 历史接口 HTTP {resp.status}: {text[:160]}")
                        return []
                    data = json.loads(text)
        except Exception as e:
            logger.error(f"[miruku_backfill] 历史接口异常: {e!r}")
            return []
        if data.get("retcode") not in (0, None):
            logger.error(f"[miruku_backfill] 历史接口 retcode={data.get('retcode')}")
            return []
        msgs = ((data.get("data") or {}).get("messages") or [])
        return sorted(msgs, key=lambda m: int(m.get("time") or 0))

    @staticmethod
    def _discover_bot_uin(uid: str, msgs: list[dict]) -> str:
        """从历史里发现 bot 自己的 uin：谁的 sender 不是对方，谁就是 bot。

        比猜 self_id 可靠——self_id 只在 OneBot 事件里有，注入路径没有事件。
        """
        for m in reversed(msgs):
            sender = str((m.get("sender") or {}).get("user_id") or "")
            if sender and sender != str(uid):
                return sender
        return ""

    # ------------------------------------------------------------- 过滤
    def _pick_backfillable(self, uid: str, msgs: list[dict]) -> list[dict]:
        st = self._user_state(uid)
        last_handled = int(st.get("last_handled_ts") or 0)
        injected = set(str(x) for x in (st.get("injected_ids") or []))
        now = int(time.time())
        max_age = self.max_age_minutes * 60
        # 首次运行没有基线：只把基线推到最新，不补历史（避免开机把陈年旧账全补）
        if last_handled <= 0:
            if msgs:
                st["last_handled_ts"] = int(msgs[-1].get("time") or now)
                self._save_state()
            logger.info(f"[miruku_backfill] {uid} 首次运行，建立基线，不补拉")
            return []
        picks: list[dict] = []
        for m in msgs:
            ts = int(m.get("time") or 0)
            mid = str(m.get("message_id"))
            sender = str((m.get("sender") or {}).get("user_id") or "")
            if sender != str(uid):
                continue  # 自己发的、或系统消息
            if ts <= last_handled:
                continue  # 已处理过
            if mid in injected:
                self.stats["skipped_dup"] += 1
                continue
            if now - ts > max_age:
                self.stats["skipped_old"] += 1
                continue
            text = self._message_text(m)
            if not text:
                continue  # 纯图片/表情，没有可注入的文本
            picks.append({"id": mid, "time": ts, "text": text,
                          "sender_name": (m.get("sender") or {}).get("nickname") or uid})
        # 只补最新的 N 条：一次注入 N 条就会触发 N 轮回复，多了是刷屏
        if len(picks) > self.max_inject_per_user:
            self.stats["skipped_cap"] += len(picks) - self.max_inject_per_user
            logger.info(
                f"[miruku_backfill] {uid} 空窗消息 {len(picks)} 条，"
                f"超过上限只补最新 {self.max_inject_per_user} 条")
            picks = picks[-self.max_inject_per_user:]
        return picks

    @staticmethod
    def _message_text(m: dict) -> str:
        """把 OneBot 段拼成可注入文本。

        纯图片/纯表情返回空——[图片] 占位没有语义内容，注入一条只有占位的
        消息只会让模型对着空气回复。图文混合才保留 [图片] 占位。
        """
        parts: list[str] = []
        has_text = False
        for seg in (m.get("message") or []):
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "text":
                t = str((seg.get("data") or {}).get("text") or "").strip()
                if t:
                    parts.append(t)
                    has_text = True
            elif seg.get("type") in ("image", "mface"):
                parts.append("[图片]")
        if not has_text:
            return ""
        return "".join(parts).strip()

    # ------------------------------------------------------------- 注入
    def _build_abm(self, uid: str, item: dict, bot_uin: str) -> AstrBotMessage:
        abm = AstrBotMessage()
        abm.type = MessageType.FRIEND_MESSAGE
        abm.self_id = str(bot_uin or "")
        abm.sender = MessageMember(uid, item.get("sender_name") or uid)
        abm.session_id = uid
        abm.message_id = item["id"]
        abm.message_str = item["text"]
        abm.message = [Plain(text=item["text"])]
        abm.raw_message = item
        abm.timestamp = int(item["time"])
        return abm

    async def _inject(self, uid: str, item: dict, bot_uin: str) -> bool:
        try:
            inst = self.context.get_platform_inst(self.platform_id)
        except Exception as e:
            logger.error(f"[miruku_backfill] 取平台实例失败: {e!r}")
            inst = None
        if inst is None:
            self.stats["no_platform"] += 1
            logger.warning(
                f"[miruku_backfill] 平台实例 {self.platform_id} 不在线，跳过 {uid} 的补拉")
            return False
        abm = self._build_abm(uid, item, bot_uin)
        try:
            await inst.handle_msg(abm)
        except Exception as e:
            self.stats["failed"] += 1
            logger.error(f"[miruku_backfill] 注入失败 uid={uid}: {e!r}")
            return False
        self.stats["injected"] += 1
        st = self._user_state(uid)
        ids = list(st.get("injected_ids") or [])
        ids.append(str(item["id"]))
        st["injected_ids"] = ids[-200:]  # 只留最近 200 个，防无限增长
        st["last_handled_ts"] = max(int(st.get("last_handled_ts") or 0), int(item["time"]))
        self._save_state()
        # 隐私铁律：只记条数与时间，不打正文
        logger.info(
            f"[miruku_backfill] 已补拉 uid={uid} msg_id={item['id']} "
            f"age={int(time.time()) - int(item['time'])}s")
        return True

    # ------------------------------------------------------------- 主流程
    async def run_backfill(self) -> None:
        if not self.enabled:
            return
        self.stats["runs"] += 1
        targets = list(self.watch_users)
        if not targets:
            logger.info("[miruku_backfill] 监视名单为空，跳过")
            return
        total = 0
        for uid in targets:
            try:
                msgs = await self._fetch_history(uid)
                if not msgs:
                    logger.info(f"[miruku_backfill] {uid} 无历史可查")
                    continue
                bot_uin = self._discover_bot_uin(uid, msgs)
                picks = self._pick_backfillable(uid, msgs)
                if not picks:
                    logger.info(f"[miruku_backfill] {uid} 无空窗消息")
                    continue
                logger.info(
                    f"[miruku_backfill] {uid} 发现空窗消息 {len(picks)} 条，开始补拉")
                for item in picks:
                    if await self._inject(uid, item, bot_uin):
                        total += 1
                    # 逐条之间留间隔，避免同一会话被并发管线打架
                    await asyncio.sleep(1.5)
            except Exception as e:
                logger.error(f"[miruku_backfill] {uid} 补拉异常: {e!r}")
        logger.info(
            f"[miruku_backfill] 本轮结束 注入={total} "
            f"累计 injected={self.stats['injected']} dup={self.stats['skipped_dup']} "
            f"old={self.stats['skipped_old']} cap={self.stats['skipped_cap']} "
            f"failed={self.stats['failed']}")

    # ------------------------------------------------------------- hooks
    @filter.on_astrbot_loaded()
    async def on_loaded(self) -> None:
        """启动完成后等平台连上，再补拉。"""
        async def _delayed() -> None:
            await asyncio.sleep(max(0.0, self.startup_delay_sec))
            try:
                await self.run_backfill()
            except Exception as e:
                logger.error(f"[miruku_backfill] 启动补拉异常: {e!r}")

        try:
            asyncio.create_task(_delayed())
            logger.info(
                f"[miruku_backfill] 已排定启动补拉（延迟 {self.startup_delay_sec}s）")
        except Exception as e:
            logger.error(f"[miruku_backfill] 排定补拉失败: {e!r}")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent) -> None:
        """正常入站消息推进「最后处理时间」，这样下次启动只补真正的空窗。"""
        try:
            uid = str(event.get_sender_id() or "")
            if uid not in self.watch_users:
                return
            ts = int(getattr(event.message_obj, "timestamp", 0) or 0)
            if ts <= 0:
                ts = int(time.time())
            st = self._user_state(uid)
            if ts > int(st.get("last_handled_ts") or 0):
                st["last_handled_ts"] = ts
                self._save_state()
        except Exception as e:
            logger.error(f"[miruku_backfill] 推进处理时间失败: {e!r}")
