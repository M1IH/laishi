#!/bin/bash
# C-09/C-10 探针 v2：整包线上插件做底，覆盖 5 个修改文件，再跑探针
set -uo pipefail
echo "=== 1. 整包线上插件 -> /tmp/mmprobe ==="
docker exec astrbot rm -rf /tmp/mmprobe
docker exec astrbot mkdir -p /tmp/mmprobe/core/data/plugins
docker exec astrbot cp -r /AstrBot/data/plugins/astrbot_plugin_proactive_chat /tmp/mmprobe/core/data/plugins/
docker cp /tmp/c09ship/probe_c09_c10.py astrbot:/tmp/mmprobe/probe_c09_c10.py

echo "=== 2. 覆盖 5 个修改文件 ==="
P=/tmp/mmprobe/core/data/plugins/astrbot_plugin_proactive_chat
docker cp /tmp/c09ship/core/data/plugins/astrbot_plugin_proactive_chat/core/services/sender_service.py    astrbot:$P/core/services/sender_service.py
docker cp /tmp/c09ship/core/data/plugins/astrbot_plugin_proactive_chat/core/services/scheduler_service.py astrbot:$P/core/services/scheduler_service.py
docker cp /tmp/c09ship/core/data/plugins/astrbot_plugin_proactive_chat/core/features/deliver/split_delivery.py astrbot:$P/core/features/deliver/split_delivery.py
docker cp /tmp/c09ship/core/data/plugins/astrbot_plugin_proactive_chat/core/features/record/history_writer.py  astrbot:$P/core/features/record/history_writer.py
docker cp /tmp/c09ship/core/data/plugins/astrbot_plugin_proactive_chat/core/pipeline/flow_orchestrator.py astrbot:$P/core/pipeline/flow_orchestrator.py
docker exec astrbot python3 -c "import ast; [ast.parse(open('$P/'+f).read()) for f in ('core/services/sender_service.py','core/services/scheduler_service.py','core/features/deliver/split_delivery.py','core/features/record/history_writer.py','core/pipeline/flow_orchestrator.py')]; print('AST_OK_CONTAINER')"

echo "=== 3. 跑探针 ==="
docker exec -w /tmp/mmprobe astrbot python3 probe_c09_c10.py 2>&1 | tail -40
