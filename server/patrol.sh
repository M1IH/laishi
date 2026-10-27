#!/usr/bin/env bash
# 隔夜状态巡检（只读）
echo "== 6199 链路（astrbot 容器内）=="
echo -n "  established: "; docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01
echo -n "  listen:      "; docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 0A

echo "== 容器状态 =="
docker ps -a --format '  {{.Names}}: {{.Status}}'

echo "== 近 13 小时：掉线/踢下线痕迹 =="
docker logs napcat --since 13h 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE '被踢|下线|kick|offline|失效|掉线|重新登录|二维码' | tail -6 | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g' || echo "  (无)"
docker logs astrbot --since 13h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '适配器已连接|断开|disconnect' | tail -6 || echo "  (无)"

echo "== 心跳统计（近 13h）=="
if [ -f /var/log/miruku-heartbeat.log ]; then
  awk '$0 ~ /status=OK/{ok++} $0 ~ /ALERT/{al++} END{print "  OK行:",ok+0," ALERT行:",al+0}' /var/log/miruku-heartbeat.log
  echo "  最近 3 行:"; tail -3 /var/log/miruku-heartbeat.log | sed 's/^/    /'
fi

echo "== 主动任务 =="
curl -s --max-time 6 http://127.0.0.1:4100/api/jobs | head -c 300; echo
