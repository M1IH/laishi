"""模拟 on_llm_request 钩子：验证「预检索注入」在本机真的能跑通。

不碰运行实例、不改插件，只把准备给 Codex 的那段钩子代码原样执行一遍，
用一个假的 event / req 走完整路径，确认：
  1. 目标号私聊 + 命中 → system_prompt 末尾多出注入块；
  2. 闲聊 / 空命中 → system_prompt 一字不动（不塞空标题行）；
  3. 群聊（同一个人）→ 不注入；
  4. 钩子被调两次 → 不重复追加（防止重试把块叠成两遍）。

用法：python data/probe_inject_hook.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "knowledge"))

import inject  # noqa: E402

MARK = "<!-- miruku-knowledge -->"
TARGET = "10000002"


class FakeEvent:
    def __init__(self, text: str, sender: str = TARGET, private: bool = True):
        self.message_str = text
        self._sender = sender
        self._private = private

    def get_sender_id(self) -> str:
        return self._sender

    def is_private_chat(self) -> bool:
        return self._private


class FakeReq:
    def __init__(self, system_prompt: str = "你是 Miruku。"):
        self.system_prompt = system_prompt


# ---- 下面这段就是准备给 Codex 的钩子本体（原样复制，只加了 MARK 去重） ----
def hook(event: FakeEvent, req: FakeReq, target_qq: str = TARGET) -> bool:
    if not (event.is_private_chat() and event.get_sender_id() == target_qq):
        return False
    if MARK in (req.system_prompt or ""):
        return False
    block = inject.build_block(event.message_str)
    if not block:
        return False
    req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n" + MARK
    return True


CASES = [
    ("你R值多少", True, True),
    ("KING你多少分", True, True),
    ("海底谭多少分", True, True),
    ("你打过14吗", True, True),
    ("ロキ你多少分", True, True),       # 表外曲目：命中曲子背景 + 兜底护栏（不能报数字）
    ("今天好累", True, False),
    ("晚安", True, False),
    ("你R值多少", False, False),        # 群聊
]

# 护栏该出现的时机：问成绩、但块里没有按曲目写死的成绩。
GUARD_CASES = [
    ("ロキ你多少分", True),
    ("シャルル多少分", True),
    ("KING你多少分", False),   # 表内：有真成绩，不需要护栏
    ("海底谭多少分", False),
    ("ロキ这歌怎么样", False),  # 没问成绩：不要多嘴
]


def main() -> int:
    fails = 0
    for text, private, expect in CASES:
        req = FakeReq()
        before = req.system_prompt
        fired = hook(FakeEvent(text, private=private), req)
        ok = fired == expect
        fails += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {text:<12} private={private!s:<5} fired={fired} expect={expect}")
        if fired:
            added = req.system_prompt[len(before):]
            print("        +", added.replace("\n", " ⏎ ")[:150])

    # 去重：同一 req 连续调两次，只加一次
    req = FakeReq()
    a = hook(FakeEvent("你R值多少"), req)
    b = hook(FakeEvent("你R值多少"), req)
    n = req.system_prompt.count("可参考的知识")
    dup_ok = a and not b and n == 1
    fails += 0 if dup_ok else 1
    print(f"{'PASS' if dup_ok else 'FAIL'}  幂等：first={a} second={b} blocks={n}")

    # 护栏：表外曲目的「不要报数字」必须在，表内不能多嘴
    for text, expect in GUARD_CASES:
        has = "只记最好的 50 首" in inject.build_block(text)
        ok = has == expect
        fails += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  护栏 {text:<12} has={has} expect={expect}")

    print(f"\n{'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
