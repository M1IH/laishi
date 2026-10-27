#!/usr/bin/env bash
# 查 napcat 容器当前 MAC（用于钉进 compose，避免 recreate 后换 MAC 导致登录态失效）
set -e
echo "== 当前 napcat 容器内 MAC =="
docker exec napcat sh -c 'for f in /sys/class/net/*/address; do cat $f; done' 2>/dev/null | grep -v '^00:00:00:00:00:00$' | head -3
echo "== 网络里的容器 MAC（docker inspect）=="
docker inspect napcat --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}: {{$v.MacAddress}}{{"\n"}}{{end}}'
echo "== 官方 astrbot 模板里的 mac_address 提示（对照）=="
grep -n mac_address /opt/miruku/server/compose.yaml || echo "  (我们的 compose 还没钉)"
