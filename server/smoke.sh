#!/usr/bin/env bash
# login.db 里有没有机器人号（决定重启后能否免扫）+ 冒烟触发（测试号）
# 机器人号不写明文：从 NapCat 自己的配置文件名里发现
DB=/opt/miruku/napcat/qq/global/nt_db/login.db
BOT=$(docker exec napcat sh -c 'ls /app/napcat/config/' 2>/dev/null | grep -oE 'onebot11_[0-9]{5,}' | head -1 | sed 's/onebot11_//')
echo "== login.db 里出现的 10 位号（打码）=="
if [ -f "$DB" ]; then
  strings "$DB" 2>/dev/null | grep -oE '[0-9]{10}' | sort -u | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/' | head -6
  if [ -n "$BOT" ] && strings "$DB" 2>/dev/null | grep -q "$BOT"; then
    echo "  → 机器人号在 login.db：YES（重启后有望免扫）"
  else
    echo "  → 机器人号在 login.db：no（或未发现机器人号；重启可能仍要扫码）"
  fi
else
  echo "  login.db 不存在"
fi

echo "== 冒烟：对测试号手动触发一条主动消息 =="
UMO=$(python3 -c "import json;d=json.load(open('/opt/miruku/astrbot/data/laishi/proactive_targets.local.json',encoding='utf-8'));print(d['test'])")
curl -s -X POST --max-time 30 "http://127.0.0.1:4100/api/jobs/${UMO}/trigger" | head -c 200; echo
sleep 12
docker logs astrbot 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E '主动消息' | tail -6
