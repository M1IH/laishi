#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Miruku knowledge database from knowledge/src/*.json.

Each source file is one topic:
  {
    "topic": "maimai",
    "title": "舞萌DX",
    "description": "...",
    "entries": [
      {"slug": "...", "title": "...", "aliases": ["..."],
       "summary": "...", "detail": "...", "tags": ["..."],
       "source": "...", "confidence": "high|medium|low",
       "sensitive": false}
    ]
  }

Usage:
  python knowledge/build_knowledge_db.py
  python knowledge/build_knowledge_db.py --src-dir knowledge/src --db knowledge/miruku_knowledge.sqlite3
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_SRC = os.path.join(HERE, "src")
DEFAULT_DB = os.path.join(HERE, "miruku_knowledge.sqlite3")
DEFAULT_DIGEST = os.path.join(HERE, "digest.md")

REQUIRED = ("slug", "title", "summary")


def load_sources(src_dir: str) -> list[dict]:
    topics = []
    for path in sorted(glob.glob(os.path.join(src_dir, "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        topic = data.get("topic") or os.path.splitext(os.path.basename(path))[0]
        entries = data.get("entries") or []
        seen = set()
        for i, e in enumerate(entries):
            for key in REQUIRED:
                if not str(e.get(key, "")).strip():
                    raise ValueError(f"{path}: entries[{i}] 缺少 {key}")
            if e["slug"] in seen:
                raise ValueError(f"{path}: slug 重复 {e['slug']}")
            seen.add(e["slug"])
            aliases = e.get("aliases") or []
            tags = e.get("tags") or []
            if not isinstance(aliases, list) or not isinstance(tags, list):
                raise ValueError(f"{path}: entries[{i}] aliases/tags 必须是数组")
            summary = e["summary"].strip()
            if len(summary) > 60:
                raise ValueError(f"{path}: {e['slug']} summary 超过 60 字（{len(summary)}）")
        topics.append({
            "topic": topic,
            "title": data.get("title") or topic,
            "description": data.get("description") or "",
            "entries": entries,
            "path": path,
        })
    if not topics:
        raise SystemExit(f"没有找到任何 JSON：{src_dir}")
    return topics


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(src_dir: str, db_path: str, digest_path: str) -> None:
    topics = load_sources(src_dir)
    tmp = db_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    con = sqlite3.connect(tmp)
    con.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE topics(
            topic TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            entry_count INTEGER NOT NULL
        );
        CREATE TABLE entries(
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL REFERENCES topics(topic),
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            aliases TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT,
            confidence TEXT,
            sensitive INTEGER NOT NULL DEFAULT 0,
            UNIQUE(topic, slug)
        );
        CREATE VIRTUAL TABLE entries_fts USING fts5(
            id UNINDEXED,
            title, aliases, summary, detail,
            tokenize='trigram'
        );
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE VIEW v_entries AS
            SELECT id, topic, slug, title, aliases, summary, detail, tags,
                   source, confidence, sensitive
            FROM entries ORDER BY topic, title;
        """
    )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = 0
    for t in topics:
        con.execute(
            "INSERT INTO topics(topic, title, description, entry_count) VALUES (?,?,?,?)",
            (t["topic"], t["title"], t["description"], len(t["entries"])),
        )
        for e in t["entries"]:
            eid = f"{t['topic']}:{e['slug']}"
            aliases = json.dumps(e.get("aliases") or [], ensure_ascii=False)
            tags = json.dumps(e.get("tags") or [], ensure_ascii=False)
            con.execute(
                """INSERT INTO entries(id, topic, slug, title, aliases, summary, detail,
                                        tags, source, confidence, sensitive)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid, t["topic"], e["slug"], e["title"], aliases, e["summary"].strip(),
                    (e.get("detail") or "").strip(), tags, e.get("source") or "",
                    e.get("confidence") or "medium", 1 if e.get("sensitive") else 0,
                ),
            )
            con.execute(
                "INSERT INTO entries_fts(id, title, aliases, summary, detail) VALUES (?,?,?,?,?)",
                (eid, e["title"], aliases, e["summary"].strip(), (e.get("detail") or "").strip()),
            )
            total += 1
        con.execute(
            "INSERT INTO meta(key, value) VALUES (?,?)",
            (f"src:{t['topic']}", sha256_file(t["path"])),
        )

    con.executemany(
        "INSERT INTO meta(key, value) VALUES (?,?)",
        [
            ("built_at_utc", now),
            ("src_dir", os.path.abspath(src_dir)),
            ("topic_count", str(len(topics))),
            ("entry_count", str(total)),
        ],
    )
    con.commit()
    con.close()

    # Windows 上 os.replace 会因杀软/索引瞬时持有 tmp 而抛 WinError 5（拒绝访问）。
    # 处理方式：**短重试，然后明确失败**——不再降级为「覆盖写」。
    #
    # 为什么删掉降级（2026-10-23）：覆盖写是 `open(db_path, "wb")`，会先把目标文件
    # 截成 0 字节再灌数据。链路接通后（C-15），运行中的进程每轮请求都会
    # `sqlite3.connect` 读这个文件；如果正好落在这几毫秒里，它会读到半截库，
    # 抛 `no such table: entries` —— 表现为「她突然不说话」，而且不可撤回。
    # 而重建失败没有任何损失：src/*.json 已保存，重跑一次即可。
    # 所以这里宁肯失败，也不拿一次真实对话去换一次构建成功。
    last_exc = None
    for attempt in range(6):
        try:
            os.replace(tmp, db_path)
            last_exc = None
            break
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.2 * (attempt + 1))
    if last_exc is not None:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise PermissionError(
            f"替换库文件失败（已重试 6 次，共约 4 秒）：{db_path}。"
            "请关掉正在占用它的进程后重跑；src/*.json 已保存，重跑不会丢数据。"
        )

    # digest.md: short, prompt-injectable
    lines = [
        "# Miruku 知识库摘要",
        "",
        f"生成时间：{now}；条目：{total}；由 `knowledge/build_knowledge_db.py` 生成，勿手改。",
        "",
    ]
    for t in topics:
        lines.append(f"## {t['title']}")
        for e in t["entries"]:
            if e.get("sensitive"):
                continue
            lines.append(f"- {e['title']}：{e['summary'].strip()}")
        lines.append("")
    with open(digest_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    print(f"OK → {db_path}")
    print(f"topics={len(topics)} entries={total} digest={digest_path}")
    for t in topics:
        print(f"  - {t['topic']}: {len(t['entries'])} 条（{t['title']}）")
    print(f"db_size={os.path.getsize(db_path):,} bytes")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="构建 Miruku 知识库 SQLite")
    ap.add_argument("--src-dir", default=DEFAULT_SRC)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--digest", default=DEFAULT_DIGEST)
    args = ap.parse_args()
    try:
        build(args.src_dir, args.db, args.digest)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
