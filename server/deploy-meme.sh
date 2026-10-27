#!/usr/bin/env bash
# 部署 meme_manager 到 AstrBot 数据卷
set -e
DATA=/opt/miruku/astrbot/data
STAGE=/tmp/meme-stage

echo "== 部署前 =="
docker inspect astrbot --format '  astrbot status={{.State.Status}}'
du -sh "$DATA" 2>/dev/null | sed 's/^/  当前数据卷: /'

# 1) 插件本体
rm -rf "$DATA/plugins/meme_manager"
cp -a "$STAGE/plugins/meme_manager" "$DATA/plugins/meme_manager"
echo "  [ok] 插件已放置"

# 2) 表情包数据（保留已有的，不覆盖）
mkdir -p "$DATA/plugin_data/meme_manager"
if [ -d "$STAGE/plugin_data/meme_manager/packs" ]; then
  cp -an "$STAGE/plugin_data/meme_manager/packs/." "$DATA/plugin_data/meme_manager/packs/" 2>/dev/null || true
  mkdir -p "$DATA/plugin_data/meme_manager/packs"
  cp -an "$STAGE/plugin_data/meme_manager/packs/." "$DATA/plugin_data/meme_manager/packs/" 2>/dev/null || true
fi
mkdir -p "$DATA/plugin_data/meme_manager"/{backup,semantic_indexes,temp}
echo "  [ok] 表情包数据已放置"

# 3) 配置
if [ -f "$STAGE/config/meme_manager_config.json" ]; then
  mkdir -p "$DATA/config"
  [ -f "$DATA/config/meme_manager_config.json" ] && cp -a "$DATA/config/meme_manager_config.json" "$DATA/config/meme_manager_config.json.bak"
  cp -a "$STAGE/config/meme_manager_config.json" "$DATA/config/meme_manager_config.json"
  echo "  [ok] 配置已放置"
fi

echo ""
echo "== 部署后统计 =="
echo -n "  插件文件数: "; find "$DATA/plugins/meme_manager" -type f | wc -l
echo -n "  表情包文件: "; find "$DATA/plugin_data/meme_manager/packs" -type f 2>/dev/null | wc -l
du -sh "$DATA/plugin_data/meme_manager" 2>/dev/null | sed 's/^/  表情包体积: /'
