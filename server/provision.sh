#!/usr/bin/env bash
# Miruku 服务器供给（幂等，可重跑）
set -uo pipefail
log(){ echo "[prov] $*"; }

# 1) swap：2G 内存机器必须兜底
if ! swapon --show | grep -q '/swapfile'; then
  log "创建 /swapfile 2G"
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=30 >/dev/null
else
  log "swap 已存在"
fi

# 2) 目录骨架
mkdir -p /opt/miruku/{napcat/qq,napcat/config,napcat/plugins,astrbot/data,projects,bin,logs,desktop}

# 3) 基础 + 桌面兜底（轻量 WM，不装 xfce4 全家桶，省内存）
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null 2>&1
need="curl rsync unzip sqlite3 ca-certificates xauth dbus dbus-x11 x11vnc xterm openbox xvfb websockify novnc fonts-noto-cjk libfontconfig1"
apt-get install -y $need

log "内存与 swap 实况："
free -m | sed -n '1,3p'
log "桌面组件："
for b in Xvfb x11vnc websockify openbox; do printf '  %s -> %s\n' "$b" "$(command -v $b || echo MISSING)"; done
log "provision 完成"
