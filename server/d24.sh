#!/usr/bin/env bash
echo "== memes_data.json 真实结构（前 600 字符）=="
head -c 600 /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack/memes_data.json; echo
echo ""
echo "== 分类对应目录的实际图片数 =="
PACK=/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack
for d in "$PACK"/memes/*/; do
  [ -d "$d" ] || continue
  n=$(find "$d" -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.gif' -o -name '*.webp' \) | wc -l)
  echo "  $(basename "$d"): $n 张"
done
echo -n "  总计: "
find "$PACK/memes" -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.gif' -o -name '*.webp' \) | wc -l
