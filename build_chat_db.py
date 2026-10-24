#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 QQChatExporter 导出的私聊 JSON 建成一个本地可查询的 SQLite 库。

用法（在项目根目录）：
    python build_chat_db.py
    python build_chat_db.py --db data/chat_content.sqlite3
    python build_chat_db.py --jsonl data/chat_content.jsonl   # 顺带导出纯文本 JSONL

默认读取 个性化语言/聊天记录/friend_*.json，全量重建 data/chat_content.sqlite3。
库里有 sessions / messages / message_parts / messages_fts 四张表，外加
v_text_messages、v_daily_counts、v_sender_counts 三个视图。示例查询见 docs/chat-db.md。
"""

import argparse
import glob
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GLOB = os.path.join(ROOT, "个性化语言", "聊天记录", "friend_*.json")
DEFAULT_DB = os.path.join(ROOT, "data", "chat_content.sqlite3")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE sessions (
    session_key  TEXT PRIMARY KEY,   -- 对端 QQ 号，如 10000002
    title        TEXT,               -- 导出里的 chatInfo.name
    self_uin     TEXT,               -- 导出者（OTTO）QQ
    self_name    TEXT,
    peer_uin     TEXT,               -- 对端 QQ
    peer_name    TEXT,
    source_file  TEXT,
    exported_at  TEXT,
    first_ms     INTEGER,
    last_ms      INTEGER,
    message_count INTEGER
);

CREATE TABLE messages (
    session_key   TEXT NOT NULL,
    id            TEXT NOT NULL,     -- 导出里的消息 id
    seq           TEXT,
    ts_ms         INTEGER NOT NULL,
    ts_utc        TEXT NOT NULL,     -- 2026-10-19T04:45:14.000Z
    ts_local      TEXT NOT NULL,     -- 2026-10-19T12:45:14+08:00
    sender_uid    TEXT,
    sender_uin    TEXT,
    sender_name   TEXT,
    direction     TEXT NOT NULL,     -- self / peer / system
    type          TEXT NOT NULL,     -- text / image / json / reply ...
    text          TEXT,
    html          TEXT,
    recalled      INTEGER NOT NULL DEFAULT 0,
    system        INTEGER NOT NULL DEFAULT 0,
    elements_json TEXT,
    resources_json TEXT,
    PRIMARY KEY (session_key, id)
);
CREATE INDEX idx_messages_ts        ON messages(session_key, ts_ms);
CREATE INDEX idx_messages_sender    ON messages(sender_uin);
CREATE INDEX idx_messages_type      ON messages(type);
CREATE INDEX idx_messages_direction ON messages(direction);

CREATE TABLE message_parts (
    session_key TEXT NOT NULL,
    msg_id      TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    part_type   TEXT NOT NULL,
    text        TEXT,
    data_json   TEXT,
    PRIMARY KEY (session_key, msg_id, idx)
);
CREATE INDEX idx_parts_type ON message_parts(part_type);

-- trigram：可做 >=3 字的子串匹配（中文 2 字词请直接用 LIKE，见 docs/chat-db.md）
CREATE VIRTUAL TABLE messages_fts USING fts5(
    session_key UNINDEXED,
    msg_id UNINDEXED,
    text,
    sender_name,
    tokenize='trigram'
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE VIEW v_text_messages AS
SELECT session_key, id, ts_ms, ts_utc, ts_local,
       sender_uin, sender_name, direction, text
FROM messages
WHERE type = 'text' AND recalled = 0 AND system = 0
  AND length(trim(coalesce(text, ''))) > 0;

CREATE VIEW v_daily_counts AS
SELECT session_key, substr(ts_local, 1, 10) AS day,
       direction, count(*) AS n
FROM messages
GROUP BY 1, 2, 3;

CREATE VIEW v_sender_counts AS
SELECT session_key, sender_uin, sender_name, direction, count(*) AS n
FROM messages
GROUP BY 1, 2, 3, 4
ORDER BY n DESC;
"""


def iso_utc(ms):
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def iso_local(ms):
    return datetime.fromtimestamp(ms / 1000.0, CST).isoformat(timespec="seconds")


def parse_ms(m):
    """QQChatExporter 的 message.timestamp 是毫秒；缺失时退回 time 字段。"""
    ts = m.get("timestamp")
    if ts:
        return int(ts)
    t = m.get("time")
    if t:
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    raise ValueError("message %r 没有 timestamp/time" % (m.get("id"),))


def sender_name(s):
    if not s:
        return None
    return s.get("name") or s.get("nickname") or s.get("remark") or s.get("uin")


def dump(v):
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def load_export(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def insert_export(conn, path):
    data = load_export(path)
    ci = data.get("chatInfo") or {}
    stat = data.get("statistics") or {}
    msgs = data.get("messages") or []

    self_uin = str(ci.get("selfUin") or "")
    peer_uin = str(ci.get("peerUin") or "")
    session_key = peer_uin or ci.get("name") or os.path.basename(path)
    title = ci.get("name") or peer_uin
    self_name = ci.get("selfName") or ""
    peer_name = ci.get("peerName") or title

    first_ms = min((parse_ms(m) for m in msgs), default=None)
    last_ms = max((parse_ms(m) for m in msgs), default=None)

    conn.execute(
        "INSERT OR REPLACE INTO sessions(session_key, title, self_uin, self_name, "
        "peer_uin, peer_name, source_file, exported_at, first_ms, last_ms, message_count) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (session_key, title, self_uin, self_name, peer_uin, peer_name,
         os.path.basename(path), datetime.now(CST).isoformat(timespec="seconds"),
         first_ms, last_ms, len(msgs)),
    )

    msg_rows = []
    part_rows = []
    fts_rows = []
    for m in msgs:
        content = m.get("content") or {}
        sender = m.get("sender") or {}
        ms = parse_ms(m)
        suin = str(sender.get("uin") or "")
        if m.get("system"):
            direction = "system"
        elif suin and suin == self_uin:
            direction = "self"
        else:
            direction = "peer"

        text = content.get("text")
        msg_id = str(m.get("id"))
        msg_rows.append((
            session_key, msg_id, str(m.get("seq") or ""), ms,
            iso_utc(ms), iso_local(ms),
            sender.get("uid"), suin, sender_name(sender),
            direction, str(m.get("type") or "unknown"),
            text, content.get("html"),
            1 if m.get("recalled") else 0,
            1 if m.get("system") else 0,
            dump(content.get("elements")),
            dump(content.get("resources")),
        ))

        for i, el in enumerate(content.get("elements") or []):
            el = el or {}
            data_el = el.get("data") if isinstance(el, dict) else None
            el_text = data_el.get("text") if isinstance(data_el, dict) else None
            part_rows.append((
                session_key, msg_id, i, str(el.get("type") or "unknown"),
                el_text, dump(data_el),
            ))

        if direction != "system" and not m.get("recalled") and text and text.strip():
            fts_rows.append((session_key, msg_id, text, sender_name(sender)))

    conn.executemany(
        "INSERT OR IGNORE INTO messages(session_key, id, seq, ts_ms, ts_utc, ts_local, "
        "sender_uid, sender_uin, sender_name, direction, type, text, html, recalled, "
        "system, elements_json, resources_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        msg_rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO message_parts(session_key, msg_id, idx, part_type, text, data_json) "
        "VALUES (?,?,?,?,?,?)",
        part_rows,
    )
    conn.executemany(
        "INSERT INTO messages_fts(session_key, msg_id, text, sender_name) VALUES (?,?,?,?)",
        fts_rows,
    )

    total = len(msgs)
    expect = stat.get("totalMessages")
    if expect is not None and expect != total:
        print("  ! statistics.totalMessages=%s 与 messages 条数 %s 不一致（按 messages 为准）"
              % (expect, total))
    print("  %-12s %-14s %6d 条  %s → %s"
          % (session_key, title, total, iso_local(first_ms), iso_local(last_ms)))


def main():
    ap = argparse.ArgumentParser(description="把 QQ 私聊导出 JSON 建成可查询的 SQLite 库")
    ap.add_argument("--src", default=DEFAULT_GLOB, help="导出文件路径或 glob，默认 %(default)s")
    ap.add_argument("--db", default=DEFAULT_DB, help="输出库路径，默认 %(default)s")
    ap.add_argument("--jsonl", default=None, help="可选：额外导出纯文本消息为 JSONL")
    args = ap.parse_args()

    if any(ch in args.src for ch in "*?["):
        files = sorted(glob.glob(args.src))
    else:
        files = [args.src]
    if not files:
        print("没有找到导出文件：%s" % args.src, file=sys.stderr)
        return 2

    db_path = os.path.abspath(args.db)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    print("读取导出：")
    for path in files:
        print("  %s (%s 字节)" % (os.path.basename(path), format(os.path.getsize(path), ",")))
    for path in files:
        insert_export(conn, path)

    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 ("built_at", datetime.now(CST).isoformat(timespec="seconds")))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                 ("builder", "build_chat_db.py"))
    conn.executemany(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        [("source:%s" % os.path.basename(p),
          "%s bytes sha256=%s" % (format(os.path.getsize(p), ","),
                                  hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]))
         for p in files],
    )
    conn.commit()

    if args.jsonl:
        with open(args.jsonl, "w", encoding="utf-8") as f:
            cur = conn.execute(
                "SELECT session_key, id, ts_local, direction, sender_name, text "
                "FROM v_text_messages ORDER BY session_key, ts_ms")
            n = 0
            for row in cur:
                f.write(json.dumps({
                    "session_key": row[0], "msg_id": row[1], "ts_local": row[2],
                    "direction": row[3], "sender": row[4], "text": row[5],
                }, ensure_ascii=False) + "\n")
                n += 1
        print("JSONL 已导出：%s（%d 条）" % (args.jsonl, n))

    print("\n统计：")
    for key, title, n, first, last in conn.execute(
            "SELECT session_key, title, message_count, first_ms, last_ms FROM sessions "
            "ORDER BY message_count DESC"):
        text_n = conn.execute(
            "SELECT count(*) FROM messages WHERE session_key=? AND type='text' "
            "AND system=0 AND recalled=0", (key,)).fetchone()[0]
        print("  %s（%s）：%d 条，其中纯文本 %d 条，%s → %s"
              % (title, key, n, text_n, iso_local(first), iso_local(last)))
        for name, direction, cnt in conn.execute(
                "SELECT sender_name, direction, count(*) FROM messages WHERE session_key=? "
                "GROUP BY sender_name, direction ORDER BY count(*) DESC LIMIT 5", (key,)):
            print("      %-16s %-6s %d" % (name or "-", direction, cnt))

    print("\n消息类型：")
    for t, cnt in conn.execute(
            "SELECT type, count(*) FROM messages GROUP BY type ORDER BY count(*) DESC"):
        print("  %-10s %d" % (t, cnt))

    print("\n媒体/结构片段（message_parts）：")
    for t, cnt in conn.execute(
            "SELECT part_type, count(*) FROM message_parts GROUP BY part_type "
            "ORDER BY count(*) DESC"):
        print("  %-10s %d" % (t, cnt))

    total = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
    text_total = conn.execute("SELECT count(*) FROM v_text_messages").fetchone()[0]
    size = os.path.getsize(db_path)
    print("\n库：%s" % db_path)
    print("  messages=%d，v_text_messages=%d，文件 %.1f MB" % (total, text_total, size / 1048576.0))
    print("\n示例：sqlite3 \"%s\" \"SELECT ts_local, sender_name, text FROM v_text_messages "
          "WHERE text LIKE '%%牛奶%%' ORDER BY ts_ms LIMIT 20;\"" % db_path)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
