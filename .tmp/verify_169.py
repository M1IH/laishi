# -*- coding: utf-8 -*-
"""出站闸门验收 v2：169 条历史重跑 + 改写样例抽查。

数据源：
1. /tmp/chat_content.sqlite3 messages 表（self_uin=10000004 发出的文本）
2. 容器 data_v4.db platform_message_history（type=bot 的 plain）
"""
import json
import os
import re
import sqlite3
import sys

os.environ.setdefault("OUTBOUND_DATA_DIR", "/AstrBot/data/plugin_data/miruku_outbound")
sys.path.insert(0, "/AstrBot/data/plugins/astrbot_plugin_miruku_outbound")
import outbound_core as ob  # noqa: E402

SELF_UIN = "10000004"
L1_RESIDUAL_RE = re.compile(
    r"<thought>|</thought>|<system_reminder>|\[Profile:|<\|?DSML\|?>", re.IGNORECASE)


def texts_chat_content():
    con = sqlite3.connect("/tmp/chat_content.sqlite3")
    rows = con.execute(
        "SELECT sender_uin, text FROM messages "
        "WHERE text IS NOT NULL AND text != '' AND recalled=0 AND system=0"
    ).fetchall()
    con.close()
    return [("chat", t) for uin, t in rows if str(uin) == SELF_UIN]


def texts_v4():
    con = sqlite3.connect("/AstrBot/data/data_v4.db")
    out = []
    for (blob,) in con.execute("SELECT content FROM platform_message_history").fetchall():
        try:
            obj = json.loads(blob)
            if obj.get("type") == "bot":
                for comp in obj.get("message", []):
                    if comp.get("type") == "plain" and comp.get("text"):
                        out.append(("v4", comp["text"]))
        except Exception:
            continue
    con.close()
    return out


def main():
    texts = texts_chat_content() + texts_v4()
    print(f"总计 bot 出站文本 {len(texts)} 条")
    stats = {"raw_l1": 0, "rewritten": 0, "fallback": 0, "empty": 0, "residual": 0}
    for src, body in texts:
        rep = ob.check(body)
        raw_l1 = any(
            str(getattr(v, "layer", "")).upper().startswith("L1")
            for v in (getattr(rep, "violations", []) or []))
        if raw_l1 or L1_RESIDUAL_RE.search(body):
            stats["raw_l1"] += 1
        fixed, fb = ob.guard(body)
        if not fixed:
            stats["empty"] += 1
            continue
        if fixed != body:
            stats["rewritten"] += 1
            print(f"\n--- [{src}] 原文: {body[:100]!r}")
            print(f"    改后: {fixed[:100]!r}  fb={fb}")
        if fb:
            stats["fallback"] += 1
        if L1_RESIDUAL_RE.search(fixed):
            stats["residual"] += 1
            print(f"  [RESIDUAL] {src}: {fixed[:80]!r}")

    print(f"\n=== 验收 ===")
    print(f"原始 L1: {stats['raw_l1']} | 改写: {stats['rewritten']} "
          f"(兜底 {stats['fallback']}, 空输出 {stats['empty']}) | 清洗后 L1 残留: {stats['residual']}")
    print("VERDICT:", "PASS" if stats["residual"] == 0 else "FAIL")


main()
