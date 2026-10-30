#!/bin/bash
# C-09/C-10 上线：备份 5 文件 -> 覆盖 -> 重启 -> 验证恢复日志
set -uo pipefail
TS=$(date +%Y%m%d-%H%M%S)
P=/AstrBot/data/plugins/astrbot_plugin_proactive_chat
S=/tmp/c09ship/core/data/plugins/astrbot_plugin_proactive_chat

echo "=== 1. 线上备份 ==="
docker exec astrbot tar -cf /tmp/pc-backup-$TS.tar -C /AstrBot/data/plugins astrbot_plugin_proactive_chat
docker cp astrbot:/tmp/pc-backup-$TS.tar /opt/miruku/backups/pc-backup-$TS.tar
ls -la /opt/miruku/backups/pc-backup-$TS.tar

echo "=== 2. 覆盖 5 文件 ==="
docker cp $S/core/services/sender_service.py    astrbot:$P/core/services/sender_service.py
docker cp $S/core/services/scheduler_service.py astrbot:$P/core/services/scheduler_service.py
docker cp $S/core/features/deliver/split_delivery.py astrbot:$P/core/features/deliver/split_delivery.py
docker cp $S/core/features/record/history_writer.py  astrbot:$P/core/features/record/history_writer.py
docker cp $S/core/pipeline/flow_orchestrator.py astrbot:$P/core/pipeline/flow_orchestrator.py
docker exec astrbot python3 -c "import ast; [ast.parse(open('$P/'+f).read()) for f in ('core/services/sender_service.py','core/services/scheduler_service.py','core/features/deliver/split_delivery.py','core/features/record/history_writer.py','core/pipeline/flow_orchestrator.py')]; print('AST_OK')"

echo "=== 3. 重启 AstrBot（C-10 口径验证：重启后自动恢复排期）==="
docker restart astrbot

echo "=== 4. 启动日志验证 ==="
sleep 45
docker logs astrbot --since 2m 2>&1 | grep -E '主动消息|恢复任务|重新排期|miruku_outbound armed|meme_manager' | tail -15
