#!/usr/bin/env bash
set -e
# 部署面板数据脚本到 astrbot 卷 + 验证登录态
mkdir -p /opt/miruku/astrbot/data/laishi
cp -f /opt/miruku/server/ws_probe.py /opt/miruku/astrbot/data/laishi/ws_probe.py
cp -f /opt/miruku/server/panel-status.py /opt/miruku/astrbot/data/laishi/panel-status.py
sed -i 's/\r$//' /opt/miruku/astrbot/data/laishi/*.py

echo "== 登录态/链路 =="
docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01
docker logs astrbot --since 10m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E '适配器已连接' | tail -2
docker logs napcat --since 15m 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' | grep -iE '登录成功|已登录|quick|快速' | tail -3 | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g' || true

echo "== panel-status.py 试跑（截 300 字符）=="
python3 /opt/miruku/astrbot/data/laishi/panel-status.py | head -c 300; echo
