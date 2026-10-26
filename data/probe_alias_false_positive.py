# -*- coding: utf-8 -*-
"""候选别名的全量误注入评估。

做法：不重建库，直接把候选别名贴到内存里的条目上，用 query.score（纯函数）
跑全量 8,663 条真实私聊，与「现状命中」逐条对比，输出新增命中。
新增命中里必须逐条能被认定为「确实在说这首歌」，否则该别名不能用。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "knowledge"))
import query as Q  # noqa: E402

DB = ROOT / "knowledge" / "miruku_knowledge.sqlite3"
CHAT = ROOT / "data" / "chat_content.sqlite3"
S = "10000002"
MIN_SCORE = 10.0


def load_corpus():
    con = sqlite3.connect(f"file:{CHAT}?mode=ro", uri=True)
    rows = [r[0] or "" for r in con.execute(
        "select text from messages where session_key=?", (S,))]
    con.close()
    return [t for t in rows if t.strip()]


def best_score(entries, text):
    """返回该句命中的最高分条目 slug 与分数。"""
    best = (0.0, None)
    for e in entries:
        s = Q.score(e, text)
        if s > best[0]:
            best = (s, e["slug"])
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", required=True, help="候选别名 JSON：{slug: [alias, ...]}")
    ap.add_argument("--limit", type=int, default=40, help="最多打印多少条新增命中")
    args = ap.parse_args()

    patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    base = Q.load_entries(str(DB), None)
    by_slug = {e["slug"]: e for e in base}

    missing = [s for s in patch if s not in by_slug]
    if missing:
        print(f"[注意] 这些 slug 在库里不存在，已跳过：{missing}")

    patched = [dict(e, aliases=list(e["aliases"])) for e in base]
    pby = {e["slug"]: e for e in patched}
    added = 0
    for slug, extra in patch.items():
        if slug not in pby:
            continue
        have = {a.lower() for a in pby[slug]["aliases"]}
        for a in extra:
            if a.lower() not in have:
                pby[slug]["aliases"].append(a)
                added += 1
    print(f"候选别名 {added} 条，涉及 {len(patch)} 个条目\n")

    corpus = load_corpus()
    print(f"语料 {len(corpus)} 条")

    # 先按子串预筛：只有当句子里**真的出现**某个候选别名（或其 normalize 形式）
    # 时，这条别名才可能改变命中结果。其余句子新旧一样，不必重算。
    # 这一步把 8,663 × 560 ≈ 485 万次打分压到只算受影响的那几十条，
    # 结论不变（score() 是纯函数，没出现过的别名不可能加分）。
    probe_forms = set()
    for slug, extra in patch.items():
        for a in extra:
            for form in (a, Q.normalize(a)):
                if len(form) >= 2:
                    probe_forms.add(form)
    print(f"候选别名形态 {len(probe_forms)} 个")

    candidates = []
    for t in corpus:
        tn = Q.normalize(t)
        if any(f in tn for f in probe_forms):
            candidates.append(t)
    print(f"含候选别名的句子 {len(candidates)} 条，只对它们复算\n")

    new_hits = []
    old_hits = 0
    new_total = 0
    for t in candidates:
        old_s, _ = best_score(base, t)
        new_s, new_slug = best_score(patched, t)
        if old_s >= MIN_SCORE:
            old_hits += 1
        if new_s >= MIN_SCORE:
            new_total += 1
            if old_s < MIN_SCORE:
                new_hits.append((t, round(new_s, 1), new_slug))

    print(f"受影响句子现状命中 {old_hits} / {len(candidates)}")
    print(f"加候选后 {new_total} / {len(candidates)}")
    print(f"**新增命中 {len(new_hits)} 条**\n")

    # 按 slug 汇总，方便判断是哪条别名在惹事
    cnt = Counter(h[2] for h in new_hits)
    print("新增命中按条目：")
    for slug, n in cnt.most_common(20):
        print(f"  {n:4d}  {slug}")

    print(f"\n新增命中的句子（最多 {args.limit} 条，逐条判断是不是真的在说这首歌）：")
    for t, s, slug in new_hits[: args.limit]:
        print(f"  [{s}] {slug} <- {t[:50]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
