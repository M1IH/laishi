# -*- coding: utf-8 -*-
"""验证：一轮真实请求后，落库历史里是否还有 EmotionAI 注入。

对比前后条数与注入命中数，并打印最后若干条角色+摘要。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB = Path(
    r"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176"
    r"\core\data\data_v4.db"
)
UID = "miruku:FriendMessage:10000002"

FAKE_USER = "（系统自检：请报告当前情感状态）"
PROTOCOL = "[PROTOCOL_ENFORCEMENT]"
HINT = "收到系统自检指令"


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, dict) and isinstance(p.get("text"), str):
                out.append(p["text"])
        return "".join(out)
    return str(content)


def is_synthetic(role: str, text: str) -> bool:
    if role == "user" and FAKE_USER in text:
        return True
    if role == "system" and PROTOCOL in text:
        return True
    if role == "assistant" and HINT in text and "<thought" in text:
        return True
    return False


def snapshot():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute(
        "select content from conversations where user_id=?", (UID,)
    ).fetchone()
    con.close()
    if not row:
        print(f"[FAIL] 找不到会话 {UID}")
        sys.exit(1)
    msgs = json.loads(row[0])
    bad = 0
    thoughts = 0
    for m in msgs:
        role = str(m.get("role", ""))
        t = text_of(m.get("content"))
        if is_synthetic(role, t):
            bad += 1
        elif "<thought" in t:
            thoughts += 1
    return msgs, bad, thoughts


def main() -> int:
    msgs, bad, thoughts = snapshot()
    print(f"总条数: {len(msgs)}")
    print(f"注入残留: {bad}")
    print(f"残留 <thought> 的消息: {thoughts}")
    print("\n最后 8 条：")
    for m in msgs[-8:]:
        role = m.get("role", "?")
        t = text_of(m.get("content")).replace("\n", " ")[:90]
        print(f"  {role:<10} {t!r}")
    return 0 if bad == 0 and thoughts == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
