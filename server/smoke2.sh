#!/usr/bin/env bash
# 冒烟：对测试号发一条主动消息，验证整条链路真能收发
set -e
UMO=$(python3 -c "import json;d=json.load(open('/opt/miruku/astrbot/data/laishi/proactive_targets.local.json',encoding='utf-8'));print(d['test'])")
echo "== 触发主动消息（测试号）=="
curl -s -X POST --max-time 30 "http://127.0.0.1:4100/api/jobs/${UMO}/trigger" | head -c 120; echo
sleep 14
echo ""
echo "== 结果 =="
docker logs astrbot --since 40s 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '主动消息.*(LLM|发送|送达|失败)|Prepare to send' | tail -6 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'
echo ""
echo "== NapCat 侧发送记录 =="
docker logs napcat --since 40s 2>&1 | grep -vE '^[0-9a-f]{40,}$' \
  | grep -iE '发送|SendMsg|error' | tail -5 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'
