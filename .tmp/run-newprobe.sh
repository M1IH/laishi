#!/bin/bash
# 本地隔离验证 C-24/C-25 补件探针（在容器/本地拉起 astrbot 代码树即可，不碰生产）
set -uo pipefail
cd /tmp/mmprobe 2>/dev/null || { echo "NO_MMPROBE"; exit 1; }
python3 - <<'PY'
import sys, ast
from pathlib import Path
# 语法先行
for f in ("core/data/plugins/astrbot_plugin_proactive_chat/core/services/sender_service.py",
          "core/data/plugins/astrbot_plugin_proactive_chat/core/services/scheduler_service.py"):
    ast.parse(Path(f).read_text(encoding="utf-8"))
print("AST_OK")
PY
python3 probe_c09_c10.py --only C10-06B,C09-07B 2>&1 | tail -30
