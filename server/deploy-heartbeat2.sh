#!/usr/bin/env bash
# 部署并验证新心跳（含 QQ 在线判据）
set -e
sed -i 's/\r$//' /opt/miruku/server/heartbeat.sh
bash -n /opt/miruku/server/heartbeat.sh && echo "[ok] 语法通过"

# 登录成功后清掉「需扫码」标记（如果之前有）
if [ "$(docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01 2>/dev/null)" = "1" ]; then
  rm -f /opt/miruku/logs/needs-rescan
fi

echo ""
echo "== 跑一次新心跳 =="
bash /opt/miruku/server/heartbeat.sh
tail -2 /var/log/miruku-heartbeat.log

echo ""
echo "== 当前真实指标 =="
echo -n "  QQ→腾讯 ESTABLISHED: "
docker exec napcat sh -c 'n=0; for f in /proc/net/tcp /proc/net/tcp6; do [ -f "$f" ] && n=$((n + $(awk "NR>1 && \$4==\"01\"" "$f" | wc -l))); done; echo $n'
echo -n "  napcat.mjs 进程: "
docker exec napcat sh -c 'ps aux 2>/dev/null | grep -c "[n]apcat.mjs"'
