# -*- coding: utf-8 -*-
"""context_guard v0.4.0 注入清污逻辑离线验证（不打真机）。

覆盖：
  T1  _is_synthetic 正确识别 EmotionAI 三条注入
  T2  _is_synthetic 不误杀真实 user / assistant / system
  T3  _strip_thought_inline 剥掉内联 <thought> 块、保留回复正文
  T4  _strip_thought_inline 对纯 thought 消息返回 None（整条丢弃）
  T5  还原路径：original_msgs 含旧注入 + 本轮 tail 含新注入 → 全部清掉
  T6  尾部锚点跳过伪 user（EmotionAI 的 "（系统自检…）" 是最后一条 user）
  T7  scrub_injected_turns=false 时不清污
  T8  清污后真实历史一条不少
"""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "astrbot_plugin_miruku_context_guard"
CORE = Path(
    r"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\core"
)
sys.path.insert(0, str(CORE))  # 先让 astrbot 可被导入

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "miruku_context_guard_under_test", PLUGIN / "main.py"
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)  # type: ignore[union-attr]

FAKE_USER = "（系统自检：请报告当前情感状态）"
FAKE_ASSISTANT = "<thought>\n[感知] 收到系统自检指令。\n[评估] 当前运行平稳，心情平静。\n[决策] 输出标准状态报告。\n[更新] joy:0\n</thought>\n当前状态正常。"
FORCE_SYSTEM = "\n[PROTOCOL_ENFORCEMENT]\nUser input received.\nINITIATING COGNITIVE PROCESS...\nREQUIRED ACTION: Generate XML block.\n"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))


def M(role: str, text: str) -> dict:
    return {"role": role, "content": text}


# --- T1 ---------------------------------------------------------------------
injected = [M("user", FAKE_USER), M("assistant", FAKE_ASSISTANT), M("system", FORCE_SYSTEM)]
t1 = all(guard._is_synthetic(m) for m in injected)
check("T1 识别三条注入", t1, f"{[guard._is_synthetic(m) for m in injected]}")

# --- T2 ---------------------------------------------------------------------
reals = [
    M("user", "otto？<system_reminder>Current datetime: 2026-10-26 11:39</system_reminder>"),
    M("assistant", "嗯？怎么突然问这个"),
    M("assistant", "那堆乱码不用理，聊点别的"),
    M("user", "何意味"),
    M("system", "You are Miruku, a companion."),
    M("assistant", "今晚去不了，我这边上不了线"),
]
false_pos = [m for m in reals if guard._is_synthetic(m)]
check("T2 不误杀真实消息", not false_pos, f"误杀 {len(false_pos)} 条")

# --- T3 ---------------------------------------------------------------------
t3_msg = M("assistant", "<thought>\n1. 感知：对方又问。\n5. 更新：joy:1\n</thought>\n那堆乱码不用理，聊点别的")
t3_out = guard._strip_thought_inline(t3_msg)
t3_ok = isinstance(t3_out, dict) and t3_out["content"] == "那堆乱码不用理，聊点别的"
check("T3 剥 thought 保留正文", t3_ok, repr(t3_out.get("content") if isinstance(t3_out, dict) else t3_out))

# --- T4 ---------------------------------------------------------------------
t4_msg = M("assistant", "<thought>\n只有思考没有正文\n</thought>")
t4_out = guard._strip_thought_inline(t4_msg)
check("T4 纯 thought → None", t4_out is None, repr(t4_out))

# --- T5 / T6 / T8：走完整 restore 路径 ---------------------------------------


class FakeCtx:
    def __init__(self, messages):
        self.messages = messages


class FakeEvent:
    def __init__(self, extra):
        self._extra = dict(extra)

    def get_extra(self, k):
        return self._extra.get(k)

    def set_extra(self, k, v):
        self._extra[k] = v


def make_plugin(cfg):
    """构造真插件实例，绕过 __init__（不需要 context/config 对象）。"""
    obj = object.__new__(guard.MirukuContextGuard)
    obj.config = cfg
    obj._stats = {}
    return obj


import asyncio  # noqa: E402


def run_restore(original_msgs, live_messages, begin_turn=None, cfg=None):
    star = make_plugin(cfg or {"scrub_injected_turns": True, "log_stats": False})
    ev = FakeEvent({guard._EXTRA_KEY: {"original_msgs": original_msgs}})
    if begin_turn is not None:
        ev.set_extra(guard._BEGIN_KEY, {"count": 0, "turn": begin_turn})
    ctx = FakeCtx(live_messages)
    asyncio.run(star.restore_history(ev, ctx, None))
    return ctx.messages


# 真实历史（还原目标），刻意不含任何注入
real_history = [
    M("user", "在买饭"),
    M("assistant", "好，买个热的"),
]

# 本轮 live messages：system + 还原历史 + 本轮 user + 本轮 assistant + EmotionAI 三条
this_turn_user = M("user", "今天打舞萌了吗")
live = [
    M("system", "You are Miruku."),
    M("user", "在买饭"),
    M("assistant", "好，买个热的"),
    this_turn_user,
    M("assistant", "<thought>\n1. 感知：他问舞萌。\n5. 更新：joy:1\n</thought>\n打了，R 值还行"),
    M("user", FAKE_USER),
    M("assistant", FAKE_ASSISTANT),
    M("system", FORCE_SYSTEM),
]
out = run_restore(real_history, live, begin_turn=this_turn_user)

t5_ok = not any(guard._is_synthetic(m) for m in out)
check("T5 还原后无注入残留", t5_ok, f"剩 {sum(1 for m in out if guard._is_synthetic(m))} 条")

texts = [m["content"] for m in out]
t6_ok = any("打了，R 值还行" == t for t in texts) and "今天打舞萌了吗" in texts
check("T6 本轮真实问答保留", t6_ok, repr(texts))

t8_ok = len(out) == 2 + 1 + 2  # system + 2 历史 + user + assistant
check("T8 条数正确（无丢真实历史）", t8_ok, f"实际 {len(out)} 条：{texts}")

# --- T7：关开关不清污 -------------------------------------------------------
out_off = run_restore(
    real_history,
    live,
    begin_turn=this_turn_user,
    cfg={"scrub_injected_turns": False, "log_stats": False},
)
t7_ok = any(guard._is_synthetic(m) for m in out_off)
check("T7 开关关闭时不清污", t7_ok, f"注入 {sum(1 for m in out_off if guard._is_synthetic(m))} 条")

# --- 额外：无裁剪路径（state 为空）也要清污 ----------------------------------
star = make_plugin({"scrub_injected_turns": True, "log_stats": False})
ev = FakeEvent({})
ctx = FakeCtx(list(live))
asyncio.run(star.restore_history(ev, ctx, None))
t9_ok = not any(guard._is_synthetic(m) for m in ctx.messages)
check("T9 未裁剪轮次也清污", t9_ok, f"剩 {sum(1 for m in ctx.messages if guard._is_synthetic(m))} 条")

# --- T10 生产场景：original_msgs 自带上一轮残留的假消息 -----------------------
# guard() 跑在 EmotionAI 之前，它 stash 的 original 是从 DB 读出的历史；
# 修复前那段历史里本来就躺着上一轮的假三条。还原后必须一并清掉。
dirty_history = [
    M("user", "在买饭"),
    M("assistant", "好，买个热的"),
    M("user", FAKE_USER),          # 上一轮残留
    M("assistant", FAKE_ASSISTANT),
    M("system", FORCE_SYSTEM),
    M("user", "何意味"),
    M("assistant", "<thought>\n1. 感知：他问何意味。\n5. 更新：joy:0\n</thought>\n随便问问"),
]
live2 = [
    M("system", "You are Miruku."),
    *dirty_history,
    M("user", "今天打舞萌了吗"),
    M("assistant", "<thought>\n1. 感知：他问舞萌。\n</thought>\n打了，R 值还行"),
    M("user", FAKE_USER),          # 本轮新注入
    M("assistant", FAKE_ASSISTANT),
    M("system", FORCE_SYSTEM),
]
out10 = run_restore(dirty_history, live2, begin_turn=live2[7])
t10_ok = not any(guard._is_synthetic(m) for m in out10)
check("T10 原始历史自带残留也被清", t10_ok,
      f"剩 {sum(1 for m in out10 if guard._is_synthetic(m))} 条")

t10_keep = any("随便问问" in (m["content"] if isinstance(m, dict) else "") for m in out10)
check("T11 历史正文未被误删", t10_keep, repr([str(m)[:40] for m in out10]))

t11_count = len(out10) == 1 + 5 + 2  # system + 5 真实历史 + user + assistant
check("T12 条数正确", t11_count, f"实际 {len(out10)}")

# --- 汇总 -------------------------------------------------------------------
print("=" * 62)
passed = 0
for name, ok, detail in results:
    mark = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    print(f"  [{mark}] {name}")
    if detail and not ok:
        print(f"         {detail}")
print("=" * 62)
print(f"  {passed}/{len(results)} 通过")
sys.exit(0 if passed == len(results) else 1)
