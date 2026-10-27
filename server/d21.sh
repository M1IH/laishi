#!/usr/bin/env bash
echo "== juxueli 的 memes_data.json 结构（前 800 字符）=="
head -c 800 /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack/memes_data.json 2>/dev/null; echo

echo ""
echo "== 目录里还有什么文件（元数据可能在别处）=="
ls -la /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack/ | head -15

echo ""
echo "== 子目录 =="
find /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack -maxdepth 2 -type d | head

echo ""
echo "== 图片样例（文件名通常带语义）=="
find /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.gif' \) | head -8
