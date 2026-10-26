#!/usr/bin/env bash
# 首次起栈：.env(NapCat WebUI token) -> compose up -> 心跳 timer -> 状态快照
set -euo pipefail
cd /opt/miruku

# 0) compose 必须放在项目根（卷里的相对路径 ./napcat ./astrbot 按 compose 文件位置解析）
cp -f server/compose.yaml compose.yaml
sed -i 's/\r$//' compose.yaml
docker compose config -q || { echo "[deploy] compose.yaml 校验失败"; docker compose config 2>&1 | tail -5; exit 2; }

# 0.5) NapCat 镜像默认以 UID/GID 1000 运行，挂载目录要可写
chown -R 1000:1000 /opt/miruku/napcat 2>/dev/null || true

# 1) NapCat WebUI token（幂等：已有就不再生成）
if [ ! -f .env ]; then
  TOKEN=$(openssl rand -hex 12)
  printf 'NAPCAT_WEBUI_TOKEN=%s\n' "$TOKEN" > .env
  chmod 600 .env
  echo "[deploy] WEBUI_TOKEN 已生成写入 .env"
else
  echo "[deploy] .env 已存在，沿用其中的 WEBUI_TOKEN"
fi

# 2) 镜像齐了才起
docker image inspect soulter/astrbot:latest >/dev/null 2>&1 || {
  echo "[deploy] astrbot 镜像还没拉完，看 logs/pull-astrbot.log；不起栈"; exit 3; }
docker image inspect mlikiowa/napcat-docker:latest >/dev/null 2>&1 || {
  echo "[deploy] napcat 镜像缺失"; exit 3; }

docker compose up -d
sleep 8
docker ps --format '  {{.Names}}: {{.Status}}'

# 3) 心跳 systemd timer（5 分钟一次）
cat > /etc/systemd/system/miruku-heartbeat.service <<'EOF'
[Unit]
Description=Miruku heartbeat + self-heal probe

[Service]
Type=oneshot
ExecStart=/bin/bash /opt/miruku/server/heartbeat.sh
EOF
cat > /etc/systemd/system/miruku-heartbeat.timer <<'EOF'
[Unit]
Description=Miruku heartbeat every 5 minutes
After=network-online.target docker.service
Requires=docker.service

[Timer]
OnBootSec=90
OnUnitActiveSec=300
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now miruku-heartbeat.timer

# 4) 立刻跑一次心跳（此时 napcat 还没登录，NO_WS_LINK 属预期，不判故障——
#    自愈动作会因 napcat 容器活着而只累计 streak，不会乱重启）
bash /opt/miruku/server/heartbeat.sh || true
tail -3 /var/log/miruku-heartbeat.log
