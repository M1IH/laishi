#!/bin/bash
# 用 cloudflared 快速隧道把 qrpage(8663) 暴露到公网，systemd 托管，
# 域名写入 /opt/miruku/logs/qr-tunnel-url 供面板读取。
set -u
mkdir -p /opt/miruku/logs /opt/miruku/server

# 1) 停掉手工起的进程
pkill -f 'cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8663' 2>/dev/null || true
sleep 1

# 2) systemd unit：ExecStart 起隧道，另一个进程抓 URL 写文件
cat > /etc/systemd/system/miruku-qr-tunnel.service <<'UNIT'
[Unit]
Description=Miruku QR page public tunnel (cloudflared quick tunnel)
After=network-online.target miruku-qrpage.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/miruku/server/qr-tunnel-run.sh
Restart=always
RestartSec=10
StandardOutput=append:/var/log/miruku-qr-tunnel.log
StandardError=append:/var/log/miruku-qr-tunnel.log

[Install]
WantedBy=multi-user.target
UNIT

# 3) 启动脚本：起隧道 + 从日志里抓 https://xxx.trycloudflare.com 写进 url 文件
cat > /opt/miruku/server/qr-tunnel-run.sh <<'RUN'
#!/bin/bash
set -u
URL_FILE=/opt/miruku/logs/qr-tunnel-url
rm -f "$URL_FILE"
/opt/miruku/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8663 2>&1 &
CF_PID=$!
for i in $(seq 1 60); do
  sleep 2
  U=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /var/log/miruku-qr-tunnel.log 2>/dev/null | tail -1)
  if [ -n "$U" ]; then
    printf '%s' "$U" > "$URL_FILE"
    chmod 644 "$URL_FILE"
    echo "[qr-tunnel] url=$U"
    break
  fi
done
wait $CF_PID
RUN

chmod +x /opt/miruku/server/qr-tunnel-run.sh
systemctl daemon-reload
systemctl enable miruku-qr-tunnel.service >/dev/null 2>&1
systemctl restart miruku-qr-tunnel.service
sleep 30
echo "=== active ==="
systemctl is-active miruku-qr-tunnel.service
echo "=== url ==="
cat /opt/miruku/logs/qr-tunnel-url 2>/dev/null; echo
