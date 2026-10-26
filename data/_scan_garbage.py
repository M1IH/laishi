# -*- coding: utf-8 -*-
"""全量扫描历史里的注入垃圾（EmotionAI 伪轮次 / PROTOCOL_ENFORCEMENT / 自检）。"""
import json
import sqlite3
from pathlib import Path

DB = Path(
    r"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176"
    r"\core\data\data_v4.db"
)
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = con.execute(
    "select conversation_id, user_id, content from conversations"
).fetchall()
con.close()


def parts(c):
    if isinstance(c, list):
        return c
    s = str(c)
    if s.startswith("["):
        try:
            return eval(s, {"__builtins__": {}})
        except Exception:
            pass
    return [{"type": "text", "text": s}]


def full(c):
    return "".join(
        (p.get("text") or "")
        for p in parts(c)
        if isinstance(p, dict) and p.get("type") == "text"
    )


MARKS = [
    "[PROTOCOL_ENFORCEMENT]",
    "系统自检",
    "请报告当前情感状态",
    "REQUIRED ACTION: Generate XML",
    "<thought>",
    "星绘的情感核心",
]

for conv_id, user_id, raw in rows:
    msgs = json.loads(raw)
    hits = []
    for i, m in enumerate(msgs):
        t = full(m.get("content"))
        for mk in MARKS:
            if mk in t:
                hits.append((i, m.get("role"), mk, t[:100]))
                break
    print(f"### {user_id}  共 {len(msgs)} 条  命中 {len(hits)}")
    for i, role, mk, snip in hits:
        print(f"   [{i}] {role:<9} mark={mk!r}")
        print(f"        {snip!r}")
    print()
