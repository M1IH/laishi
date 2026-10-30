#!/bin/bash
# ①掉线窗口消息连续性（token 用全局 onebot.json 的 httpServers.accessToken）
TOKEN=$(python3 -c "
import json
p='/var/lib/docker/volumes/qq-gateway-data/_data/config/onebot.json'
d=json.load(open(p,encoding='utf-8-sig'))
h=(d.get('networks') or {}).get('httpServers') or []
print((h[0].get('accessToken') if h else '') or d.get('accessToken') or '')
")
echo "token_len=${#TOKEN}"
docker exec -e TOKEN="$TOKEN" astrbot python3 -c "
import json, os, urllib.request, datetime
tok = os.environ.get('TOKEN', '')
def call(action, payload):
    req = urllib.request.Request(
        f'http://snowluma:3000/{action}',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {tok}'},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

tz = datetime.timezone(datetime.timedelta(hours=8))
lo = int(datetime.datetime(2026, 10, 29, 16, 51, tzinfo=tz).timestamp())
hi = int(datetime.datetime(2026, 10, 29, 19, 17, tzinfo=tz).timestamp())
r = call('get_friend_msg_history', {'user_id': 10000001, 'count': 100})
msgs = (r.get('data') or {}).get('messages') or []
times = [m.get('time', 0) for m in msgs]
print(f'拉到 {len(msgs)} 条, 时间戳范围 {min(times)}..{max(times)}')
inwin = [m for m in msgs if lo <= m.get('time', 0) <= hi]
print(f'掉线窗口内消息: {len(inwin)} 条')
for m in inwin[:12]:
    raw = m.get('message')
    segs = ''.join(s.get('data', {}).get('text','') if s.get('type')=='text' else f\"[{s.get('type')}]\" for s in raw) if isinstance(raw, list) else str(raw)
    print(' ', datetime.datetime.fromtimestamp(m['time'], tz).strftime('%m-%d %H:%M:%S'), m.get('sender', {}).get('user_id'), repr(segs)[:70])
print('首条:', datetime.datetime.fromtimestamp(min(times), tz), ' 末条:', datetime.datetime.fromtimestamp(max(times), tz))
"
echo "=== G8 白名单核对 ==="
docker exec astrbot python3 -c "
import json
d = json.load(open('/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json', encoding='utf-8-sig'))
fs = d.get('friend_settings') or {}
for sid, s in fs.items():
    ss = s.get('schedule_settings') or {}
    at = s.get('auto_trigger_settings') or {}
    print('会话:', sid, '| enable:', s.get('enable'), '| auto:', at.get('enable_auto_trigger'), '| quiet:', ss.get('quiet_hours'), '| max_unanswered:', s.get('max_unanswered_count'))
"
