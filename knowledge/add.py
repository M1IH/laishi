#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往知识库加一条知识 / 改一条知识，并当场验证「她真的会用上」。

为什么需要这个脚本
------------------
写进 JSON ≠ 能被检索到。`inject.build_block` 只注入 **score >= 10.0** 的条目，
一条新条目如果标题和别名写得不对，可能只有 1~7 分——库里有、聊天时永远不出现，
而且是**静默**不出现（没有任何报错）。

b50 那轮就踩过：单曲条目只 3.2 分，把曲名插成第一条别名才到 20.0。

所以本脚本把「写」和「验证命中」绑成一步：分数不够就不落盘。

用法
----
    # 看有哪些主题
    python knowledge/add.py --list-topics

    # 新增一条（--test 必须写真实会出现的问法）
    python knowledge/add.py --topic maimai \
        --slug xin-qu-ming --title "新曲名" --aliases "新曲,别名2" \
        --summary "定数 13.2，她打过。" --test "你怎么看新曲名"

    # 只预演，不落盘
    python knowledge/add.py ... --dry-run

    # 改已有条目（例如 b50 成绩刷新；只覆盖你给的字段）
    python knowledge/add.py --topic b50 --update wo-de-b50 \
        --summary "..." --test "你R值多少"

    # 排查「她为什么不知道这首」：对已有条目跑命中预演
    python knowledge/add.py --topic maimai --check xin-qu-ming --test "新曲名多少分"

退出码
------
    0 成功（或预演通过）／ 1 校验或命中失败 ／ 2 环境问题（缺文件等）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_knowledge_db as B  # noqa: E402
import query as Q  # noqa: E402

SRC_DIR = HERE / "src"
DB_PATH = HERE / "miruku_knowledge.sqlite3"
DIGEST_PATH = HERE / "digest.md"

INJECT_MIN_SCORE = 10.0   # 与 inject.build_block 的默认 min_score 一致，别单独调
SUMMARY_MAX = 60          # 与 build_knowledge_db 的校验一致


# ---------------------------------------------------------------- 文件读写

def fmt_of(path: Path) -> tuple[int, bool]:
    """推断原文件的缩进宽度与换行风格，写回时保持一致（别把整个文件重排版）。"""
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    indent = 1
    lines = raw.split(b"\n")
    if len(lines) > 1:
        n = len(lines[1]) - len(lines[1].lstrip(b" "))
        indent = n if n > 0 else 1
    return indent, crlf


def write_topic(path: Path, data: dict, indent: int, crlf: bool) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text + ("\r\n" if crlf else "\n"))


def load_topic(topic: str) -> tuple[Path, dict]:
    path = SRC_DIR / f"{topic}.json"
    if not path.exists():
        avail = ", ".join(p.stem for p in sorted(SRC_DIR.glob("*.json")))
        raise SystemExit(f"[FAIL] 没有这个主题：{path}\n       现有主题：{avail}")
    with open(path, "r", encoding="utf-8") as f:
        return path, json.load(f)


# ---------------------------------------------------------------- 校验

def split_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    for sep in ("、", "|", ";"):
        raw = raw.replace(sep, ",")
    return [s.strip() for s in raw.split(",") if s.strip()]


def check_structure(entry: dict, used_slugs: set[str], is_update: bool) -> list[str]:
    errs = []
    if not str(entry.get("title", "")).strip():
        errs.append("title 不能为空")
    if not str(entry.get("summary", "")).strip():
        errs.append("summary 不能为空")
    elif len(entry["summary"].strip()) > SUMMARY_MAX:
        errs.append(f"summary {len(entry['summary'].strip())} 字，超过 {SUMMARY_MAX} 字上限（构建会报错）")
    if not str(entry.get("slug", "")).strip():
        errs.append("slug 不能为空（拼音，同主题内唯一）")
    elif not is_update and entry["slug"] in used_slugs:
        errs.append(f"slug 已存在：{entry['slug']}（同主题内必须唯一）")
    if not entry.get("aliases"):
        errs.append("aliases 为空：只靠标题命中率很低，至少写 2~3 个真实叫法")
    return errs


def check_conflict(entry: dict, others: list[dict]) -> list[str]:
    """标题或别名与别的条目完全相同 → 两个条目会互相抢分，提示但不阻断。"""
    mine = {Q.normalize(entry.get("title", ""))} | {Q.normalize(a) for a in entry.get("aliases", [])}
    mine.discard("")
    hits = []
    for o in others:
        if o.get("slug") == entry.get("slug"):
            continue
        theirs = {Q.normalize(o.get("title", ""))} | {Q.normalize(a) for a in o.get("aliases", [])}
        dup = mine & theirs
        if dup:
            hits.append(f"{o.get('title')}（{o.get('topic')}:{o.get('slug')}）重合 {sorted(dup)}")
    return hits


# ---------------------------------------------------------------- 命中预演

def preview(entry: dict, tests: list[str]) -> list[tuple[str, float]]:
    """用 query.score 直接给分。score 是纯函数（无 idf / 无全局统计），
    所以这里的分数与运行期注入时的分数**一致**，不需要先落盘。

    `topic` 必须带上，否则预演会**系统性低估**：`query.score()` 里
    「别名 clean 后与整句相同」这条 20.0 的路径只对 topic 为 self/b50 的
    条目生效（`query.py:731`）。漏了它，self 的「你多少分」预演只有 5.00、
    运行期实际 55.00，`add.py` 会据此拒绝一条本来完全够用的别名。
    （2026-10-26 实测：漏 topic 时 5.00 / 2.50，带上 topic 时 55.00 / 49.50。）
    """
    probe = {
        "topic": entry.get("topic", ""),
        "title": entry.get("title", ""),
        "aliases": list(entry.get("aliases") or []),
        "summary": entry.get("summary", ""),
        "tags": list(entry.get("tags") or []),
        "detail": entry.get("detail", ""),
    }
    return [(q, round(Q.score(probe, q), 2)) for q in tests]


def report_preview(pairs: list[tuple[str, float]], min_score: float) -> tuple[bool, list[tuple[str, float]]]:
    fails = []
    for q, s in pairs:
        ok = s >= min_score
        mark = "OK  " if ok else "LOW "
        print(f"      {mark}{q:<24} {s:>6.2f}")
        if not ok:
            fails.append((q, s))
    return (not fails), fails


def advice(fails: list[tuple[str, float]]) -> None:
    print("\n  [为什么不过] 注入阈值 %.1f 分，低于它这条永远不会进上下文（且不报错）。" % INJECT_MIN_SCORE)
    print("  [怎么办] 按优先级补：")
    print("      1. 把问句里**最可能出现的那个词**原样加进 aliases（b50 单曲就是这么从 3.2 → 20.0）")
    print("      2. 确认标题不是生僻写法——她听来的叫法往往是简称/谐音")
    print("      3. 确实只想放背景知识、不指望被问到时，用 --allow-weak 强制写入并在备注里写清")
    if fails:
        worst = min(fails, key=lambda x: x[1])
        print(f"  [当前最差] 「{worst[0]}」只有 {worst[1]:.2f} 分")


# ---------------------------------------------------------------- 构建

def rebuild() -> tuple[bool, str]:
    try:
        B.build(str(SRC_DIR), str(DB_PATH), str(DIGEST_PATH))
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def count_entries(data: dict) -> int:
    return len(data.get("entries") or [])


# ---------------------------------------------------------------- 主流程

def cmd_list_topics() -> int:
    print("现有主题（knowledge/src/*.json）：")
    total = 0
    for p in sorted(SRC_DIR.glob("*.json")):
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        n = count_entries(d)
        total += n
        print(f"  {p.stem:<12} {n:>4} 条   {d.get('title', '')}")
    print(f"  {'合计':<12} {total:>4} 条")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="加/改一条知识，并验证它能被检索到")
    ap.add_argument("--list-topics", action="store_true", help="列出所有主题")
    ap.add_argument("--topic", help="主题 = knowledge/src/<topic>.json 的文件名")
    ap.add_argument("--slug", help="条目 id，同主题内唯一（拼音）")
    ap.add_argument("--title", help="条目标题")
    ap.add_argument("--aliases", help="别名，逗号或顿号分隔")
    ap.add_argument("--summary", help="一句话总结（≤60 字，会被注入 prompt）")
    ap.add_argument("--detail", help="补充事实（不进 prompt，只供人工与全文检索）")
    ap.add_argument("--tags", help="标签，逗号分隔")
    ap.add_argument("--source", help="来源（URL 或「聊天记录」）")
    ap.add_argument("--confidence", default=None, choices=["high", "medium", "low"])
    ap.add_argument("--sensitive", action="store_true", help="敏感条目：运行期默认不注入")
    ap.add_argument("--test", help="必须命中的真实问法，多个用 | 分隔")
    ap.add_argument("--min-score", type=float, default=INJECT_MIN_SCORE)
    ap.add_argument("--allow-weak", action="store_true", help="分数不够也强制写入")
    ap.add_argument("--dry-run", action="store_true", help="只预演不落盘")
    ap.add_argument("--update", metavar="SLUG", help="改已有条目（只覆盖你给的字段）")
    ap.add_argument("--check", metavar="SLUG", help="只对已有条目跑命中预演")
    ap.add_argument("--no-build", action="store_true", help="只改 JSON，不重建库（一般别用）")
    args = ap.parse_args()

    if args.list_topics:
        return cmd_list_topics()
    if not args.topic:
        ap.error("需要 --topic（或用 --list-topics 看现有主题）")

    path, data = load_topic(args.topic)
    entries = data.get("entries") or []
    indent, crlf = fmt_of(path)
    tests = split_list(args.test)

    # ---- 模式 1：--check（只预演已有条目）
    if args.check:
        target = next((e for e in entries if e.get("slug") == args.check), None)
        if target is None:
            print(f"[FAIL] {args.topic} 里没有 slug={args.check}")
            return 2
        if not tests:
            ap.error("--check 需要 --test 给问法")
        print(f"[1/2] 已有条目：{target.get('title')}（{args.topic}:{args.check}）")
        pairs = preview(target, tests)
        ok, fails = report_preview(pairs, args.min_score)
        if not ok:
            advice(fails)
        print("\n[2/2] 该条目是否被别的条目抢分（真实检索前 3）")
        for q in tests:
            hits = Q.search(str(DB_PATH), q, None, 3, include_sensitive=True)
            print(f"      「{q}」→ " + ("；".join(f"{h['title']}({h['score']})" for h in hits) or "无命中"))
        return 0 if ok else 1

    # ---- 模式 2：新增 / 更新
    is_update = bool(args.update)
    if is_update:
        idx = next((i for i, e in enumerate(entries) if e.get("slug") == args.update), None)
        if idx is None:
            print(f"[FAIL] {args.topic} 里没有 slug={args.update}")
            return 2
        entry = dict(entries[idx])
        # JSON 源里没有 topic（它由 src 文件名决定、只在建库时写进 DB），
        # 但 preview() 要靠 topic 才能走对分支，这里补上。
        entry["topic"] = args.topic
        replaced = {k: v for k, v in {
            "title": args.title, "summary": args.summary, "detail": args.detail,
            "source": args.source, "confidence": args.confidence,
        }.items() if v is not None}
        if args.aliases is not None:
            replaced["aliases"] = split_list(args.aliases)
        if args.tags is not None:
            replaced["tags"] = split_list(args.tags)
        if args.sensitive:
            replaced["sensitive"] = True
        if not replaced:
            ap.error("--update 至少要给一个要改的字段")
        entry.update(replaced)
        print(f"[1/5] 改已有条目 {args.update}，覆盖字段：{', '.join(replaced)}")
    else:
        entry = {
            "topic": args.topic,
            "slug": args.slug or "",
            "title": args.title or "",
            "aliases": split_list(args.aliases),
            "summary": args.summary or "",
            "detail": args.detail or "",
            "tags": split_list(args.tags),
            "source": args.source or "",
            "confidence": args.confidence or "medium",
            "sensitive": bool(args.sensitive),
        }
        print("[1/5] 新增条目")

    # ---- 校验
    used = {e.get("slug") for e in entries} - ({args.update} if is_update else set())
    errs = check_structure(entry, used, is_update)
    if errs:
        print("\n[2/5] 结构校验 ✗")
        for e in errs:
            print(f"      - {e}")
        return 1
    print(f"[2/5] 结构校验 OK（summary {len(entry['summary'].strip())} 字 / 别名 {len(entry['aliases'])} 个）")

    conflicts = check_conflict(entry, [e for e in entries if e.get("slug") != entry["slug"]])
    if conflicts:
        print("      提醒：与已有条目有完全相同的标题/别名（会互相抢分，酌情改）")
        for c in conflicts:
            print(f"        · {c}")

    # ---- 命中预演（核心）
    if tests:
        print(f"[3/5] 命中预演（阈值 {args.min_score}）")
        pairs = preview(entry, tests)
        ok, fails = report_preview(pairs, args.min_score)
        if not ok and not args.allow_weak:
            advice(fails)
            print("\n[未写入] 这条现在加进去，她也用不上。补好别名后重跑。")
            return 1
        if not ok and args.allow_weak:
            print("      [--allow-weak] 分数不达标但按你的要求写入（她大概率不会被问到时想起它）")
    else:
        print("[3/5] 命中预演 跳过（没给 --test）")
        print("      警告：不做这一步，等于不知道她能不能用上它。强烈建议补 --test。")

    if args.dry_run:
        print("\n[--dry-run] 到此为止，未写入任何文件、未重建库。")
        return 0

    # ---- 写入
    # topic 只存在于 DB 与内存里（JSON 文件名就是 topic），写回前必须摘掉，
    # 否则每次 add.py 都会往源 JSON 里塞一个新字段，源文件被慢慢污染。
    entry.pop("topic", None)
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_bytes(path.read_bytes())
    try:
        if is_update:
            entries[next(i for i, e in enumerate(entries) if e.get("slug") == args.update)] = entry
        else:
            entries.append(entry)
        data["entries"] = entries
        write_topic(path, data, indent, crlf)
        print(f"[4/5] 已写入 {path.name}（{len(entries)} 条，备份 {backup.name}）")

        if args.no_build:
            print("[5/5] --no-build：库未重建，改动**不会生效**，记得手动跑 build_knowledge_db.py")
            return 0

        started = time.perf_counter()
        ok, err = rebuild()
        elapsed = time.perf_counter() - started
        if not ok:
            raise RuntimeError(err)
        print(f"[5/5] 库已重建（{elapsed:.2f}s）")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] {type(exc).__name__}: {exc}")
        path.write_bytes(backup.read_bytes())
        print("      已回滚 JSON，重建一次库以恢复原状…")
        ok2, err2 = rebuild()
        print("      回滚后重建：" + ("OK" if ok2 else f"又失败 {err2}"))
        if not ok2:
            print("      库可能处于旧版本（src 已回滚，两者仍自洽）。")
        print("      若是 PermissionError：说明此刻进程正在读库（每秒都会读一次）。")
        print("      等她安静几秒再重跑即可——JSON 已回滚，重跑不会重复添加。")
        return 1

    # ---- 真实库复核（不靠预算，直接查一遍）
    if tests:
        print("\n[复核] 用重建后的库真实检索：")
        all_ok = True
        for q in tests:
            hits = Q.search(str(DB_PATH), q, None, 3, include_sensitive=True)
            line = "；".join(f"{h['title']}({h['score']})" for h in hits) or "无命中"
            mine = next((h for h in hits if h["slug"] == entry["slug"]), None)
            flag = "OK" if (mine and mine["score"] >= args.min_score) else "低"
            if not (mine and mine["score"] >= args.min_score):
                all_ok = False
            print(f"      [{flag}] 「{q}」→ {line}")
        if not all_ok:
            print("      注意：真实检索与预演不一致，先查 query.py 再说。")
            return 1

    print(f"\n完成。条目 {entry['slug']} 已可用（无需重启进程：每次请求都新开连接读库）。")
    if backup.exists():
        print(f"确认无误后可删除备份：{backup.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
