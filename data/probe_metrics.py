"""聊天质量指标采集探针（隔离内存，不碰生产数据）。

跑法：python data/probe_metrics.py
退出码 0 = 全绿，1 = 有失败。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent / "astrbot_plugin_miruku_metrics"
if not PLUGIN.exists():
    PLUGIN = HERE / "astrbot_plugin_miruku_metrics"

CASES: list[tuple[str, bool, str]] = []


def case(name: str, ok: bool, detail: str = "") -> None:
    CASES.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  <- " + detail) if (detail and not ok) else ""))


def _install_fakes() -> None:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = types.SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None,
        error=lambda *a, **k: None, debug=lambda *a, **k: None,
    )
    api_event = types.ModuleType("astrbot.api.event")

    class AstrMessageEvent:                       # noqa: D401
        pass

    class _Filter:
        @staticmethod
        def event_message_type(*_a, **_k):
            return lambda fn: fn

    api_event.AstrMessageEvent = AstrMessageEvent
    api_event.filter = _Filter()

    api_filter = types.ModuleType("astrbot.api.event.filter")

    class EventMessageType:
        PRIVATE_MESSAGE = "private"
        GROUP_MESSAGE = "group"

    api_filter.EventMessageType = EventMessageType

    api_star = types.ModuleType("astrbot.api.star")

    class Star:
        def __init__(self, context=None, config=None):
            self.context = context
            self.config = config

    api_star.Star = Star

    for name, mod in [
        ("astrbot", astrbot), ("astrbot.api", api), ("astrbot.api.event", api_event),
        ("astrbot.api.event.filter", api_filter), ("astrbot.api.star", api_star),
    ]:
        sys.modules[name] = mod


def load_module():
    _install_fakes()
    spec = importlib.util.spec_from_file_location("mm_metrics", PLUGIN / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mm_metrics"] = mod
    spec.loader.exec_module(mod)
    return mod


PROACTIVE = "你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。保持已配置的人格与口吻。"
REMINDER = "<system_reminder>Current datetime: 2026-11-02 08:31 (CST), Weekday: Monday</system_reminder>"


def U(text: str) -> dict:
    return {"role": "user", "text": text, "proactive": False}


def P(text: str) -> dict:
    return {"role": "user", "text": text, "proactive": True}


def A(text: str) -> dict:
    return {"role": "assistant", "text": text, "proactive": False}


def main() -> int:
    mod = load_module()
    print("=" * 60)
    print("Miruku 聊天质量指标探针")
    print("=" * 60)

    # ---------- 1. 消息文本摊平 ----------
    print("\n[1] 文本摊平")
    case("纯文本", mod._msg_text([{"type": "text", "text": "晚上好"}]) == "晚上好")
    case("图文混合", mod._msg_text([{"type": "text", "text": "看这个"},
                                    {"type": "image"}]) == "看这个[image]")
    case("think 不计入正文",
         mod._msg_text([{"type": "think", "think": "内部推理"},
                        {"type": "text", "text": "说出来的话"}]) == "说出来的话",
         mod._msg_text([{"type": "think", "think": "内部推理"},
                        {"type": "text", "text": "说出来的话"}]))
    case("字符串输入原样返回", mod._msg_text("纯字符串") == "纯字符串")
    # 早期版本把 content 写成「字符串化的 Python 字面量」（单引号），
    # json.loads 会失败；不兜底就会把整串原文当正文，实测把平均长度拉爆。
    py_literal = "[{'type': 'text', 'text': '晚上好'}]"
    case("Python 字面量字符串能被解析",
         mod._msg_text(py_literal) == "晚上好", repr(mod._msg_text(py_literal)))
    py_literal2 = "[{'type': 'text', 'text': '[图片]'}, {'type': 'text', 'text': '正文'}]"
    case("Python 字面量多段正确拼接",
         mod._msg_text(py_literal2) == "[图片]正文", repr(mod._msg_text(py_literal2)))
    # base64 图片必须剥掉，否则一次带图就把「用户平均长度」统计毁掉
    b64 = "data:image/jpeg;base64," + "A" * 500
    got = mod._msg_text([{"type": "text", "text": "看图" + b64}])
    case("base64 被替换为 [图片]", b64 not in got and "[图片]" in got, repr(got[:40]))
    case("剥离后长度可控", len(got) < 60, str(len(got)))

    # ---------- 2. 主动消息识别 ----------
    print("\n[2] 主动消息识别")
    case("带标记识别为主动", mod._is_proactive(PROACTIVE + " 问问他在干嘛") is True)
    case("用户真实发言不误判", mod._is_proactive("今天好累啊") is False)
    case("空字符串安全", mod._is_proactive("") is False)

    # ---------- 3. 提醒剥离 ----------
    print("\n[3] system_reminder 剥离")
    case("剥离后只剩正文",
         mod._clean_user_text("晚上好" + REMINDER) == "晚上好",
         repr(mod._clean_user_text("晚上好" + REMINDER)))
    case("纯提醒剥离后为空", mod._clean_user_text(REMINDER) == "")

    # ---------- 4. 基本计数 ----------
    print("\n[4] 基本计数")
    r = mod.analyze([U("你好"), A("嗯"), U("在干嘛"), A("躺着")])
    case("用户轮数 = 2", r["user_turns"] == 2, str(r["user_turns"]))
    case("机器人轮数 = 2", r["bot_turns"] == 2, str(r["bot_turns"]))
    case("话轮比 = 1.0", r["turn_ratio"] == 1.0, str(r["turn_ratio"]))

    # ---------- 5. 非真实发言过滤 ----------
    print("\n[5] 非真实发言过滤")
    r = mod.analyze([U("[图片]"), U(REMINDER), U("真说话"), A("好")])
    case("纯图片与提醒不计入 user_turns", r["user_turns"] == 1, str(r["user_turns"]))
    r2 = mod.analyze([U("说话" + REMINDER), A("嗯")])
    case("正文+提醒计 1 条且长度不含提醒", r2["user_turns"] == 1 and r2["user_avg_len"] == 2,
         "%s / %s" % (r2["user_turns"], r2["user_avg_len"]))
    # 工具结果会被写回 user 轮，绝不能当成对方发言（实测能拉爆均值）
    r = mod.analyze([U("## Search Results (6 results, 1417ms)\n\n### 1. 舞萌"), A("搜到了")])
    case("搜索工具结果不计入用户发言", r["user_turns"] == 0, str(r["user_turns"]))
    r = mod.analyze([U("[已截断：原始返回 99000 字符"), U("真说话"), A("嗯")])
    case("截断提示不计入用户发言", r["user_turns"] == 1, str(r["user_turns"]))
    r = mod.analyze([U("[Image 1: original path C:/x.jpg]"), U("真说话"), A("嗯")])
    case("本地图片路径占位不计入用户发言", r["user_turns"] == 1, str(r["user_turns"]))
    case("工具结果判定函数正确",
         mod._is_tool_result("## Search Results (3 results") is True
         and mod._is_tool_result("今天吃啥") is False)

    # ---------- 6. 冷场连发 ----------
    print("\n[6] 冷场信号（max_bot_streak）")
    r = mod.analyze([A("第一句"), A("第二句"), A("第三句")])
    case("连说 3 句 = 3", r["max_bot_streak"] == 3, str(r["max_bot_streak"]))
    r = mod.analyze([A("a"), U("接话"), A("b"), A("c")])
    case("用户接话会打断连发 = 2", r["max_bot_streak"] == 2, str(r["max_bot_streak"]))
    r = mod.analyze([U("hi"), A("x"), U("嗯"), A("y")])
    case("正常一来一回 = 1", r["max_bot_streak"] == 1, str(r["max_bot_streak"]))

    # ---------- 7. 主动消息回复率 ----------
    print("\n[7] 主动消息回复率")
    r = mod.analyze([P(PROACTIVE), A("在干嘛呢"), U("在上课")])
    case("主动后有真实回复 → 1/1", r["proactive_replied"] == 1 and r["proactive_total"] == 1,
         "%s/%s" % (r["proactive_replied"], r["proactive_total"]))
    case("回复率 = 1.0", r["proactive_reply_rate"] == 1.0, str(r["proactive_reply_rate"]))
    r = mod.analyze([P(PROACTIVE), A("在干嘛呢"), P(PROACTIVE), A("吃饭没")])
    case("两条主动都没被回 → 0/2", r["proactive_replied"] == 0 and r["proactive_total"] == 2,
         "%s/%s" % (r["proactive_replied"], r["proactive_total"]))
    case("回复率 = 0.0", r["proactive_reply_rate"] == 0.0, str(r["proactive_reply_rate"]))
    r = mod.analyze([U("我在"), P(PROACTIVE), A("哦"), U("在")])
    case("混合场景 1/1", r["proactive_total"] == 1 and r["proactive_replied"] == 1,
         "%s/%s" % (r["proactive_replied"], r["proactive_total"]))

    # ---------- 8. 空会话安全 ----------
    print("\n[8] 边界")
    r = mod.analyze([])
    case("空列表不炸且全 0",
         r["user_turns"] == 0 and r["bot_turns"] == 0 and r["turn_ratio"] is None)
    case("主动消息总数 0 时回复率为 None", r["proactive_reply_rate"] is None)
    r = mod.analyze([A("")])
    case("空文本的机器人轮被跳过", r["bot_turns"] == 0, str(r["bot_turns"]))

    # ---------- 9. 只读保证（源码静态断言）----------
    print("\n[9] 只读保证（静态断言）")
    src = (PLUGIN / "main.py").read_text(encoding="utf-8")
    # 只查「代码行」：排除注释、docstring、以及字符串常量里的说明文字。
    import ast
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            ds = ast.get_docstring(node, clean=False)
            if ds:
                docstrings.add(ds)
    code_lines: list[str] = []
    for ln in src.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if any(ds_line.strip() == s for ds in docstrings for ds_line in ds.splitlines()):
            continue                        # docstring 行
        if s.startswith(("'", '"')) or s.endswith(("'", '"')):
            # 纯字符串字面量行（metadata 说明、日志文案）也排除
            if not any(k in s for k in ("(", "=", ".", "[")):
                continue
        code_lines.append(s)
    for bad, why in [
        ("stop_event", "不得阻断发送"),
        ("completion_text", "不得改写回复文本"),
        ("send_message", "不得主动发消息"),
        ("persona", "不得触碰 persona"),
    ]:
        hits = [ln for ln in code_lines if bad in ln]
        case("代码不含 %s（%s）" % (bad, why), len(hits) == 0,
             "命中 %d 行: %s" % (len(hits), hits[:2]))
    case("使用只读模式打开 DB", 'mode=ro' in src)
    case("异常不冒泡（采集失败只 warning）", "except Exception" in src)

    # ---------- 汇总 ----------
    total = len(CASES)
    failed = [c for c in CASES if not c[1]]
    print("\n" + "=" * 60)
    print("共 %d 条：通过 %d / 失败 %d" % (total, total - len(failed), len(failed)))
    if failed:
        print("失败项：")
        for name, _, detail in failed:
            print("  - %s  %s" % (name, detail))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
