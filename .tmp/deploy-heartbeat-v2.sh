#!/bin/bash
# heartbeat.sh v2（SnowLuma 版）部署：备份→替换→语法检查→试跑一次→启动 timer→验证
set -uo pipefail
TS=$(date +%Y%m%d-%H%M%S)

echo "=== 1. 备份旧脚本 ==="
cp /opt/miruku/server/heartbeat.sh "/opt/miruku/backups/heartbeat.sh.bak.$TS" && echo "backup -> /opt/miruku/backups/heartbeat.sh.bak.$TS"

echo "=== 2. 落位 ==="
cp /root/heartbeat.sh /opt/miruku/server/heartbeat.sh
chmod +x /opt/miruku/server/heartbeat.sh
bash -n /opt/miruku/server/heartbeat.sh && echo "SYNTAX_OK"

echo "=== 3. timer 现状 ==="
systemctl is-active miruku-heartbeat.timer || true
systemctl is-enabled miruku-heartbeat.timer || true

echo "=== 4. 手动试跑一次（观察判定）==="
bash /opt/miruku/server/heartbeat.sh
tail -2 /var/log/miruku-heartbeat.log

echo "=== 5. 启动 timer ==="
systemctl start miruku-heartbeat.timer
systemctl is-active miruku-heartbeat.timer
systemctl list-timers miruku-heartbeat.timer --no-pager | head -4
