# -*- coding: utf-8 -*-
"""D4-⑦ 场景 B 补拉探针（隔离，不碰生产数据）。

验证 miruku_backfill 的过滤与注入契约，不需要真的连 QQ：
1. 首次运行只建基线，不补历史
2. 空窗内对方消息会被选中；自己发的、已处理的、太老的、已补过的都跳过
3. 上限生效：超过 max_inject_per_user 只取最新几条
4. 纯图片消息不进候选（没有可注入文本）
5. bot uin 从历史里发现，不靠猜
6. 注入走 platform.handle_msg，且构造出的 AstrBotMessage 字段正确
7. 注入成功后 last_handled_ts 前移、injected_ids 累积、状态落盘
8. 平台实例缺失时不炸，只记 no_platform
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

FAILS: list[str] = []
PASSES = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}")
    else:
        FAILS.append(f"{name} {detail}")
        print(f"  FAIL {name} {detail}")


# ---------------------------------------------------------------- 假对象
class FakePlain:
    def __init__(self, text: str = ""):
        self.text = text


class FakeABM:
    def __init__(self):
        self.timestamp = 0

    def __setattr__(self, k, v):
        object.__setattr__(self, k, v)


class FakePlatform:
    def __init__(self):
        self.injected: list = []
        self.meta_id = "miruku"

    async def handle_msg(self, abm):
        self.injected.append(abm)


class FakeContext:
    def __init__(self, platform=None):
        self.platform = platform

    def get_platform_inst(self, pid):
        if self.platform and pid == self.platform.meta_id:
            return self.platform
        return None

    def get_config(self):
        return {}


def _install_fake_astrbot() -> None:
    """在 sys.modules 里装假 astrbot 模块，然后原样 import 真插件源码。

    比字符串改写源码可靠：测的是真文件，不会有缩进被改坏的假失败。
    """
    import types

    def mod(name: str, **attrs) -> types.ModuleType:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    class _FilterNS:
        EventMessageType = type("EventMessageType", (), {"PRIVATE_MESSAGE": "private"})

        @staticmethod
        def on_astrbot_loaded():
            def deco(fn):
                return fn
            return deco

        @staticmethod
        def event_message_type(kind):
            def deco(fn):
                return fn
            return deco

    class _Plain:
        def __init__(self, text: str = ""):
            self.text = text

        def __repr__(self):
            return f"Plain({self.text!r})"

    class _Member:
        def __init__(self, user_id, nickname=None):
            self.user_id = user_id
            self.nickname = nickname

    class _ABM:
        def __init__(self):
            self.type = None
            self.self_id = ""
            self.session_id = ""
            self.message_id = ""
            self.message = []
            self.message_str = ""
            self.raw_message = None
            self.timestamp = 0
            self.sender = None

    class _MsgType:
        FRIEND_MESSAGE = "FriendMessage"
        GROUP_MESSAGE = "GroupMessage"

    class _Star:
        def __init__(self, context, config=None):
            self.context = context

    logger_obj = _Logger()
    mod("astrbot")
    mod("astrbot.api", logger=logger_obj)
    mod("astrbot.api.event", AstrMessageEvent=object, filter=_FilterNS)
    mod("astrbot.api.message_components", Plain=_Plain)
    mod("astrbot.api.star", Context=object, Star=_Star)
    mod("astrbot.core")
    mod("astrbot.core.platform")
    mod("astrbot.core.platform.astrbot_message",
        AstrBotMessage=_ABM, MessageMember=_Member)
    mod("astrbot.core.platform.message_type", MessageType=_MsgType)


def load_plugin_module():
    """import 真插件源码；把状态文件重定向到临时目录。"""
    here = Path(__file__).resolve().parent
    src = here.parent / "astrbot_plugin_miruku_backfill" / "main.py"
    if not src.exists():
        src = here / "astrbot_plugin_miruku_backfill" / "main.py"
    _install_fake_astrbot()
    import importlib.util

    spec = importlib.util.spec_from_file_location("miruku_backfill_under_test", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 状态落盘指到临时目录，不碰 /AstrBot
    mod.STATE_PATH = Path(_TMPDIR) / "state.json"
    mod.PLUGIN_DATA_DIR = _TMPDIR
    return mod.BackfillPlugin


class _Logger:
    def __init__(self):
        self.lines: list[str] = []

    def info(self, m):
        self.lines.append(str(m))

    def warning(self, m):
        self.lines.append(str(m))

    def error(self, m):
        self.lines.append(str(m))


class _Star:
    def __init__(self, context, config=None):
        self.context = context


def _make_abm():
    return FakeABM()


def _make_member(uid, nick=None):
    return FakePlain(text=f"member:{uid}:{nick}")


import os  # noqa: E402

_TMPDIR = tempfile.mkdtemp(prefix="bfprobe-")


# ---------------------------------------------------------------- 数据构造
NOW = int(time.time())
UID = "10000002"
BOT = "10000004"


def msg(mid, ts, sender, text=None, image=False):
    segs = []
    if text:
        segs.append({"type": "text", "data": {"text": text}})
    if image:
        segs.append({"type": "image", "data": {"url": "http://x/y.jpg"}})
    return {
        "message_id": mid,
        "time": ts,
        "sender": {"user_id": sender, "nickname": "来世" if sender == UID else "miruku"},
        "message": segs,
    }


def make_plugin(platform=None, **cfg):
    base = {"watch_users": [UID], "max_inject_per_user": 3,
            "max_age_minutes": 120, "startup_delay_sec": 0}
    base.update(cfg)
    P = load_plugin_module()
    return P(FakeContext(platform), base)


def main() -> int:
    print("== 1. 首次运行只建基线，不补历史 ==")
    p = make_plugin(FakePlatform())
    hist = [msg(1001, NOW - 600, UID, "空窗消息一"),
            msg(1002, NOW - 590, BOT, "旧回复"),
            msg(1003, NOW - 300, UID, "空窗消息二")]
    picks = p._pick_backfillable(UID, hist)
    check("首次不补", picks == [], str(picks))
    st = p._user_state(UID)
    check("基线推到最新", st["last_handled_ts"] == NOW - 300, str(st["last_handled_ts"]))

    print("== 2. 有基线后只选空窗内对方消息 ==")
    p = make_plugin(FakePlatform())
    p._user_state(UID)["last_handled_ts"] = NOW - 1000
    hist = [
        msg(2001, NOW - 2000, UID, "太老了"),          # 已处理过（早于基线）
        msg(2002, NOW - 500, UID, "空窗一"),           # 该补
        msg(2003, NOW - 480, BOT, "自己的回复"),        # 跳过：自己发的
        msg(2004, NOW - 460, UID, "空窗二"),           # 该补
        msg(2005, NOW - 60, UID, None, image=True),   # 纯图片：无文本，跳过
        msg(2006, NOW - 30, UID, "空窗三"),            # 该补
    ]
    picks = p._pick_backfillable(UID, hist)
    texts = [x["text"] for x in picks]
    check("选中的正好是三条文本", texts == ["空窗一", "空窗二", "空窗三"], str(texts))
    check("不含自己的话", "自己的回复" not in texts, str(texts))

    print("== 3. 太老的消息跳过，且计入 skipped_old ==")
    p = make_plugin(FakePlatform(), max_age_minutes=60)
    p._user_state(UID)["last_handled_ts"] = NOW - 7200
    hist = [msg(3001, NOW - 7000, UID, "两小时前"), msg(3002, NOW - 300, UID, "刚刚")]
    picks = p._pick_backfillable(UID, hist)
    check("只补新的", [x["text"] for x in picks] == ["刚刚"], str(picks))
    check("old 计数", p.stats["skipped_old"] == 1, str(p.stats))

    print("== 4. 已补过的不重复补 ==")
    p = make_plugin(FakePlatform())
    st = p._user_state(UID)
    st["last_handled_ts"] = NOW - 1000
    st["injected_ids"] = ["4001"]
    hist = [msg(4001, NOW - 500, UID, "补过一次"), msg(4002, NOW - 400, UID, "没补过")]
    picks = p._pick_backfillable(UID, hist)
    check("跳过已补", [x["text"] for x in picks] == ["没补过"], str(picks))
    check("dup 计数", p.stats["skipped_dup"] == 1, str(p.stats))

    print("== 5. 单次上限只取最新 N 条 ==")
    p = make_plugin(FakePlatform(), max_inject_per_user=2)
    p._user_state(UID)["last_handled_ts"] = NOW - 1000
    hist = [msg(5000 + i, NOW - 500 + i * 10, UID, f"第{i}条") for i in range(5)]
    picks = p._pick_backfillable(UID, hist)
    check("只取最新两条", [x["text"] for x in picks] == ["第3条", "第4条"], str(picks))
    check("cap 计数", p.stats["skipped_cap"] == 3, str(p.stats))

    print("== 6. bot uin 从历史里发现 ==")
    p = make_plugin(FakePlatform())
    bot = p._discover_bot_uin(UID, [msg(6001, NOW - 100, BOT, "我")])
    check("发现 bot uin", bot == BOT, bot)
    check("只有对方消息时为空", p._discover_bot_uin(UID, [msg(6002, NOW, UID, "x")]) == "")

    print("== 7. 注入走 handle_msg，ABM 字段正确 ==")
    plat = FakePlatform()
    p = make_plugin(plat)
    p._user_state(UID)["last_handled_ts"] = NOW - 1000
    hist = [msg(7001, NOW - 500, UID, "被补的消息")]
    picks = p._pick_backfillable(UID, hist)
    ok = asyncio.get_event_loop().run_until_complete(
        p._inject(UID, picks[0], BOT))
    check("注入成功", ok is True, str(p.stats))
    check("平台收到一条", len(plat.injected) == 1, str(len(plat.injected)))
    got = plat.injected[0]
    check("类型是私聊", getattr(got, "type", None) == "FriendMessage",
          str(getattr(got, "type", None)))
    check("session_id 是对方 uin", getattr(got, "session_id", None) == UID,
          str(getattr(got, "session_id", None)))
    check("self_id 是 bot", getattr(got, "self_id", None) == BOT,
          str(getattr(got, "self_id", None)))
    check("message_str 有正文", getattr(got, "message_str", "") == "被补的消息",
          str(getattr(got, "message_str", "")))
    check("时间戳保留原值", getattr(got, "timestamp", 0) == NOW - 500,
          str(getattr(got, "timestamp", 0)))

    print("== 8. 注入后状态前移并落盘 ==")
    st = p._user_state(UID)
    check("last_handled 前移", st["last_handled_ts"] == NOW - 500, str(st["last_handled_ts"]))
    check("injected_ids 记录", "7001" in st["injected_ids"], str(st["injected_ids"]))
    state_file = Path(p._state_path_str()) if hasattr(p, "_state_path_str") else None
    raw = Path(_TMPDIR) / "state.json"
    check("状态文件已写", raw.exists(), str(raw))
    if raw.exists():
        on_disk = json.loads(raw.read_text(encoding="utf-8"))
        check("落盘内容含该 uid", UID in (on_disk.get("users") or {}), str(on_disk)[:200])

    print("== 9. 平台不在线时不炸，只记 no_platform ==")
    p = make_plugin(None)
    p._user_state(UID)["last_handled_ts"] = NOW - 1000
    hist = [msg(8001, NOW - 500, UID, "平台没连上")]
    picks = p._pick_backfillable(UID, hist)
    ok = asyncio.get_event_loop().run_until_complete(
        p._inject(UID, picks[0], BOT))
    check("返回 False", ok is False)
    check("no_platform 计数", p.stats["no_platform"] == 1, str(p.stats))

    print("== 10. 消息文本拼接（图文混合） ==")
    text = p._message_text({"message": [{"type": "text", "data": {"text": "看这个"}},
                                        {"type": "image", "data": {}},
                                        {"type": "text", "data": {"text": "笑死"}}]})
    check("拼成一段", text == "看这个[图片]笑死", text)

    print()
    print(f"共 {PASSES + len(FAILS)} 条：通过 {PASSES} / 失败 {len(FAILS)}")
    if FAILS:
        for f in FAILS:
            print("  FAILED:", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
