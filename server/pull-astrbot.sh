#!/usr/bin/env bash
set -e
cd /opt/miruku
mkdir -p logs

# 后台拉 AstrBot 镜像，日志落盘，便于随时查进度
if ! docker image inspect soulter/astrbot:latest >/dev/null 2>&1; then
  nohup bash -lc 'docker pull soulter/astrbot:latest && echo PULL_OK' \
    > /opt/miruku/logs/pull-astrbot.log 2>&1 &
  echo "[pull] 已后台启动，日志 logs/pull-astrbot.log"
else
  echo "[pull] astrbot 镜像已在本地"
fi

# 前台确认 napcat 镜像可用（拉取早已完成）
docker image inspect mlikiowa/napcat-docker:latest --format 'napcat OK {{.Size}}'
