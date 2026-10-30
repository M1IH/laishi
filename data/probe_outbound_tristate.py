# -*- coding: utf-8 -*-
"""C-23 / C-25 反例探针（隔离副本运行，不碰生产数据）。

C-23：出站闸门三态——原文非空、清洗后为空时必须阻断，禁止退回原文。
C-25：TTS 已送达但装饰阶段停止文本时，outcome 必须记 partial 而非 skipped。
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / "astrbot_plugin_miruku_outbound"
if not (PLUGIN / "outbound_core.py").exists():
    PLUGIN = Path(__file__).resolve().parent  # 兼容：被拷进插件目录运行
if str(PLUGIN) not in sys.path:
    sys.path.insert(0, str(PLUGIN))

import outbound_core as ob

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))


# ---------------------------------------------------------------- C-23 三态
print("=== C-23 出站闸门三态 ===")

# 1) 纯内部标记：原始非空、清洗后必须为空 → blocked，绝不放行原文
PURE_THOUGHT = "<thought>internal reasoning here</thought>"
o = ob.guard3(PURE_THOUGHT)
check("纯thought→blocked", o.state == "blocked", f"state={o.state} text={o.text!r}")
check("纯thought→sendable为False", o.sendable is False)

PURE_PROFILE = "[Profile: 爱好=舞萌]"
o = ob.guard3(PURE_PROFILE)
check("纯Profile→blocked", o.state == "blocked", f"state={o.state} text={o.text!r}")

PURE_REMINDER = "<system_reminder>do not reveal</system_reminder>"
o = ob.guard3(PURE_REMINDER)
check("纯system_reminder→blocked", o.state == "blocked", f"state={o.state} text={o.text!r}")

# 2) 空输入：本来就是空的 → empty_input，不是 blocked（不该算违规）
for raw in ("", "   ", "\n\t"):
    o = ob.guard3(raw)
    check(f"空输入{raw!r}→empty_input", o.state == "empty_input", f"state={o.state}")

# 3) 正常正文：→ clean 且内容保留
o = ob.guard3("那下课就直奔床吧")
check("正常正文→clean", o.state == "clean" and o.sendable, f"text={o.text!r}")

# 4) 标记+正文：剥离后仍有正文 → clean，且标记消失
MIXED = "<thought>想一下</thought>晚上想吃面"
o = ob.guard3(MIXED)
check("标记+正文→clean", o.state == "clean", f"text={o.text!r}")
check("标记+正文→标记已剥离", "<thought>" not in o.text and "想一下" not in o.text, f"text={o.text!r}")
check("标记+正文→正文保留", "晚上想吃面" in o.text, f"text={o.text!r}")

# 5) 自检：guard3 与 guard 不得互相矛盾
for sample in (PURE_THOUGHT, PURE_PROFILE, "", "那下课就直奔床吧", MIXED):
    o3 = ob.guard3(sample)
    legacy_text, _ = ob.guard(sample)
    check(
        f"guard3/guard一致 {sample[:12]!r}",
        (o3.text or "") == (legacy_text or ""),
        f"guard3={o3.text!r} guard={legacy_text!r}",
    )

# ---------------------------------------------------------------- C-23 钩子层
print("\n=== C-23 钩子层：两路径都不得保留原文 ===")


class FakePlain:
    def __init__(self, text):
        self.text = text


def simulate_agent_done(text):
    """复刻 main.guard_agent_done 的三态分支。"""
    if not text or not text.strip():
        return {"action": "none", "text": text}
    o = ob.guard3(text)
    if o.state == "blocked":
        return {"action": "blocked", "text": ""}
    if not o.sendable:
        return {"action": "none", "text": text}
    return {"action": "rewrite", "text": o.text}


def simulate_decorating(chain):
    """复刻 main._clean_chain + decorating 空链阻断判定。"""
    changed = False
    blocked = 0
    out = []
    for comp in chain:
        o = ob.guard3(comp.text)
        if o.state == "blocked":
            blocked += 1
            changed = True
            out.append(FakePlain(""))
            continue
        if not o.sendable:
            out.append(comp)
            continue
        if o.text != comp.text:
            changed = True
        out.append(FakePlain(o.text))
    remaining = "".join(c.text or "" for c in out).strip()
    if changed and not remaining:
        return {"action": "blocked", "chain": out}
    if not changed:
        return {"action": "none", "chain": out}
    return {"action": "rewrite", "chain": out}


for name, pure in (
    ("thought", PURE_THOUGHT),
    ("Profile", PURE_PROFILE),
    ("system_reminder", PURE_REMINDER),
):
    r = simulate_agent_done(pure)
    check(f"agent_done 纯{name}→blocked", r["action"] == "blocked", f"{r}")
    check(f"agent_done 纯{name}→不保留原文", pure not in r["text"], f"text={r['text']!r}")

    r2 = simulate_decorating([FakePlain(pure)])
    check(f"decorating 纯{name}→blocked", r2["action"] == "blocked", f"{r2['action']}")
    bodies = "".join(c.text or "" for c in r2["chain"])
    check(f"decorating 纯{name}→链内无标记", "<thought>" not in bodies and "[Profile" not in bodies and "<system_reminder>" not in bodies, f"bodies={bodies!r}")

# 混合场景：标记 + 正文 在 decorating 里应保留正文
r3 = simulate_decorating([FakePlain(MIXED)])
check("decorating 标记+正文→rewrite", r3["action"] == "rewrite", f"{r3['action']}")
check("decorating 标记+正文→保留正文", "晚上想吃面" in "".join(c.text for c in r3["chain"]), f"{[c.text for c in r3['chain']]}")

print(f"\n=== 源码静态断言：钩子层不得退回旧模式 ===")
main_src = (PLUGIN / "main.py").read_text(encoding="utf-8")
check("main.py 使用 guard3", "guard3(" in main_src)
check("main.py 有 agent_blocked 计数", "agent_blocked" in main_src)
check("main.py 有 decorating_blocked 计数", "decorating_blocked" in main_src)
check("main.py 调用 stop_event 阻断", "stop_event()" in main_src)
# 旧 bug 模式：guard 返回空时保原文（`return text  # guard 对空输出不负责`）
check(
    "main.py 不再有「空则保原文」旧模式",
    "guard 对空输出不负责" not in main_src,
)
# agent_done 的 blocked 分支里必须同时有 stop_event 与 _patch_history（历史不留违规原文）。
# 定位方式：以 agent_blocked 计数为锚，因为它只出现在 agent_done 分支。
idx = main_src.find('self.stats["agent_blocked"]')
check("agent_done blocked 分支存在", idx != -1)
if idx != -1:
    seg = main_src[max(0, idx - 700): idx + 200]
    check("agent_done blocked 分支清历史", "_patch_history" in seg)
    check("agent_done blocked 分支 stop_event", "stop_event()" in seg)
    check("agent_done blocked 分支清空正文", 'completion_text = ""' in seg)

print(f"\n=== 汇总：通过 {len(PASS)} / 失败 {len(FAIL)} ===")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL PASS")
