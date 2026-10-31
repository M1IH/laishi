#!/bin/bash
set -u
URL_FILE=/opt/miruku/logs/qr-tunnel-url
LOG=/var/log/miruku-qr-tunnel.log
rm -f "$URL_FILE"
# 记录当前日志行数，之后只看新行
BASE=$(wc -l < "$LOG" 2>/dev/null || echo 0)
/opt/miruku/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8663 2>&1 &
CF_PID=$!
for i in $(seq 1 60); do
  sleep 2
  U=$(tail -n +$((BASE+1)) "$LOG" 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)
  if [ -n "$U" ]; then
    printf '%s' "$U" > "$URL_FILE"
    chmod 644 "$URL_FILE"
    echo "[qr-tunnel] url=$U"
    break
  fi
done
wait $CF_PID
