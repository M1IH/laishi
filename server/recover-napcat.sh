#!/usr/bin/env bash
# 恢复 NapCat：重启容器（登录态已由固定 MAC 保护，应能快速登录免扫）
set -e
echo "== 重启前 =="
docker inspect napcat --format '  status={{.State.Status}} restarts={{.RestartCount}}'

docker restart napcat
echo "== 已重启，等待登录 =="

for i in $(seq 1 12); do
  sleep 10
  alive=$(docker exec napcat sh -c 'ps aux | grep -c "[n]apcat.mjs"' 2>/dev/null || echo 0)
  ws=$(docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01 2>/dev/null || echo 0)
  echo "  t+$((i*10))s  napcat.mjs=$alive  ws6199=$ws"
  [ "$ws" = "1" ] && [ "$alive" -ge 1 ] && { echo "  ★ 已恢复"; break; }
done

echo ""
echo "== 登录方式（是否免扫）=="
docker logs napcat --since 3m 2>&1 | grep -vE '^[0-9a-f]{40,}$' \
  | grep -iE '快速登录|二维码|登录成功|Login' | tail -5 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'
