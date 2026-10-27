#!/usr/bin/env bash
# 实验：验证 compose 的 mac_address 能否真正钉住容器 MAC
# 只重建 napcat 容器本身（不碰 astrbot、不碰数据卷），看看新 MAC 是否等于配置值
set -uo pipefail
cd /opt/miruku

WANT=$(grep -oP 'mac_address:\s*"\K[^"]+' compose.yaml | head -1)
echo "== 配置里写的期望 MAC: $WANT"
echo -n "== 重建前实际 MAC: "
docker inspect napcat --format '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}'

echo ""
echo "== 记录当前登录态文件指纹（用于对比是否过期）=="
ls -la napcat/qq/global/nt_db/login.db 2>/dev/null | awk '{print "  login.db:", $5, "bytes,", $6, $7, $8}'

echo ""
echo "== 执行 force-recreate（保留所有数据卷）=="
cp -f server/compose.yaml compose.yaml
docker compose up -d --force-recreate --no-deps napcat 2>&1 | tail -4

sleep 8
echo ""
echo -n "== 重建后实际 MAC: "
docker inspect napcat --format '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}'

ACTUAL=$(docker inspect napcat --format '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}' | tr 'A-Z' 'a-z')
echo ""
if [ "$ACTUAL" = "$(echo $WANT | tr 'A-Z' 'a-z')" ]; then
  echo "  ★ MAC 钉住成功：$ACTUAL"
else
  echo "  ✗ MAC 未生效：期望 $WANT，实际 $ACTUAL"
fi
