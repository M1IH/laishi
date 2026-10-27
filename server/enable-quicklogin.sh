#!/usr/bin/env bash
# 启用快速登录：从 NapCat 配置文件名发现机器人 uin，写入 .env 的 NAPCAT_ACCOUNT，
# 重建 napcat 容器并验证免扫（全程不打印明文号码）
set -euo pipefail
cd /opt/miruku

# 1) 发现 uin（onebot11_<uin>.json 文件名）
UIN=$(docker exec napcat sh -c 'ls /app/napcat/config/' | grep -oE 'onebot11_[0-9]{5,}' | head -1 | sed 's/onebot11_//')
if [ -z "$UIN" ]; then echo "[FAIL] 没能从配置发现机器人 uin"; exit 2; fi
echo "[quicklogin] 发现机器人 uin: $(echo "$UIN" | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/')"

# 2) 写 .env（幂等）
grep -q '^NAPCAT_ACCOUNT=' .env || echo "NAPCAT_ACCOUNT=$UIN" >> .env
chmod 600 .env

# 3) 更新 compose（ACCOUNT 环境变量）并重建 napcat
cp -f server/compose.yaml compose.yaml
sed -i 's/\r$//' compose.yaml
docker compose up -d --force-recreate napcat
sleep 20

echo "[quicklogin] napcat 日志判断登录方式:"
docker logs napcat --since 40s 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' | grep -iE '快速登录|二维码|qrcode|login' | head -5 | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g' || echo "  (无匹配行)"

echo "[quicklogin] 6199 链路:"
for i in 1 2 3 4 5 6; do
  n=$(docker exec astrbot python3 -c "
n=0
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='01': n+=1
    except OSError: pass
print(n)" 2>/dev/null || echo x)
  echo "  t+$((i*10))s ws=$n"
  [ "$n" = "1" ] && { echo "[quicklogin] ★ 免扫重连成功"; break; }
  sleep 10
done
