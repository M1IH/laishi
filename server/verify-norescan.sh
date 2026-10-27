#!/usr/bin/env bash
# 严格验证「真正免扫」：模拟服务器重启（restart docker + 容器），看能否自动恢复
# 这是最终验收——如果 restart 后还要扫码，那"免扫"就是假的。
set -uo pipefail
cd /opt/miruku

echo "== 重启前基线 =="
echo -n "  MAC: "; docker inspect napcat --format '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}'
echo -n "  ws6199: "; docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01 2>/dev/null

echo ""
echo "== 模拟整机重启：restart docker 服务（等同开机）=="
systemctl restart docker
sleep 5

# docker 服务重启后容器需要被拉起（restart:always / unless-stopped 会处理）
for i in $(seq 1 30); do
  sleep 5
  up=$(docker ps --format '{{.Names}}' | grep -c -E 'astrbot|napcat' || true)
  ws=$(docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01 2>/dev/null || echo 0)
  echo "  t+$((i*5))s  容器数=$up  ws6199=$ws"
  [ "$up" -ge 2 ] && [ "$ws" = "1" ] && break
done

echo ""
echo "== 结果 =="
echo -n "  MAC: "; docker inspect napcat --format '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}'
echo -n "  ws6199: "; docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01 2>/dev/null
echo -n "  二维码次数: "; docker logs napcat --since 3m 2>&1 | grep -c '二维码' || true
docker logs napcat --since 3m 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE '快速登录|登录态失效' | tail -3 | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'
