#!/usr/bin/env bash
echo "===== 1. 先看 xiaomi provider 在 AstrBot 里的确切 id ====="
python3 - <<'PY'
import json
d = json.load(open("/opt/miruku/astrbot/data/cmd_config.json", encoding="utf-8-sig"))
for s in d.get("provider_sources", []):
    print(f"  source id={s.get('id')!r} type={s.get('type')}")
print("  provider 列表:")
for p in d.get("provider", []):
    print(f"    id={p.get('id')!r} model={p.get('model')!r} source={p.get('provider_source_id')!r} enable={p.get('enable')}")
PY

echo ""
echo "===== 2. 当前情感模型配置 ====="
python3 -c "
import json
d=json.load(open('/opt/miruku/astrbot/data/config/meme_manager_config.json',encoding='utf-8-sig'))
e=d.get('generation',{}).get('emotion',{}).get('llm',{})
print('  enabled     =', e.get('enabled'))
print('  provider_id =', repr(e.get('provider_id')))
print('  context_turns =', e.get('context_turns'))
print('  inject_persona =', e.get('inject_persona'))
"

echo ""
echo "===== 3. proactive 插件是否支持分时段频率 ====="
python3 - <<'PY'
import json
p = "/opt/miruku/astrbot/data/config/astrbot_plugin_proactive_chat_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
s = d["friend_settings"]["schedule_settings"]
print("  schedule_settings 现有键:")
for k in sorted(s):
    print(f"    {k} = {s[k]!r}")
PY
