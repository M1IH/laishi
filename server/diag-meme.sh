#!/usr/bin/env bash
echo "===== 表情：情感标签从哪来，为什么和我们的分类对不上 ====="
docker logs astrbot --since 10h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme' | grep -viE 'DEPRECATION' | grep -E '情感|标签|概率|随机|命中' | tail -16

echo ""
echo "===== 我们的分类 vs 情感模型可能输出的标签 ====="
echo "  包内分类:"
python3 -c "
import json
d=json.load(open('/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack/memes_data.json',encoding='utf-8'))
for k in d: print('   ', k)
"

echo ""
echo "===== 情感模型配置（用哪个 provider 判情绪）====="
python3 -c "
import json
d=json.load(open('/opt/miruku/astrbot/data/config/meme_manager_config.json',encoding='utf-8-sig'))
e=d.get('generation',{}).get('emotion',{})
print(json.dumps(e,ensure_ascii=False,indent=1))
"
