#!/bin/bash
# 构建待部署产物到 /tmp/ship（宿主侧），probe 的 CORE 常量改为容器隔离副本路径
set -uo pipefail
mkdir -p /tmp/ship
P=core/data/plugins/astrbot_plugin_proactive_chat

cp "/root/uploads/sender_service.py"          /tmp/ship/sender_service.py
cp "/root/uploads/scheduler_service.py"       /tmp/ship/scheduler_service.py
cp "/root/uploads/split_delivery.py"          /tmp/ship/split_delivery.py
cp "/root/uploads/history_writer.py"          /tmp/ship/history_writer.py
cp "/root/uploads/flow_orchestrator.py"       /tmp/ship/flow_orchestrator.py

# 探针：CORE 指向容器隔离副本；sys.path 补 /AstrBot
python3 - <<'PY'
from pathlib import Path
src = Path('/root/uploads/probe_c09_c10.py').read_text(encoding='utf-8')
old = '''CORE = Path(
    r"C:/Users/OTTO/.astrbot_launcher/instances/"
    r"298681be-6ba8-4137-818c-28ed67ec9176/core"
)'''
new = 'CORE = Path("/tmp/mmprobe2/core")'
assert old in src, "CORE 常量锚点未命中"
src = src.replace(old, new, 1)
# 保证 /AstrBot 在 sys.path（容器内 astrbot 包位置）
if "'/AstrBot'" not in src:
    anchor = "sys.path.insert(0, str(CORE / \"data\" / \"plugins\"))"
    if anchor in src:
        src = src.replace(anchor, anchor + "\nsys.path.insert(0, '/AstrBot')", 1)
    else:
        # 兜底：在 import 段后追加
        src = src.replace("import argparse", "import argparse", 1)
        src = src.replace(
            "PLUGIN_DATA = CORE",
            "sys.path.insert(0, '/AstrBot')\nPLUGIN_DATA = CORE",
            1,
        )
Path('/tmp/ship/probe_c09_c10.py').write_text(src, encoding='utf-8')
print("PROBE_REWRITTEN", "CORE=/tmp/mmprobe2/core")
PY

echo "=== ship 内容 ==="
ls -l /tmp/ship/
python3 -c "
import ast
from pathlib import Path
for f in Path('/tmp/ship').glob('*.py'):
    ast.parse(f.read_text(encoding='utf-8'))
print('SHIP_AST_OK')
"
