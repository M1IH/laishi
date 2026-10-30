#!/bin/bash
# C-23/C-24/C-25 补件：容器内隔离验证（整包副本 + 覆盖修改版），不碰生产
set -uo pipefail
PROBE=/tmp/mmprobe2
rm -rf "$PROBE"
mkdir -p "$PROBE"

echo "=== 1. 整包拷线上插件到隔离副本 ==="
docker exec astrbot rm -rf "$PROBE"
docker exec astrbot mkdir -p "$PROBE/core/data/plugins"
docker exec astrbot cp -r /AstrBot/data/plugins/astrbot_plugin_proactive_chat "$PROBE/core/data/plugins/"
echo "copied"

echo "=== 2. 覆盖 5 个修改版 + 新探针 ==="
docker exec astrbot mkdir -p /tmp/patch
docker cp /tmp/ship/sender_service.py astrbot:"$PROBE/core/data/plugins/astrbot_plugin_proactive_chat/core/services/sender_service.py"
docker cp /tmp/ship/scheduler_service.py astrbot:"$PROBE/core/data/plugins/astrbot_plugin_proactive_chat/core/services/scheduler_service.py"
docker cp /tmp/ship/split_delivery.py astrbot:"$PROBE/core/data/plugins/astrbot_plugin_proactive_chat/core/features/deliver/split_delivery.py"
docker cp /tmp/ship/history_writer.py astrbot:"$PROBE/core/data/plugins/astrbot_plugin_proactive_chat/core/features/record/history_writer.py"
docker cp /tmp/ship/flow_orchestrator.py astrbot:"$PROBE/core/data/plugins/astrbot_plugin_proactive_chat/core/pipeline/flow_orchestrator.py"
docker cp /tmp/ship/probe_c09_c10.py astrbot:"$PROBE/probe_c09_c10.py"

echo "=== 3. 语法校验 ==="
docker exec astrbot python3 -c "
import ast
from pathlib import Path
base = Path('$PROBE')
files = [
  'core/data/plugins/astrbot_plugin_proactive_chat/core/services/sender_service.py',
  'core/data/plugins/astrbot_plugin_proactive_chat/core/services/scheduler_service.py',
  'core/data/plugins/astrbot_plugin_proactive_chat/core/features/deliver/split_delivery.py',
  'core/data/plugins/astrbot_plugin_proactive_chat/core/features/record/history_writer.py',
  'core/data/plugins/astrbot_plugin_proactive_chat/core/pipeline/flow_orchestrator.py',
  'probe_c09_c10.py',
]
for f in files:
    ast.parse((base/f).read_text(encoding='utf-8'))
print('CONTAINER_AST_OK')
"

echo "=== 4. 跑全量探针（含 C-24/C-25 补件） ==="
docker exec astrbot sh -c "cd $PROBE && python3 probe_c09_c10.py 2>&1 | tail -40"
