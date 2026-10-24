#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`knowledge/add.py` 的自测：证明「预演分数可信、低分会被拦、失败不毁库」。

为什么需要它：add.py 会**写文件并重建库**。在把它交给 OTTO 之前，必须先证明
三件事——否则"加知识"这个动作本身就是风险：

  1. 预演分数 == 运行期真实分数（不然预演就是自欺）
  2. 写得不对的条目会被拦住（不然等于没有把关）
  3. 重建失败时目标库不会被截断（不然一次构建会毁掉一次真实对话）

全部只读 src + 临时目录，不碰 `knowledge/miruku_knowledge.sqlite3`。

用法：python data/probe_add_knowledge.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "knowledge"))

import add as A  # noqa: E402
import build_knowledge_db as B  # noqa: E402
import query as Q  # noqa: E402

FAILS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global FAILS
    FAILS += 0 if cond else 1
    print(f"{'PASS' if cond else 'FAIL'}  {name}{('  — ' + detail) if detail and not cond else ''}")


def load_b50() -> dict:
    with open(ROOT / "knowledge" / "src" / "b50.json", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    data = load_b50()
    entries = data["entries"]
    king = next(e for e in entries if e["slug"] == "b50-17-king")

    # ---------- 1. 预演分数必须等于真实检索分数
    q = "KING你多少分"
    preview = dict(A.preview(king, [q]))[q]
    real_hits = Q.search(str(A.DB_PATH), q, None, 5, include_sensitive=True)
    real = next((h["score"] for h in real_hits if h["slug"] == "b50-17-king"), None)
    check("预演分数 == 真实检索分数（预演可信）",
          real is not None and abs(preview - real) < 0.01,
          f"preview={preview} real={real}")

    # ---------- 2. 只写全称、不给简称 → 0 分，必须被拦
    weak = {
        "slug": "probe-weak", "title": "ENERGY SYNERGY MATRIX",
        "aliases": ["ENERGY SYNERGY MATRIX"], "summary": "定数 13.0。",
        "tags": [], "detail": "",
    }
    s_weak = dict(A.preview(weak, ["ESM 怎么样"]))["ESM 怎么样"]
    check("缺简称 → 低于注入阈值（会被拦）", s_weak < A.INJECT_MIN_SCORE, f"score={s_weak}")

    # ---------- 3. 补上简称 → 过阈值
    strong = dict(weak, aliases=["ESM", "ENERGY SYNERGY MATRIX"])
    s_strong = dict(A.preview(strong, ["ESM 怎么样"]))["ESM 怎么样"]
    check("补了简称 → 过阈值（会被放进上下文）", s_strong >= A.INJECT_MIN_SCORE, f"score={s_strong}")
    check("补简称后分数高于缺简称", s_strong > s_weak, f"{s_weak} → {s_strong}")

    # ---------- 4~6. 结构校验该拦的三类
    used = {e["slug"] for e in entries}
    over = dict(strong, summary="字" * 61)
    check("summary 超 60 字 → 报错",
          any("60" in e for e in A.check_structure(over, used, False)))
    dup = dict(strong, slug=king["slug"])   # 用一个真实存在的 slug 测重复
    check("slug 重复 → 报错",
          any("已存在" in e for e in A.check_structure(dup, used, False)))
    check("aliases 为空 → 报错",
          any("aliases" in e for e in A.check_structure(dict(strong, aliases=[]), used, False)))
    check("合法条目 → 无错",
          A.check_structure(strong, used, False) == [])

    # ---------- 7. 重建时目标库被占用 → 抛错，且**不截断**目标库
    d = Path(tempfile.mkdtemp())
    db, dg = d / "k.db", d / "k.md"
    B.build(str(ROOT / "knowledge" / "src"), str(db), str(dg))
    con = sqlite3.connect(db)          # 模拟运行期进程持有连接
    con.execute("select 1 from entries limit 1").fetchall()
    n_before = con.execute("select count(*) from entries").fetchone()[0]
    size_before = db.stat().st_size
    raised = False
    try:
        B.build(str(ROOT / "knowledge" / "src"), str(db), str(dg))
    except PermissionError:
        raised = True
    con.close()
    n_after = sqlite3.connect(db).execute("select count(*) from entries").fetchone()[0]
    size_after = db.stat().st_size
    check("被占用时重建抛 PermissionError（而不是静默覆盖）", raised)
    check("目标库未被截断（条目数与体积不变）",
          n_before == n_after and size_before == size_after,
          f"{n_before}/{size_before} → {n_after}/{size_after}")
    check("失败后不留 .tmp 残骸", not list(d.glob("*.tmp")))

    print(f"\n{'ALL PASS' if FAILS == 0 else str(FAILS) + ' FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
