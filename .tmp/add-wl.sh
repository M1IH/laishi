#!/bin/bash
# 加新好友 10000003 进 AstrBot 核心白名单
set -uo pipefail
TS=$(date +%Y%m%d-%H%M%S)

echo "=== 1. 备份 ==="
docker exec astrbot cp /AstrBot/data/cmd_config.json /AstrBot/data/cmd_config.json.bak.$TS && echo "backup: cmd_config.json.bak.$TS"

echo "=== 2. 追加白名单（幂等） ==="
docker exec astrbot python3 -c "
import json
path = '/AstrBot/data/cmd_config.json'
cfg = json.load(open(path, encoding='utf-8-sig'))
wl = cfg['platform_settings']['id_whitelist']
new = 'miruku:FriendMessage:10000003'
if new in wl:
    print('already present:', wl)
else:
    wl.append(new)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print('added ->', json.dumps(wl, ensure_ascii=False))
"

echo "=== 3. 重启 AstrBot（C-10 已修：排期自动恢复） ==="
docker restart astrbot

echo "=== 4. 验证 ==="
sleep 40
docker exec astrbot python3 -c "
import json
cfg = json.load(open('/AstrBot/data/cmd_config.json', encoding='utf-8-sig'))
print('id_whitelist =', json.dumps(cfg['platform_settings']['id_whitelist'], ensure_ascii=False))
"
docker logs astrbot --since 1m 2>&1 | grep -E '恢复任务|重新排期|stall|适配器已连接' | tail -4
