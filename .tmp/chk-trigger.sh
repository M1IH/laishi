#!/bin/bash
echo "=== 最近主动消息 + 闸门日志（今天）==="
docker logs astrbot --since 4h 2>&1 | grep -E '主动消息|miruku_outbound' | tail -12
echo "=== QQ 最近收发 ==="
docker exec snowluma sh -c "grep -hE 'login detected|awaiting login' /app/data/logs/*.log 2>/dev/null | tail -1"
docker logs astrbot --since 4h 2>&1 | grep -E 'Prepare to send' | tail -3
