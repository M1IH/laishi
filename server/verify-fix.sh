#!/usr/bin/env bash
# 部署 v0.7.0 后的完整验证：适配器重连 + 冒烟
echo "== astrbot 启动与插件 =="
docker logs astrbot --since 60s 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E 'context_guard|适配器已连接|主动消息.*(初始化|触发器完成)' | tail -5
sleep 6
echo "== 6199 链路 =="
docker exec astrbot python3 -c "
n=0
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='01': n+=1
    except OSError: pass
print('  ESTABLISHED:',n)"
echo "== 冒烟（测试号）=="
UMO=$(python3 -c "import json;d=json.load(open('/opt/miruku/astrbot/data/laishi/proactive_targets.local.json',encoding='utf-8'));print(d['test'])")
curl -s -X POST --max-time 30 "http://127.0.0.1:4100/api/jobs/${UMO}/trigger" | head -c 120; echo
sleep 14
docker logs astrbot --since 40s 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E 'Miruku context|主动消息.*(LLM|发送|送达|失败)|Prepare to send' | tail -8
