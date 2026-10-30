#!/bin/bash
# 部署 C-23/C-24/C-25 修复：proactive_chat 2 文件 + outbound 插件 2 文件，一次重启
set -uo pipefail
TS=$(date +%Y%m%d-%H%M%S)
PC=/AstrBot/data/plugins/astrbot_plugin_proactive_chat
OB=/AstrBot/data/plugins/astrbot_plugin_miruku_outbound

echo "=== 1. 备份 ==="
docker exec astrbot tar -cf /tmp/pc-backup-$TS.tar -C /AstrBot/data/plugins astrbot_plugin_proactive_chat astrbot_plugin_miruku_outbound
echo "backup: /opt/miruku/backups/pc-backup-$TS.tar"

echo "=== 2. proactive_chat：C-24 + C-25 ==="
docker cp /tmp/ship/sender_service.py    astrbot:"$PC/core/services/sender_service.py"
docker cp /tmp/ship/scheduler_service.py astrbot:"$PC/core/services/scheduler_service.py"

echo "=== 3. outbound 插件：C-23 三态 ==="
docker exec astrbot mkdir -p "$OB"
docker cp /tmp/ob/main.py          astrbot:"$OB/main.py"
docker cp /tmp/ob/outbound_core.py astrbot:"$OB/outbound_core.py"
docker cp /tmp/ob/metadata.yaml    astrbot:"$OB/metadata.yaml"

echo "=== 4. 语法校验 ==="
docker exec astrbot python3 -c "
import ast
for f in ('$PC/core/services/sender_service.py','$PC/core/services/scheduler_service.py',
          '$OB/main.py','$OB/outbound_core.py'):
    ast.parse(open(f, encoding='utf-8').read())
print('PROD_AST_OK')
" || exit 1

echo "=== 5. 生产代码冒烟（三态 + partial） ==="
docker exec astrbot python3 -c "
import os, sys
os.environ['OUTBOUND_DATA_DIR'] = '/AstrBot/data/plugin_data/miruku_outbound'
sys.path.insert(0, '$OB')
import outbound_core as ob
print('songs =', len(ob.song_levels()))
for label, t in (('纯thought','<thought>x</thought>'), ('纯Profile','[Profile: a=b]'),
                 ('空',''), ('正文','那下课就直奔床吧'),
                 ('标记+正文','<thought>想想</thought>晚上吃面')):
    o = ob.guard3(t)
    print(f'  {label}: state={o.state} sendable={o.sendable} text={o.text!r}')
"

echo "=== 6. 重启 AstrBot ==="
docker restart astrbot

echo "=== 7. 验证 ==="
sleep 45
docker logs astrbot --since 2m 2>&1 | grep -E 'miruku_outbound.*armed|恢复任务|重新排期|适配器已连接' | tail -6
