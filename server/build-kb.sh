#!/usr/bin/env bash
set -e
K=/opt/miruku/astrbot/data/knowledge
cd "$K"
python3 - <<'PY'
import sys
sys.version_info >= (3, 10) or sys.exit("[FAIL] 需要 Python>=3.10（query.py 用了 X | None 注解）")
print("[pre] python", sys.version.split()[0])
PY
python3 build_knowledge_db.py --src-dir src --db miruku_knowledge.sqlite3
ls -la miruku_knowledge.sqlite3
python3 - <<'PY'
import sqlite3
con = sqlite3.connect("miruku_knowledge.sqlite3")
n = con.execute("select count(*) from entries").fetchone()[0]
print("[verify] entries =", n, "(期望 560)")
for t, c in con.execute("select topic, count(*) from entries group by topic order by 2 desc"):
    print("   ", t, c)
PY
echo "=== re-run migrate ==="
python3 /opt/miruku/server/migrate_config.py
