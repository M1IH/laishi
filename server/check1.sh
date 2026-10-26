#!/usr/bin/env bash
echo "== unit files =="
ls -la /etc/systemd/system/ | grep -i heartbeat || echo "(none)"
echo "== content check (cat -A first line) =="
for f in /etc/systemd/system/miruku-heartbeat.*; do
  [ -f "$f" ] && { echo "--- $f"; head -3 "$f" | cat -A | head -3; }
done
echo "== try daemon-reload + enable again =="
systemctl daemon-reload
systemctl enable --now miruku-heartbeat.timer 2>&1 | tail -2
systemctl list-timers miruku-heartbeat* --no-pager 2>&1 | tail -3
echo "== containers =="
docker ps --format '  {{.Names}}: {{.Status}}'
echo "== astrbot logs (last 15) =="
docker logs astrbot 2>&1 | tail -15
echo "== napcat logs (last 8) =="
docker logs napcat 2>&1 | tail -8
