#!/usr/bin/env bash
set -e
sed -i 's/\r$//' /opt/miruku/server/panel-status.py /opt/miruku/server/heartbeat.sh
cp -f /opt/miruku/server/panel-status.py /opt/miruku/astrbot/data/laishi/panel-status.py
bash -n /opt/miruku/server/heartbeat.sh && echo "[ok] heartbeat 语法通过"
# 立刻跑一次，让新掩码逻辑生效
bash /opt/miruku/server/heartbeat.sh || true
echo "[check] panel-status 输出里是否还有 10 位明文号码："
python3 /opt/miruku/astrbot/data/laishi/panel-status.py > /tmp/ps.json
python3 - <<'PY'
import json, re
s = open("/tmp/ps.json", encoding="utf-8").read()
leak = re.findall(r"(?<!\d)\d{10}(?!\d)", s)
print("  明文号码:", leak or "NONE")
d = json.loads(s)
print("  heartbeat 最后一行:", (d["heartbeat"][-1] if d["heartbeat"] else "-")[:120])
PY
