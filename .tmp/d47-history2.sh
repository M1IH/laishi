#!/bin/bash
# 读 SnowLuma accessToken 并带 token 重试历史 API
TOKEN=$(python3 -c "
import json
p='/var/lib/docker/volumes/qq-gateway-data/_data/config/onebot_10000004.json'
try:
    d=json.load(open(p,encoding='utf-8-sig'))
    print(d.get('accessToken') or d.get('access_token') or '')
except Exception as e:
    print('')
")
if [ -z "$TOKEN" ]; then
  TOKEN=$(python3 -c "
import json
p='/var/lib/docker/volumes/qq-gateway-data/_data/config/onebot.json'
try:
    d=json.load(open(p,encoding='utf-8-sig'))
    n=d.get('networks') or {}
    h=n.get('httpServers') or []
    print((h[0].get('accessToken') if h else '') or '')
except Exception as e:
    print('')
")
fi
echo "token_len=${#TOKEN}"
docker exec -e TOKEN="$TOKEN" astrbot python3 -c "
import json, os, urllib.request
tok = os.environ.get('TOKEN', '')
def call(action, payload):
    req = urllib.request.Request(
        f'http://snowluma:3000/{action}',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {tok}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {'_error': str(e)}

r = call('get_version_info', {})
print('version:', str(r.get('data'))[:120] if 'data' in r else r)

r = call('get_friend_msg_history', {'user_id': 10000001, 'count': 5})
if '_error' in r:
    print('history:', r['_error'])
else:
    print('history status:', r.get('status'), 'retcode:', r.get('retcode'), str(r.get('wording'))[:80] if r.get('retcode') not in (0, 1) else '')
    data = r.get('data')
    msgs = data.get('messages') if isinstance(data, dict) else data
    if isinstance(msgs, list):
        print('count:', len(msgs))
        for m in msgs[-3:]:
            raw = m.get('message')
            if isinstance(raw, list):
                segs = ''.join(s.get('data', {}).get('text', '') if s.get('type') == 'text' else f\"[{s.get('type')}]\" for s in raw)
            else:
                segs = str(raw)
            print(' ', m.get('time'), str(m.get('sender', {}).get('nickname'))[:16], repr(segs)[:80])
    else:
        print('data:', str(data)[:150])
"
