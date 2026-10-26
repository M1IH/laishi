#!/usr/bin/env bash
# Miruku 服务器引导（Ubuntu 22.04）——只装运行栈所需，不开任何公网端口
set -euo pipefail

log(){ echo "[bootstrap] $*"; }

# 1) 基础工具
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg rsync git python3 sqlite3 \
  xauth dbus unzip tar

# 2) Docker（阿里云镜像源，国内直连 download.docker.com 常超时）
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(. /etc/os-release; echo $VERSION_CODENAME) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

# 3) Docker Hub 加速（阿里云个人镜像加速地址由环境变量传入，没有就跳过）
if [ -n "${ACCEL_MIRROR:-}" ]; then
  mkdir -p /etc/docker
  cat > /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": ["${ACCEL_MIRROR}"],
  "default-ulimits": { "nofile": { "Name": "nofile", "Hard": 65536, "Soft": 65536 } }
}
EOF
  systemctl restart docker
  log "registry mirror = ${ACCEL_MIRROR}"
fi

# 4) 目录骨架
APP=/opt/miruku
mkdir -p "$APP"/{napcat/qq,napcat/config,napcat/plugins,astrbot/data,projects,logs,bin,systemd}

# 5) 2G 机器加 swap（内存临界时的兜底， Otto 已确认机器 2G）
if [ "$(free -m | awk '/^Swap:/{print $2}')" -lt 512 ] && [ ! -f /swapfile ]; then
  log "创建 2G swap"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

log "内存实况："; free -m | sed -n '1,3p'
log "磁盘实况："; df -h / | sed -n '1,2p'
log "bootstrap 完成"
