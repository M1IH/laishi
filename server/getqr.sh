#!/usr/bin/env bash
# 部署修正版心跳 + 取当前二维码（不重启任何容器）
set -e
cp -f /opt/miruku/server/heartbeat.sh /opt/miruku/server/heartbeat.sh.new 2>/dev/null || true
sed -i 's/\r$//' /opt/miruku/server/heartbeat.sh /opt/miruku/server/heartbeat.sh.new 2>/dev/null || true
bash -n /opt/miruku/server/heartbeat.sh && echo "[ok] heartbeat.sh 语法通过"
rm -f /opt/miruku/server/heartbeat.sh.new

docker exec napcat cp /app/napcat/cache/qrcode.png /tmp/qr.png 2>/dev/null || true
docker cp napcat:/app/napcat/cache/qrcode.png /tmp/qrcode.png 2>/dev/null && ls -la /tmp/qrcode.png

echo "== napcat 当前状态 =="
docker logs napcat --since 10m 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' | grep -iE '快速登录|二维码|已登录|login' | tail -4 | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'
echo "== 心跳最新 =="
tail -2 /var/log/miruku-heartbeat.log
