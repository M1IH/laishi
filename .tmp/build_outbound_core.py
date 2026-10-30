#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成插件版 outbound_core.py：knowledge/outbound.py + 数据路径参数化。

OUTBOUND_DATA_DIR 环境变量存在 → 用它（线上插件场景）；
否则回落 ROOT/data/maimai（本地探针场景，探针零改动）。
"""
from pathlib import Path

SRC = Path("knowledge/outbound.py")
DST = Path(".tmp/plugin_build/outbound_core.py")

src = SRC.read_text(encoding="utf-8")

old_import = "import json\nimport re\nimport unicodedata\n"
new_import = "import json\nimport os\nimport re\nimport unicodedata\n"
assert src.count(old_import) == 1, "import block not unique"
src = src.replace(old_import, new_import)

old_path = (
    'ROOT = Path(__file__).resolve().parents[1]\n'
    'TRUTH_PATH = ROOT / "data" / "maimai" / "b50_miruku.json"'
)
new_path = (
    'ROOT = Path(__file__).resolve().parents[1]\n'
    '\n'
    'def _data_dir() -> Path:\n'
    '    env = os.environ.get("OUTBOUND_DATA_DIR")\n'
    '    return Path(env) if env else ROOT / "data" / "maimai"\n'
    '\n'
    'TRUTH_PATH = _data_dir() / "b50_miruku.json"'
)
assert src.count(old_path) == 1, "TRUTH_PATH block not unique"
src = src.replace(old_path, new_path)

old_song = 'SONGLIST_PATH = ROOT / "data" / "maimai" / "song_list.json"'
new_song = 'SONGLIST_PATH = _data_dir() / "song_list.json"'
assert src.count(old_song) == 1, "SONGLIST_PATH not unique"
src = src.replace(old_song, new_song)

# 插件内不再引用 ROOT 的话可以保留（无害）。写文件并做语法校验。
DST.parent.mkdir(parents=True, exist_ok=True)
DST.write_text(src, encoding="utf-8")

import ast
ast.parse(src)
print(f"OK {DST} ({len(src)} chars), syntax valid")
print("ROOT refs left:", src.count("ROOT /"))
