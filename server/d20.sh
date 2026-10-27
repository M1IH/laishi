#!/usr/bin/env bash
echo "== 当前实际生效的 prompt 是模板版还是语义版 =="
docker logs astrbot --since 20m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE '语义检索已开启|没有可重建|分类|semantic|fallback|回退' \
  | grep -viE 'DEPRECATION' | tail -8 || echo "  （无）"

echo ""
echo "== 分类列表是否已生成（模板版依赖它）=="
python3 - <<'PY'
import json, os
for p in ("/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack/memes_data.json",
          "/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/builtin-default/memes_data.json"):
    if not os.path.isfile(p):
        print("  缺失:", p); continue
    d = json.load(open(p, encoding="utf-8"))
    name = p.split("/")[-2]
    if isinstance(d, dict):
        memes = d.get("memes") or d.get("items") or []
        cats = d.get("categories") or d.get("category") or {}
        print(f"  {name}: 条目 {len(memes)}, 分类键 {len(cats) if hasattr(cats,'__len__') else '?'}")
        if isinstance(cats, dict):
            print("     分类样例:", list(cats)[:8])
    else:
        print(f"  {name}: list, {len(d)} 条")
PY

echo ""
echo "== markup 配置（决定 &&分类键&& 怎么变成图片）=="
python3 - <<'PY'
import json
d = json.load(open("/opt/miruku/astrbot/data/config/meme_manager_config.json", encoding="utf-8-sig"))
print(json.dumps(d.get("generation", {}).get("markup", {}), ensure_ascii=False, indent=1)[:600])
PY
