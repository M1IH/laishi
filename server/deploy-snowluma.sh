#!/bin/bash
# SnowLuma 切换部署脚本（2026-10-29 DeepSeek）
# 前提：镜像已拉取。作用：停 napcat+heartbeat → 起 snowluma（同 docker 网络）→ 输出扫码指引
set -uo pipefail

NET=miruku_miruku
IMAGE=motricseven7/snowluma:latest
# 仅用于最后打印「本机怎么连隧道」的提示；地址从 MIRUKU_SSH 或项目根 .env 读，
# 公开仓库只带 RFC 5737 占位地址 203.0.113.10。
Target=${MIRUKU_SSH:-root@203.0.113.10}

echo "[1/5] 停 heartbeat timer（防 self-heal 拉起 napcat 互踢）"
systemctl stop miruku-heartbeat.timer
echo "      timer=$(systemctl is-active miruku-heartbeat.timer)"

echo "[2/5] 停 napcat（QQ 登录态保留在容器卷里，随时可回退）"
docker stop napcat
echo "      napcat status: $(docker inspect napcat --format '{{.State.Status}}')"

echo "[3/5] 创建 docker volume（幂等）"
docker volume create qq-gateway-data >/dev/null
docker volume create qq-client-config >/dev/null
docker volume create qq-client-data >/dev/null

echo "[4/5] 启动 snowluma"
docker rm -f snowluma 2>/dev/null
docker run -d \
  --name snowluma \
  --restart unless-stopped \
  --shm-size=1g \
  --ulimit nofile=65536:1048576 \
  --cap-add=SYS_PTRACE \
  --security-opt seccomp=unconfined \
  --network $NET \
  --network-alias snowluma \
  -e SNOWLUMA_WEBUI_HOST=0.0.0.0 \
  -e SNOWLUMA_WEBUI_PORT=5099 \
  -e SNOWLUMA_QQ_FLAGS="--disable-gpu --disable-software-rasterizer --disable-gpu-compositing" \
  -p 127.0.0.1:6081:6081 \
  -p 127.0.0.1:5099:5099 \
  -v qq-gateway-data:/app/data \
  -v qq-client-config:/app/.config \
  -v qq-client-data:/app/.local/share \
  $IMAGE

sleep 8
echo "[5/5] 启动状态"
docker ps --filter name=snowluma --format '{{.Names}} {{.Status}}'
echo
echo "=== WebUI 临时密码（首次启动一次性，只在全新数据卷打印）==="
docker logs snowluma 2>&1 | grep -E "临时密码|initial credentials" | tail -n 1
echo
echo "=== 容器内进程 ==="
docker exec snowluma supervisorctl status 2>/dev/null || echo "(supervisorctl 暂不可用，等 10s 再看)"
echo
echo "=== 内存 ==="
free -h | head -2
echo
echo ">>> 下一步：本机开 SSH 隧道 ssh -L 16081:127.0.0.1:6081 \$Target"
echo ">>> 浏览器开 http://localhost:16081/ 用日志里的远程桌面密码登录 noVNC，桌面里 QQ 应已自动弹出二维码，手机扫码。"
echo ">>> 回退：docker stop snowluma && docker start napcat && systemctl start miruku-heartbeat.timer"
