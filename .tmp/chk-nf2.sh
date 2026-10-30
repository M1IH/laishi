#!/bin/bash
set -uo pipefail
echo "=== 新好友 10000003 最近处理情况（重启后）==="
docker logs astrbot --since 20m 2>&1 | grep "10000003" | tail -12
echo "--- 白名单拦截计数(20m): $(docker logs astrbot --since 20m 2>&1 | grep -c '10000003 is not in the session allowlist') ---"
echo
echo "=== 该会话是否被 proactive 收录 ==="
docker exec astrbot python3 -c "
import json
cfg = json.load(open('/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json', encoding='utf-8-sig'))
fs = cfg.get('friend_settings', {})
print('session_list =', fs.get('session_list'))
"
