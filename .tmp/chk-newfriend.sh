#!/bin/bash
# 排查新好友 10000003 消息无回应
set -uo pipefail
UIN=10000003

echo "=== 1. SnowLuma 侧：消息事件是否进来 ==="
docker exec snowluma sh -c "grep -h '$UIN' /app/data/logs/*.log 2>/dev/null | tail -8" || echo "(snowluma 日志无记录)"

echo "=== 2. AstrBot 侧：收到/处理记录 ==="
docker logs astrbot --since 3h 2>&1 | grep "$UIN" | tail -15
echo "--- (3h 内总提及行数: $(docker logs astrbot --since 3h 2>&1 | grep -c "$UIN")) ---"

echo "=== 3. Miruku 自己(10000004)最近的收发(对照组) ==="
docker logs astrbot --since 1h 2>&1 | grep -E '10000004' | tail -5

echo "=== 4. AstrBot 唤醒/平台配置 ==="
docker exec astrbot python3 -c "
import json
cfg = json.load(open('/AstrBot/data/cmd_config.json', encoding='utf-8-sig'))
ps = cfg.get('platform_settings', {})
for k in ('unique_session','wake_prefix','wake_require_prefix','mention_require','at_require','friend_message_wake'):
    if k in ps: print(k, '=', ps[k])
print('platform_settings keys:', list(ps.keys())[:20])
for p in cfg.get('platform', []):
    print('platform:', p.get('id'), p.get('type'), 'enable=', p.get('enable'))
"

echo "=== 5. proactive_chat gating 配置 ==="
docker exec astrbot python3 -c "
import json
cfg = json.load(open('/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json', encoding='utf-8-sig'))
fs = cfg.get('friend_settings', {})
print('session_list:', fs.get('session_list'))
gat = {k: v for k, v in fs.items() if 'gate' in k or 'session' in k or 'enable' in k}
print('gating-ish:', json.dumps(gat, ensure_ascii=False)[:600])
"

echo "=== 6. 好友列表确认(新好友是否已在 SnowLuma 好友列表) ==="
TOKEN=$(docker exec astrbot python3 -c "import json;print(json.load(open('/var/lib/docker/volumes/qq-gateway-data/_data/config/onebot.json' if False else '/dev/null'))['x'] if False else '')" 2>/dev/null)
docker exec snowluma sh -c "ls /app/.config/QQ/ 2>/dev/null | head -5; echo ---; cat /app/data/config/onebot.json 2>/dev/null | head -30"
