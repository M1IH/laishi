#!/usr/bin/env bash
# NapCat 容器健康检查 + WebUI 登录页可达性（只读）
echo "== napcat last non-hash lines =="
docker logs napcat 2>&1 | grep -Ev '^[0-9a-f]{40,}$' | tail -8 | sed 's/\x1b\[[0-9;]*m//g'
echo "== 6099 webui redirect =="
curl -s -o /dev/null -w 'root %{http_code} -> %{redirect_url}\n' --max-time 5 http://127.0.0.1:6099/
echo "== process tree =="
docker top napcat 2>/dev/null | awk 'NR<8{print "  "$0}'
echo "== qrcode file =="
docker exec napcat ls -la /app/napcat/cache/qrcode.png 2>&1 | tail -1
echo "== astrbot ws listener still there =="
docker exec astrbot python3 -c "
n=0
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='0A': n+=1
    except OSError: pass
print('  6199 LISTEN entries:', n)"
