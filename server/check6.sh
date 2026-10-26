#!/usr/bin/env bash
echo "== timers =="
systemctl list-timers miruku-heartbeat* --no-pager | tail -2
echo "== heartbeat latest =="
tail -2 /var/log/miruku-heartbeat.log
echo "== units =="
for u in miruku-xvfb miruku-desktop miruku-vnc miruku-novnc; do printf '%s=%s ' "$u" "$(systemctl is-active $u)"; done; echo
echo "== containers =="
docker ps --format '{{.Names}}: {{.Status}}'
echo "== dashboard auth state =="
curl -s -o /dev/null -w '6185/api/v1/system-config -> %{http_code}\n' --max-time 5 http://127.0.0.1:6185/api/v1/system-config
echo "== webui login probe =="
curl -s -o /dev/null -w '6099/webui/ -> %{http_code}\n' --max-time 5 http://127.0.0.1:6099/webui/
echo "== qrcode freshness =="
docker exec napcat ls -la /app/napcat/cache/qrcode.png 2>&1 | tail -1
