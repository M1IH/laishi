#!/bin/bash
# SnowLuma 日志格式侦察：为心跳判据选信号
echo "=== /app/data/logs 文件列表 ==="
docker exec snowluma sh -c "ls -la /app/data/logs/ 2>/dev/null | tail -8"
echo "=== data/logs 最近 15 行 ==="
docker exec snowluma sh -c "tail -15 /app/data/logs/*.log 2>/dev/null"
echo "=== login 相关全部命中（带行格式）==="
docker exec snowluma sh -c "grep -hE 'login detected|awaiting login|WS-Client' /app/data/logs/*.log 2>/dev/null | tail -10"
echo "=== docker logs snowluma 最近 10 行 ==="
docker logs snowluma --tail 10 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
echo "=== docker logs 里 login 信号 ==="
docker logs snowluma 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E 'login detected|awaiting login|WS-Client' | tail -8
