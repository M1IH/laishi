#!/bin/bash
echo "=== outbound armed + WS + QQ 登录态 ==="
docker logs astrbot --since 5m 2>&1 | grep -E 'miruku_outbound|WS-Client|aiocqhttp' | tail -6
echo "--- QQ login state ---"
docker exec snowluma sh -c "grep -hE 'login detected|awaiting login' /app/data/logs/*.log 2>/dev/null | tail -1"
