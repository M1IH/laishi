#!/usr/bin/env bash
echo "===== 语义检索现状 ====="
python3 -c "
import json
d=json.load(open('/opt/miruku/astrbot/data/config/meme_manager_config.json',encoding='utf-8-sig'))
s=d.get('semantic',{})
for k in sorted(s): print(f'  {k} = {s[k]!r}')
"
echo ""
echo "===== AstrBot 里现有哪些 provider（能当 embedding 的）====="
python3 - <<'PY'
import json
d = json.load(open("/opt/miruku/astrbot/data/cmd_config.json", encoding="utf-8-sig"))
print("  provider_sources:")
for s in d.get("provider_sources", []):
    print(f"    - {s.get('id'):12s} type={s.get('type'):32s} base={s.get('api_base','')}")
print("  provider (会话用):")
for p in d.get("provider", []):
    print(f"    - {p.get('id')}")
PY
echo ""
echo "===== 结论 ====="
echo "  小米 MiMo 无 embedding 模型 -> 语义检索无法用小米"
echo "  现有 provider 只有 deepseek / xiaomi，都没有 embedding 接口"
