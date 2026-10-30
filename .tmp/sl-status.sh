#!/bin/bash
echo "=== QQ status ==="
docker exec snowluma sh -c "grep -hE 'login detected|awaiting login' /app/data/logs/*.log 2>/dev/null | tail -2"
docker exec snowluma sh -c "grep -h 'WS-Client' /app/data/logs/*.log 2>/dev/null | tail -1"
echo "=== jobs ==="
docker exec astrbot python3 -c "
import urllib.request, json
try:
    d = json.load(urllib.request.urlopen('http://127.0.0.1:4100/api/jobs'))
    print(json.dumps(d, ensure_ascii=False)[:500])
except Exception as e:
    print('jobs ERR', e)
"
echo "=== outbound logs (20h) ==="
docker logs astrbot --since 20h 2>&1 | grep miruku_outbound | tail -5
