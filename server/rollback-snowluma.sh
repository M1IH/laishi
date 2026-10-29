#!/bin/bash
# SnowLuma 回退脚本：回到 NapCat（2026-10-29 DeepSeek）
set -uo pipefail
echo "[1/3] 停 snowluma"
docker stop snowluma 2>/dev/null
docker rm snowluma 2>/dev/null
echo "[2/3] 起 napcat"
docker start napcat
sleep 6
echo "[3/3] 恢复 heartbeat timer 与验证"
systemctl start miruku-heartbeat.timer
docker ps --filter name=napcat --format '{{.Names}} {{.Status}}'
ss -tnp 2>/dev/null | grep -c ':6199.*ESTAB' | xargs echo "6199 ESTABLISHED 连接数:"
echo ">>> 若 napcat 停了 17h 后登录态失效，需打开 NapCat WebUI(6099 隧道)重新扫码"
