#!/usr/bin/env bash
echo "== 插件识别到哪些表情包 =="
docker logs astrbot --since 5m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'pack|类别|memes_data|表情包|juxueli' | tail -15

echo ""
echo "== packs 目录实际内容 =="
ls -la /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/ | head -10
echo ""
echo "== juxueli 包内文件数 =="
find /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack -type f 2>/dev/null | wc -l
echo ""
echo "== 每个包的 memes_data.json 是否存在（插件靠它识别）=="
for d in /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/*/; do
  name=$(basename "$d")
  has=$([ -f "$d/memes_data.json" ] && echo YES || echo "NO ")
  cnt=$(find "$d" -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.gif' -o -name '*.webp' \) 2>/dev/null | wc -l)
  echo "  $has  $name  (图片 $cnt)"
done

echo ""
echo "== 语义索引是否构建 =="
docker logs astrbot --since 5m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'semantic|embedding|faiss|索引' | tail -6 || echo "  （无相关日志）"