#!/usr/bin/env bash
echo "===== 情感模型会输出哪些标签（读插件的标签表）====="
grep -oE '"[a-z_]{3,20}"' /opt/miruku/astrbot/data/plugins/meme_manager/mixins/event_handlers.py 2>/dev/null \
  | sort -u | head -40

echo ""
echo "===== 插件内置的标准分类定义（找它的映射表）====="
grep -rn -iE 'sigh|confused|sad' /opt/miruku/astrbot/data/plugins/meme_manager/*.py /opt/miruku/astrbot/data/plugins/meme_manager/**/*.py 2>/dev/null \
  | grep -viE '^Binary' | head -10

echo ""
echo "===== builtin-default 有哪些标准分类（它的 memes_data.json）====="
cat /opt/miruku/astrbot/data/plugin_data/meme_manager/packs/builtin-default/memes_data.json 2>/dev/null | head -c 800; echo
