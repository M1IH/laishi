# -*- coding: utf-8 -*-
"""清理被 EmotionAI 注入并落库的伪造轮次。

处理规则（保守）：
1. 纯注入消息 —— 整条删除：
   - user 内容等于/含 "（系统自检：请报告当前情感状态）"
   - system 内容含 "[PROTOCOL_ENFORCEMENT]"
   - assistant 内容与 EmotionAI 伪造样本逐字一致（即以 "<thought>" 开头、
     含 "收到系统自检指令"、以 "当前状态正常。" 或 "报告前辈" 结尾）
2. 只把 <thought>…</thought> 剥掉、保留真实回复文本：
   - 其他 assistant 消息（这些是模型真实产出，可能确实发过）

用法：
    python data/clean_emotionai_injection.py --dry-run
    python data/clean_emotionai_injection.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path(
    r"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176"
    r"\core\data\data_v4.db"
)
BACKUP_DIR = Path(r"C:\Users\OTTO\Desktop\来世\data\backups")

FAKE_USER = "（系统自检：请报告当前情感状态）"
PROTOCOL = "[PROTOCOL_ENFORCEMENT]"
FAKE_SAMPLE_HINT = "收到系统自检指令"

THOUGHT_RE = re.compile(
    r"(?:```(?:xml|text)?\s*)?<(?:thought|thinking)>[\s\S]*?</(?:thought|thinking)>(?:\s*```)?",
    re.IGNORECASE,
)


def parts(content):
    if isinstance(content, list):
        return content
    s = str(content)
    if s.startswith("["):
        try:
            return eval(s, {"__builtins__": {}})
        except Exception:
            pass
    return [{"type": "text", "text": s}]


def text_of(content) -> str:
    return "".join(
        (p.get("text") or "")
        for p in parts(content)
        if isinstance(p, dict) and p.get("type") == "text"
    )


def classify(msg):
    """-> 'drop' | 'strip' | 'keep'"""
    role = str(msg.get("role", ""))
    t = text_of(msg.get("content"))
    if role == "user" and FAKE_USER in t:
        return "drop"
    if role == "system" and PROTOCOL in t:
        return "drop"
    if role == "assistant" and FAKE_SAMPLE_HINT in t and "<thought>" in t:
        return "drop"
    if THOUGHT_RE.search(t):
        return "strip"
    return "keep"


def rewrite_stripped(msg):
    """把 content 里内联的 <thought> 去掉，返回 (新msg, 是否改动)。"""
    content = msg.get("content")
    if isinstance(content, str):
        new = THOUGHT_RE.sub("", content).strip()
        if new != content:
            out = dict(msg)
            out["content"] = new
            return out, True
        return msg, False
    if isinstance(content, list):
        changed = False
        new_parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                txt = p.get("text") or ""
                new = THOUGHT_RE.sub("", txt)
                if new != txt:
                    changed = True
                    new = new.strip()
                    if not new:
                        continue
                    new_parts.append({**p, "text": new})
                    continue
            new_parts.append(p)
        if changed:
            out = dict(msg)
            out["content"] = new_parts
            return out, True
        return msg, False
    return msg, False


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"[FAIL] DB not found: {db}")
        return 1

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select conversation_id, user_id, content from conversations"
    ).fetchall()

    plan = []
    for row in rows:
        uid = row["user_id"]
        msgs = json.loads(row["content"])
        kept, dropped, stripped = [], [], []
        for i, m in enumerate(msgs):
            kind = classify(m)
            if kind == "drop":
                dropped.append((i, str(m.get("role")), text_of(m.get("content"))[:60]))
                continue
            if kind == "strip":
                nm, ch = rewrite_stripped(m)
                if ch:
                    stripped.append((i, text_of(m.get("content"))[:40], text_of(nm.get("content"))[:40]))
                    kept.append(nm)
                    continue
            kept.append(m)
        if dropped or stripped:
            plan.append(
                {
                    "cid": row["conversation_id"],
                    "uid": uid,
                    "before": len(msgs),
                    "after": len(kept),
                    "dropped": dropped,
                    "stripped": stripped,
                    "content": kept,
                }
            )

    if not plan:
        print("[OK] 没有发现需要清理的注入残留。")
        con.close()
        return 0

    print(f"=== 计划：{len(plan)} 个会话需要处理 ===")
    for p in plan:
        print(f"\n--- {p['uid']} ---")
        print(f"    条数 {p['before']} -> {p['after']}（删 {len(p['dropped'])}，剥 thought {len(p['stripped'])}）")
        for i, role, snip in p["dropped"]:
            print(f"    DROP  [{i}] {role:<9} {snip!r}")
        for i, old, new in p["stripped"]:
            print(f"    STRIP [{i}] {old!r} -> {new!r}")

    total_drop = sum(len(p["dropped"]) for p in plan)
    total_strip = sum(len(p["stripped"]) for p in plan)
    print(f"\n合计：删除 {total_drop} 条，剥离 thought {total_strip} 条")

    if args.dry_run:
        print("\n[dry-run] 未写入。")
        con.close()
        return 0

    # 备份
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = BACKUP_DIR / f"emotionai-injection-clean-{stamp}"
    bdir.mkdir(parents=True, exist_ok=True)
    bpath = bdir / db.name
    bcon = sqlite3.connect(str(bpath))
    con.backup(bcon)
    bcon.close()
    print(f"\n备份 -> {bpath}")

    try:
        con.execute("begin immediate")
        for p in plan:
            con.execute(
                "update conversations set content=? where conversation_id=?",
                (json.dumps(p["content"], ensure_ascii=False), p["cid"]),
            )
        con.execute("commit")
    except Exception as exc:
        con.execute("rollback")
        print(f"[FAIL] 写入失败，已回滚：{exc}")
        con.close()
        return 1

    # 复核
    ver = con.execute(
        "select user_id, content from conversations where user_id=?",
        ("miruku:FriendMessage:10000002",),
    ).fetchone()
    if ver:
        msgs = json.loads(ver[1])
        left = sum(
            1
            for m in msgs
            if classify(m) == "drop"
        )
        print(f"[verify] 来世会话现在 {len(msgs)} 条，残留注入 {left} 条")
    con.close()
    print("[OK] 已写回。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
