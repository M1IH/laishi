# -*- coding: utf-8 -*-
"""生成容器版 C-09/C-10 探针 + 打包修改后的插件副本。"""
from pathlib import Path
import shutil

WS = Path(r"C:\Users\OTTO\Desktop\来世")
BASE = WS / ".tmp" / "c09base" / "data" / "plugins" / "astrbot_plugin_proactive_chat"
OUT = WS / ".tmp" / "c09ship"
if OUT.exists():
    shutil.rmtree(OUT)

# 1) 插件副本（5 文件修改版，整包带走以防遗漏依赖）
plugin_dst = OUT / "core" / "data" / "plugins" / "astrbot_plugin_proactive_chat"
shutil.copytree(BASE, plugin_dst)

# 2) 容器版探针：CORE 指向 /tmp/mmprobe/core，sys.path 加 /AstrBot
src = (WS / "data" / "probe_c09_c10.py").read_text(encoding="utf-8")
old_core = (
    "CORE = Path(\n"
    '    r"C:/Users/OTTO/.astrbot_launcher/instances/"\n'
    '    r"298681be-6ba8-4137-818c-28ed67ec9176/core"\n'
    ")"
)
new_core = 'CORE = Path("/tmp/mmprobe/core")'
assert old_core in src, "CORE 常量锚文本未找到"
src = src.replace(old_core, new_core)
old_syspath = "for p in (str(CORE), str(PLUGINS)):"
new_syspath = 'for p in (str(CORE), str(PLUGINS), "/AstrBot"):'
assert old_syspath in src, "sys.path 锚文本未找到"
src = src.replace(old_syspath, new_syspath)
(OUT / "probe_c09_c10.py").write_text(src, encoding="utf-8")

# 3) 校验修改后的插件源码能被 ast 解析（语法层）
import ast

for rel in (
    "core/services/sender_service.py",
    "core/services/scheduler_service.py",
    "core/features/deliver/split_delivery.py",
    "core/features/record/history_writer.py",
    "core/pipeline/flow_orchestrator.py",
):
    ast.parse((plugin_dst / rel).read_text(encoding="utf-8"))
    print("AST_OK", rel)

# 4) 摘要
import os

for p in sorted(OUT.rglob("*")):
    if p.is_file():
        print(f"  {p.relative_to(OUT)}  {p.stat().st_size}B")
print("BUILD_OK ->", OUT)
