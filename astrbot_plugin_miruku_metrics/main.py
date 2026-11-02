"""聊天质量指标采集（只读）。

不改变任何对话行为。每次私聊消息处理完后读取本地 DB 的会话内容，
算出几条可量化的「聊得怎么样」指标，落盘成 JSONL 并打印一行摘要。

为什么只读：让机器自己改 persona 会形成闭环放大（一次判断偏差被写进
persona 后固化，之后所有对话都带着偏差），所以采集与调参必须分开。
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Star

PLUGIN_DATA_DIR = "/AstrBot/data/plugin_data/miruku_metrics"
STATE_PATH = f"{PLUGIN_DATA_DIR}/state.json"
METRICS_PATH = f"{PLUGIN_DATA_DIR}/metrics.jsonl"
DB_PATH = "/AstrBot/data/data_v4.db"

# 主动消息合成轮的识别标记。主动消息把 prompt 写进 user 轮，与用户真实
# 发言混在同一条会话里，必须能分开，否则「她回了没」的统计全是错的。
PROACTIVE_MARK = "你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息"
REMINDER_RE = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)
DATA_URI_RE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+")
TZ = timezone(timedelta(hours=8))

# 工具结果会被 AstrBot 以 user 轮写回会话历史。它们不是对方说的话，
# 统计时必须剔除——否则一次搜索 3 万字能把「用户平均长度」从 20 拉到 2000+。
TOOL_RESULT_MARKS = (
    "## Search Results (",
    "[已截断：",
    "Tool `",
)


def _is_tool_result(text: str) -> bool:
    if not text:
        return False
    head = text.lstrip()[:200]
    if any(mark in head for mark in TOOL_RESULT_MARKS):
        return True
    # 图片占位符：早期版本把本地路径写进正文，也不是对方说的话
    if head.startswith("[Image ") and "original path" in head:
        return True
    return False


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _part_text(part) -> str:
    if isinstance(part, dict):
        if part.get("type") == "text":
            return part.get("text") or ""
        if part.get("type") == "think":
            return ""                       # 思考内容不计入正文长度
        return "[%s]" % part.get("type")
    if isinstance(part, str):
        return part
    return ""


def _msg_text(content) -> str:
    """把一条会话内容的 content 摊平成纯文本。

    历史记录有两种形态：正常的 list，以及早期版本写进去的「字符串化的
    Python 字面量」（单引号）。后者 json.loads 会失败，必须用 ast 兜底，
    否则整串原文会被当正文计入长度（实测把平均长度从 30 拉到 2000+）。
    """
    if isinstance(content, str):
        s = content.strip()
        if s.startswith("[") or s.startswith("{"):
            try:
                content = json.loads(s)
            except Exception:
                try:
                    content = ast.literal_eval(s)
                except Exception:
                    return _strip_data_uri(s)
        else:
            return _strip_data_uri(content)
    if isinstance(content, list):
        return _strip_data_uri("".join(_part_text(p) for p in content).strip())
    return _strip_data_uri(str(content))


def _strip_data_uri(text: str) -> str:
    """去掉 base64 图片数据，否则一次图片就把统计拉爆。"""
    if "data:image" in text or ";base64," in text:
        return DATA_URI_RE.sub("[图片]", text)
    return text


def _is_proactive(text: str) -> bool:
    return PROACTIVE_MARK in text


def _clean_user_text(text: str) -> str:
    return REMINDER_RE.sub("", text).strip()


def analyze(turns: list[dict]) -> dict:
    """从会话轮次算指标。turns 为 [{'role','text','proactive'}] 顺序列表。"""
    n_user = n_bot = n_proactive = 0
    user_lens: list[int] = []
    bot_lens: list[int] = []
    # 冷场：bot 连发而中间没有用户真实发言
    max_bot_streak = bot_streak = 0
    # 用户接话率：主动消息之后，用户有没有真实发言
    proactive_with_reply = proactive_total = 0
    last_was_proactive = False

    for t in turns:
        role, text = t["role"], t["text"]
        pro = t.get("proactive", False)
        if role == "assistant":
            if not text:
                continue
            n_bot += 1
            bot_lens.append(len(text))
            bot_streak += 1
            max_bot_streak = max(max_bot_streak, bot_streak)
            # 注意：机器人回复自己的主动消息 prompt 不算「对方回应」，
            # 只有对方真实发言才算，否则回复率恒为 100%。
        else:
            if pro:
                n_proactive += 1
                proactive_total += 1
                last_was_proactive = True
            else:
                if _is_tool_result(text):
                    continue                # 工具结果写回的 user 轮，不是对方发言
                clean = _clean_user_text(text)
                if not clean or clean == "[图片]" or clean.startswith("[Image "):
                    continue                # 纯图片/系统提醒不算真实发言
                n_user += 1
                user_lens.append(len(clean))
                bot_streak = 0
                if last_was_proactive:
                    proactive_with_reply += 1
                    last_was_proactive = False

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    return {
        "user_turns": n_user,
        "bot_turns": n_bot,
        "proactive_turns": n_proactive,
        "user_avg_len": avg(user_lens),
        "bot_avg_len": avg(bot_lens),
        # 关键冷场信号：>3 表示她连着说了 3 句以上对方都没接
        "max_bot_streak": max_bot_streak,
        "proactive_total": proactive_total,
        "proactive_replied": proactive_with_reply,
        "proactive_reply_rate": (
            round(proactive_with_reply / proactive_total, 3) if proactive_total else None
        ),
        # 话轮比：她说了几句 / 对方说了几句。>1 偏话痨，<0.5 偏冷淡
        "turn_ratio": round(n_bot / n_user, 2) if n_user else None,
    }


class MetricsPlugin(Star):
    def __init__(self, context, config: dict | None = None):
        super().__init__(context, config)
        self.conf = config or {}
        self.enabled = self._cfg_bool("enabled", True)
        self.watch_users = [str(u).strip() for u in (self.conf.get("watch_users") or [])
                            if str(u).strip()]
        self.window_turns = self._cfg_int("window_turns", 200)
        self._last_at: dict[str, float] = {}
        Path(PLUGIN_DATA_DIR).mkdir(parents=True, exist_ok=True)
        logger.info(
            "[miruku_metrics] armed: enabled=%s watch=%d window=%d",
            self.enabled, len(self.watch_users), self.window_turns,
        )

    # ---------- 配置 ----------
    def _cfg_bool(self, key: str, default: bool) -> bool:
        v = self.conf.get(key, default)
        return bool(v) if not isinstance(v, str) else v.strip().lower() in ("1", "true", "yes", "on")

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            v = int(self.conf.get(key, default))
            return v if v > 0 else default
        except Exception:
            return default

    # ---------- 主流程 ----------
    @filter.event_message_type(EventMessageType.PRIVATE_MESSAGE)
    async def on_private(self, event: AstrMessageEvent):
        if not self.enabled:
            return
        uid = str(event.get_sender_id() or "")
        if self.watch_users and uid not in self.watch_users:
            return
        # 同一个人 20 秒内只算一次，避免连发消息导致反复读大 DB
        now = time.time()
        if now - self._last_at.get(uid, 0) < 20:
            return
        self._last_at[uid] = now
        try:
            row = self._collect(uid)
        except Exception as e:                       # 采集失败绝不影响对话
            logger.warning("[miruku_metrics] 采集失败 uid=%s: %s", uid, e)
            return
        if row:
            self._append(row)
            logger.info(
                "[miruku_metrics] %s user=%d bot=%d 主动=%d 回复率=%s 冷场连发=%d 话轮比=%s",
                uid, row["user_turns"], row["bot_turns"], row["proactive_turns"],
                row["proactive_reply_rate"], row["max_bot_streak"], row["turn_ratio"],
            )

    def _collect(self, uid: str) -> dict | None:
        import sqlite3
        if not os.path.exists(DB_PATH):
            return None
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            cur = con.cursor()
            # conversations.user_id 是完整 umo；平台 ID 前缀可能是 miruku 也可能带别的
            cur.execute(
                "SELECT content FROM conversations WHERE user_id LIKE ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (f"%FriendMessage:{uid}",),
            )
            r = cur.fetchone()
            if not r or not r[0]:
                return None
            try:
                arr = json.loads(r[0])
            except Exception:
                return None
        finally:
            con.close()

        turns = []
        for m in arr[-self.window_turns:]:
            if not isinstance(m, dict):
                continue
            role = m.get("role") or "user"
            text = _msg_text(m.get("content"))
            turns.append({
                "role": "assistant" if role == "assistant" else "user",
                "text": text,
                "proactive": role != "assistant" and _is_proactive(text),
            })
        if not turns:
            return None
        row = {"at": _now(), "uid": uid, "turns_total": len(arr)}
        row.update(analyze(turns))
        return row

    def _append(self, row: dict) -> None:
        try:
            with open(METRICS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[miruku_metrics] 写盘失败: %s", e)
