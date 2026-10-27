#!/usr/bin/env bash
# 扫码后收尾验证（只读，除 touch qr-acked 外不改任何东西）
echo "== 1. AstrBot 是否认到适配器 =="
docker logs astrbot 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E '适配器已连接|aiocqhttp.*(连接|启动)' | tail -3

echo "== 2. 6199 链路（astrbot 容器内 /proc/net/tcp，01=ESTABLISHED）=="
docker exec astrbot python3 -c "
n=0
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='01': n+=1
    except OSError: pass
print('  ESTABLISHED on 6199:', n)"

echo "== 3. 机器人号登录态：login.enc 是否写入、里面有没有机器人号 =="
find /opt/miruku/napcat/qq -name 'login.enc' -newer /opt/miruku/.env -exec ls -la {} \; 2>/dev/null | head -3
ENC=$(find /opt/miruku/napcat/qq -name 'login.enc' 2>/dev/null | head -1)
if [ -n "$ENC" ]; then
  echo "  path: $ENC  mtime: $(stat -c %y "$ENC")"
  echo "  （login.enc 里出现过的 10 位数字，打码显示）:"
  strings "$ENC" 2>/dev/null | grep -oE '[0-9]{10}' | sort -u | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/;s/^/    /' | head -6
else
  echo "  还没生成 login.enc"
fi

echo "== 4. NapCat 侧确认在线（容器日志尾部）=="
docker logs napcat 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' | tail -4

echo "== 5. 打开 WS 自愈闸门 =="
touch /opt/miruku/logs/qr-acked && echo "  qr-acked 已写入"

echo "== 6. 立刻跑一次心跳 =="
bash /opt/miruku/server/heartbeat.sh
tail -2 /var/log/miruku-heartbeat.log
