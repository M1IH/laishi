import sqlite3

db = sqlite3.connect('/AstrBot/data/data_v4.db')
c = db.execute(
    "SELECT platform_id, COUNT(*), MIN(created_at), MAX(created_at) "
    "FROM platform_message_history GROUP BY platform_id").fetchall()
for r in c:
    print(r)

rows = db.execute(
    "SELECT sender_id, sender_name, substr(content,1,80), created_at "
    "FROM platform_message_history ORDER BY created_at DESC LIMIT 12").fetchall()
print('---')
for r in rows:
    print(r[3], r[0], (r[1] or '')[:8], repr(r[2])[:90])
