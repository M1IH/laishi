# 聊天内容数据库（`data/chat_content.sqlite3`）

把 QQChatExporter 导出的私聊记录整理成一个**本地可查询**的 SQLite 库，用来按人、时间、类型检索，也方便后续导出 JSONL。

## 生成 / 重建

```bash
cd "C:/Users/OTTO/Desktop/来世"
python build_chat_db.py                                  # 重建 data/chat_content.sqlite3
python build_chat_db.py --jsonl data/chat_content.jsonl  # 顺带导出纯文本 JSONL
```

- 默认读取 `个性化语言/聊天记录/friend_*.json`（两份导出全量重建）。
- 脚本只用 Python 标准库（3.9+），不需要装包。
- 重建会删掉旧库再重来；新增导出文件后重跑即可。

## 当前规模（2026-10-20 17:52 构建）

| 会话 | session_key | 条数 | 纯文本 | 时间范围（+08:00） |
| --- | --- | --- | --- | --- |
| 来世 | `10000002` | 28,451 | 26,454 | 2025-10-04 21:59 → 2026-10-19 12:57 |
| miruku 测试 | `10000004` | 215 | 207 | 2026-10-19 12:45 → 2026-10-20 17:29 |

合计 28,666 条，`v_text_messages` 26,661 条，库文件约 31.9 MB。

> 不含 2026-10-20 12:21–12:24 来世真实三条——那三条不在两份导出里，在 AstrBot 的 `data_v4.db`；需要时可从那边单独补。

## 表结构

- `sessions`：一个对端一行。`session_key` 是对端 QQ 号，`title` 是导出里的名字，另有 `self_uin/self_name`、`peer_uin/peer_name`、`source_file`、`first_ms/last_ms/message_count`。
- `messages`：一条 QQ 消息一行，主键 `(session_key, id)`。
  - `direction`：`self`（OTTO 发的）/ `peer`（对方发的）/ `system`（系统消息）。
  - `type`：导出原始类型（`text`、`image`、`json`、`reply`、`forward`、`video`、`audio`、`file` 等）。
  - `ts_ms` 毫秒时间戳；`ts_utc` 原始 UTC；`ts_local` 已转成 +08:00，直接用这个。
  - `text` 是 `content.text`；`elements_json`、`resources_json` 保留原始结构。
- `message_parts`：把 `content.elements` 拆开，一段一行。`part_type` 有 `text`、`image`、`reply`、`json`、`forward`、`video`、`audio`、`file`、`face`、`market_face`、`av_record`、`markdown`。查“发过哪些图”用这张表。
- `messages_fts`：trigram 全文索引，支持 **3 字及以上**的子串搜索；中文 2 字词（如“牛奶”）请直接用 `LIKE`，这个规模下毫秒级。
- `meta`：构建时间、源文件大小与 sha256 前 16 位。
- 视图：`v_text_messages`（纯文本、非系统、非撤回、非空）、`v_daily_counts`（按天/方向计数）、`v_sender_counts`（按发送者计数）。

## 常用查询

Windows 终端建议先 `chcp 65001`，或者直接用 Python 的 `sqlite3` 查，避免中文乱码。

```bash
DB=data/chat_content.sqlite3
```

```bash
# 最近 20 条（来世）
sqlite3 "$DB" "SELECT ts_local, sender_name, text FROM v_text_messages WHERE session_key='10000002' ORDER BY ts_ms DESC LIMIT 20;"

# 关键词，任意长度（2 字词用这个）
sqlite3 "$DB" "SELECT ts_local, sender_name, text FROM v_text_messages WHERE text LIKE '%牛奶%' ORDER BY ts_ms LIMIT 20;"

# 3 字以上走 FTS（中文同样适用）
sqlite3 "$DB" "SELECT m.ts_local, f.sender_name, substr(f.text,1,60) FROM messages_fts f JOIN messages m ON m.session_key=f.session_key AND m.id=f.msg_id WHERE messages_fts MATCH '三角洲' ORDER BY m.ts_ms LIMIT 20;"

# 某一天
sqlite3 "$DB" "SELECT ts_local, sender_name, text FROM v_text_messages WHERE session_key='10000002' AND ts_local LIKE '2026-10-18%' ORDER BY ts_ms;"

# 每天条数（按方向）
sqlite3 "$DB" "SELECT day, direction, n FROM v_daily_counts WHERE session_key='10000002' ORDER BY day DESC LIMIT 14;"

# 只看来世发的文本
sqlite3 "$DB" "SELECT ts_local, text FROM v_text_messages WHERE sender_uin='10000002' ORDER BY ts_ms DESC LIMIT 50;"

# 找图片消息
sqlite3 "$DB" "SELECT m.ts_local, m.sender_name FROM message_parts p JOIN messages m ON m.session_key=p.session_key AND m.id=p.msg_id WHERE p.part_type='image' AND p.session_key='10000002' ORDER BY m.ts_ms DESC LIMIT 20;"

# 文本长度分布（SQLite 没有中位数，取出来自己算）
sqlite3 "$DB" "SELECT length(text) FROM v_text_messages WHERE sender_uin='10000002';"
```

Python 里：

```python
import sqlite3
c = sqlite3.connect("data/chat_content.sqlite3")
for ts, name, text in c.execute(
        "SELECT ts_local, sender_name, text FROM v_text_messages "
        "WHERE text LIKE ? ORDER BY ts_ms LIMIT 20", ("%牛奶%",)):
    print(ts, name, text.replace("\n", " "))
```

## 注意

- `data/` 是私有目录，库里有真实 QQ 号和聊天原文，**不要提交、不要外发**。
- `v_text_messages` 排除了系统消息与撤回消息；要看全部用 `messages`。
- 消息里的 `[图片:xxx.jpg]` 这类占位文本保留在 `text` 里，图片文件名可在 `message_parts.data_json` 里查。
