#!/usr/bin/env bash
# 免扫验证：重启 napcat，看它能否用 login.db 免扫码重新登录
# （Windows 上机器人号天生不进快速登录名单；服务器独占 profile 是干净实验）
echo "== 重启前链路 =="
docker exec astrbot python3 -c "
n=0
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='01': n+=1
    except OSError: pass
print('  ESTABLISHED:',n)"
docker restart napcat
echo "== 等 45 秒观察是否免扫重连 =="
for i in 1 2 3 4 5 6 7 8 9; do
  sleep 5
  n=$(docker exec astrbot python3 -c "
n=0
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='01': n+=1
    except OSError: pass
print(n)" 2>/dev/null || echo x)
  echo "  t+$((i*5))s ws=$n"
  [ "$n" = "1" ] && break
done
echo "== napcat 日志尾部（判断是快速登录还是二维码）=="
docker logs napcat --since 60s 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'quick|login|二维码|qrcode|登录' | tail -6
echo "== astrbot 侧 =="
docker logs astrbot --since 60s 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E '适配器已连接|断开' | tail -3
