#!/bin/bash
# D4-7 空窗消息可补性实测：SnowLuma OneBot 历史消息 API
echo "=== 1. get_friend_msg_history（go-cqhttp 扩展）==="
docker exec astrbot python3 -c "
import json, urllib.request
def call(action, payload):
    req = urllib.request.Request(
        f'http://snowluma:3000/{action}',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {'_error': str(e)}

r = call('get_friend_msg_history', {'user_id': 10000001, 'count': 5})
if '_error' in r:
    print('get_friend_msg_history:', r['_error'])
else:
    print('status:', r.get('status'), 'retcode:', r.get('retcode'))
    msgs = (r.get('data') or {}).get('messages') if isinstance(r.get('data'), dict) else r.get('data')
    if isinstance(msgs, list):
        print('count:', len(msgs))
        for m in msgs[-3:]:
            segs = m.get('message') if not isinstance(m.get('message'), list) else ''.join(
                s.get('data', {}).get('text', '[非文本]') if s.get('type') == 'text' else f\"[{s.get('type')}]\"
                for s in m['message'])
            print(' ', m.get('time'), m.get('sender', {}).get('nickname'), repr(segs)[:80])
    else:
        print('data:', str(r.get('data'))[:200])
"
echo "=== 2. get_version_info（对照 API 可用性）==="
docker exec astrbot python3 -c "
import json, urllib.request
req = urllib.request.Request('http://snowluma:3000/get_version_info', data=b'{}', headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode())
    print('version:', (d.get('data') or {}).get('app_name'), (d.get('data') or {}).get('app_version'))
except Exception as e:
    print('error:', e)
"
