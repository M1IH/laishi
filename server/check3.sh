#!/usr/bin/env bash
# 正确姿势：先看 docker port 映射，再实测 HTTP；6199 用 /proc/net/tcp（0x1837）查
echo "== docker port =="
docker port astrbot; echo --; docker port napcat
echo "== host curl =="
for p in 6185 4100 6099 6080; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$p/" || echo ERR)
  echo "  127.0.0.1:$p -> $code"
done
echo "== astrbot 6199 listen (0x1837, 0A=LISTEN) =="
docker exec astrbot python3 -c "
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='0A': print('  LISTEN', f, p[1])
    except OSError: pass
"
echo "== napcat -> astrbot 连接尝试痕迹 =="
docker logs napcat 2>&1 | grep -iE 'websocket|reverse|connect' | tail -4
echo "== qrcode.png =="
docker exec napcat ls -la /app/napcat/cache/qrcode.png 2>&1 | tail -1
echo "== heartbeat 最近 =="
tail -2 /var/log/miruku-heartbeat.log
