#!/usr/bin/env bash
echo "== 各分类的图片数量（确认可用）=="
python3 - <<'PY'
import json, os, glob
p = "/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack"
d = json.load(open(p + "/memes_data.json", encoding="utf-8"))
total = 0
for cat, items in d.items():
    n = len(items) if isinstance(items, list) else (len(items.get("items", [])) if isinstance(items, dict) else 0)
    total += n
    print(f"  {cat:14s} {n} 张")
print(f"  合计 {total} 张")
# 每类抽一张验证文件真实存在
print()
missing = 0
for cat, items in d.items():
    lst = items if isinstance(items, list) else items.get("items", [])
    for it in lst[:1]:
        rel = it.get("path") or it.get("file") or it.get("filename") if isinstance(it, dict) else str(it)
        if rel:
            full = os.path.join(p, rel) if not os.path.isabs(rel) else rel
            if not os.path.isfile(full):
                # 试几种常见路径
                for cand in (os.path.join(p, "memes", cat, os.path.basename(rel)),
                             os.path.join(p, "memes", rel)):
                    if os.path.isfile(cand):
                        break
                else:
                    missing += 1
                    print(f"  [缺失] {cat}: {rel}")
print(f"  抽样缺失: {missing}")
PY

echo ""
echo "== 触发范围配置（chat_and_plugin_llm = 普通聊天也触发）=="
python3 -c "
import json
d=json.load(open('/opt/miruku/astrbot/data/config/meme_manager_config.json',encoding='utf-8-sig'))
g=d.get('generation',{})
print('  scope      =', g.get('trigger',{}).get('scope'))
print('  probability=', g.get('emotion',{}).get('probability'))
print('  max_memes  =', g.get('emotion',{}).get('max_memes_per_message'))
print('  频率指导   =', g.get('prompt',{}).get('quantity_guidance_enabled'))
"
