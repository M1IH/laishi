#!/bin/bash
set -uo pipefail
echo "=== friend_settings 原始结构 ==="
docker exec astrbot python3 -c "
import json
d = json.load(open('/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json', encoding='utf-8-sig'))
fs = d.get('friend_settings')
print('type:', type(fs).__name__)
print(json.dumps(fs, ensure_ascii=False, indent=1)[:1200])
"
