"""离线探针：出站内部标记清洗（C-24）。

跑法（必须用实例 venv 的 python，系统 python 导入 astrbot 会炸）：

    PYTHONIOENCODING=utf-8 \
    PYTHONPATH="C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/core" \
    "C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe" \
    data/probe_outbound_scrub.py

只测 `_strip_outbound_marks` 这层纯函数，以及 `scrub_outbound` 钩子对 chain 的处理，
不起 AstrBot、不连 QQ、不读数据库。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "astrbot_plugin_miruku_context_guard"

_spec = importlib.util.spec_from_file_location(
    "miruku_context_guard_outbound_under_test", PLUGIN / "main.py"
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)  # type: ignore[union-attr]

from astrbot.core.message.components import Plain  # noqa: E402
from astrbot.core.message.message_event_result import MessageEventResult  # noqa: E402

strip = guard._strip_outbound_marks

PASS = 0
FAIL = 0
CASES: list[tuple[str, bool, str | None]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {detail}")


def case(name: str, text: str, expect: str, *, expect_hit: bool = True) -> None:
    """断言剥离结果等于 expect。"""
    got, hits = strip(text)
    ok = got == expect
    if expect_hit:
        ok = ok and bool(hits)
    check(name, ok, f"got={got!r} hits={hits} want={expect!r}")


print("== T 组：<thought> 五段式 ==")

# T1 生产实测形状（2026-10-26 20:40 那条）
T1 = (
    " <thought> [感知] 对方问在不在，像是想开始聊。\n"
    "[评估] 陌生人，中立，接一句就好。\n"
    "[代谢] 无负面情绪可消解，情绪平稳。\n"
    "[决策] 直接回\"在\"，短句。\n"
    "[更新] trust:2\n"
    "</thought>\n在"
)
case("T1 五段式 + 正文", T1, "在")

# T2 只有 thought，没有正文 → 空串（调用方靠空串判定不发）
case("T2 纯 thought", "<thought>[感知] x</thought>", "")

# T3 大小写
case("T3 大写标签", "<THOUGHT>abc</THOUGHT>在", "在")

# T4 thinking
case("T4 thinking 标签", "<thinking>abc</thinking>在", "在")

# T5 带 ```xml 围栏
case("T5 围栏包裹", "```xml\n<thought>abc</thought>\n```\n在", "在")

# T6 嵌套：内层优先，外层也该清掉
case("T6 嵌套", "<thought>a<thought>b</thought>c</thought>在", "在")

# T7 未闭合（截断）→ 从开标签起全砍
case("T7 未闭合", "在吗？\n<thought>[感知] 还没写完", "在吗？")

# T8 孤儿闭合标签 → 砍它之前的全部
case("T8 孤儿闭合", "<thought>abc</thought>正文\n</thought>", "正文")

print("\n== F 组：全角 / 中文输入法形态 ==")

# F1 全角尖括号
case("F1 全角尖括号", "＜thought＞abc＜/thought＞在", "在")

# F2 全角字符（ｔｈｏｕｇｈｔ）
case("F2 全角字母", "＜ｔｈｏｕｇｈｔ＞abc＜/ｔｈｏｕｇｈｔ＞在", "在")

# F3 标签内空格
case("F3 标签内空格", "< thought >abc< /thought >在", "在")

print("\n== P 组：[Profile:] ==")

case("P1 半角", "[Profile: 爱好=舞萌, 称呼=来世]在", "在")
case("P2 全角括号", "【Profile： 爱好=舞萌】在", "在")
case("P3 裸形态", "Profile: 爱好=舞萌, 称呼=来世在吗", "在吗")
case("P4 正文里的英文 profile 不误伤", "我的 profile 没啥好写的", "我的 profile 没啥好写的")

print("\n== M 组：DSML / system_reminder / 内心独白行 ==")

case("M1 DSML", "<|DSML|invoke name=\"x\"><|DSML|parameter>在", "在")
case("M2 system_reminder", "<system_reminder>别忘了</system_reminder>在", "在")
case("M3 裸独白行", "[感知] 对方问在不在\n在", "在")
case("M4 括号内心状态", "（更新：joy:2）在", "在")
case("M5 think 裸标签", "<think>abc</think>在", "在")

print("\n== N 组：不能误伤的正常回复 ==")

for name, text in [
    ("N1 普通短句", "在"),
    ("N2 带括号", "行吧（笑）"),
    ("N3 带方括号", "【公告】今天不开机"),
    ("N4 英文方括号", "[kidding] no"),
    ("N5 表情文字", "好耶 :3"),
    ("N6 多行正文", "第一行\n第二行\n第三行"),
]:
    got, hits = strip(text)
    check(name, got == text and not hits, f"got={got!r} hits={hits}")

# N7 空行折叠但正文不动
got, _ = strip("第一段\n\n\n\n第二段")
check("N7 空行折叠", got == "第一段\n\n第二段", f"got={got!r}")

print("\n== H 组：钩子对 chain 的处理 ==")


class FakeEvent:
    def __init__(self, result):
        self._result = result
        self.cleared = False

    def get_result(self):
        return None if self.cleared else self._result

    def clear_result(self):
        self.cleared = True


class FakeResult:
    def __init__(self, chain):
        self.chain = chain


def make_guard():
    g = object.__new__(guard.MirukuContextGuard)
    g.config = {}
    g._stats = {
        "requests": 0,
        "images": 0,
        "chars": 0,
        "revived": 0,
        "dropped_rounds": 0,
        "dropped_chars": 0,
        "outbound_scrubbed": 0,
        "outbound_cleared": 0,
    }
    return g


import asyncio  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# H1 单段 thought+正文 → 只留正文
g = make_guard()
ev = FakeEvent(FakeResult([Plain("<thought>abc</thought>在")]))
run(g.scrub_outbound(ev))
check(
    "H1 单段混合",
    ev.get_result() is not None and ev.get_result().chain[0].text == "在",
    f"chain={[c.text for c in ev.get_result().chain] if ev.get_result() else None}",
)

# H2 全是 thought → clear_result
g = make_guard()
ev = FakeEvent(FakeResult([Plain("<thought>abc</thought>")]))
run(g.scrub_outbound(ev))
check("H2 全是 thought → 不发", ev.cleared, f"cleared={ev.cleared}")

# H3 多段：一段干净一段脏
g = make_guard()
ev = FakeEvent(
    FakeResult([Plain("第一句"), Plain("<thought>x</thought>第二句")])
)
run(g.scrub_outbound(ev))
chain = [c.text for c in ev.get_result().chain] if ev.get_result() else []
check("H3 多段保留干净段", chain == ["第一句", "第二句"], f"chain={chain}")

# H4 没有任何标记 → 不动，不计数
g = make_guard()
ev = FakeEvent(FakeResult([Plain("在")]))
run(g.scrub_outbound(ev))
check(
    "H4 干净回复不动",
    ev.get_result().chain[0].text == "在" and g._stats["outbound_scrubbed"] == 0,
    f"stats={g._stats}",
)

# H5 开关关闭 → 不动
g = make_guard()
g.config = {"strip_outbound_marks": False}
ev = FakeEvent(FakeResult([Plain("<thought>abc</thought>在")]))
run(g.scrub_outbound(ev))
check("H5 开关关闭", ev.get_result().chain[0].text == "<thought>abc</thought>在")

# H6 result 为 None 不炸
g = make_guard()
ev = FakeEvent(None)
run(g.scrub_outbound(ev))
check("H6 result 为 None", True)

# H7 chain 为空不炸
g = make_guard()
ev = FakeEvent(FakeResult([]))
run(g.scrub_outbound(ev))
check("H7 空 chain", True)

# H8 非 Plain 组件（比如 Image）原样保留
class FakeImage:
    type = "image"
    text = None


g = make_guard()
ev = FakeEvent(FakeResult([Plain("<thought>abc</thought>在"), FakeImage()]))
run(g.scrub_outbound(ev))
chain = ev.get_result().chain
check(
    "H8 非 Plain 组件保留",
    len(chain) == 2 and chain[0].text == "在" and isinstance(chain[1], FakeImage),
)

print(f"\n{'=' * 50}\n通过 {PASS} / {PASS + FAIL}")
if FAIL:
    print(f"失败 {FAIL}")
    sys.exit(1)
print("全部通过")
