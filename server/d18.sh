#!/usr/bin/env bash
echo "== 插件注入给模型的 prompt 原文（关键：会不会让她变得刻意发图）=="
grep -A15 '\[表情图片工具\]' /opt/miruku/astrbot/data/plugins/meme_manager/main.py 2>/dev/null | head -25

echo ""
echo "== 发送触发的配置项（有多少控制权）=="
python3 - <<'PY'
import json
d = json.load(open("/opt/miruku/astrbot/data/config/meme_manager_config.json", encoding="utf-8-sig"))
for k in sorted(d):
    if k in ("storage", "community", "sync", "webui", "settings_center"):
        continue
    print(f"  {k} = {json.dumps(d[k], ensure_ascii=False)[:160]}")
PY
