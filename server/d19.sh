#!/usr/bin/env bash
echo "== generation 配置全貌（决定触发范围与频率）=="
python3 - <<'PY'
import json
d = json.load(open("/opt/miruku/astrbot/data/config/meme_manager_config.json", encoding="utf-8-sig"))
print(json.dumps(d.get("generation", {}), ensure_ascii=False, indent=1)[:2000])
PY
