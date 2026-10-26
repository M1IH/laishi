#!/usr/bin/env bash
# 把上传的 .stage 内容放到 AstrBot 数据卷里（幂等，先备份后放）
#
# 关键点：知识插件在 **AstrBot 容器内**用 importlib 加载 knowledge_root 下的
# inject.py/query.py 和 sqlite 库，所以 knowledge 必须在挂载卷里，
# knowledge_root 要写**容器路径** /AstrBot/data/knowledge，不能写宿主机路径。
set -euo pipefail

APP=/opt/miruku
STAGE=$APP/laishi            # .stage.tgz 解包位置
DATA=$APP/astrbot/data       # 挂载进容器 = /AstrBot/data
TS=$(date +%Y%m%d-%H%M%S)
BAK=$APP/backup/assemble-$TS

echo "[assemble] 阶段：$(ls $STAGE)"

# 1) 已有内容先备份（第一次跑时目录基本是空的）
mkdir -p "$BAK"
if [ -f "$DATA/cmd_config.json" ]; then
  cp -a "$DATA/cmd_config.json" "$BAK/cmd_config.json.orig"
fi
if [ -d "$DATA/config" ] && [ -n "$(ls -A "$DATA/config" 2>/dev/null)" ]; then
  cp -a "$DATA/config" "$BAK/config.orig"
fi

# 2) 知识目录整包进卷
rm -rf "$DATA/knowledge.new"
cp -a "$STAGE/knowledge" "$DATA/knowledge.new"
rm -rf "$DATA/knowledge"
mv "$DATA/knowledge.new" "$DATA/knowledge"
rm -f "$DATA/knowledge"/*.bak_* "$DATA/knowledge"/*.ds03bak 2>/dev/null || true

# 3) 项目侧文件（提示词/人格/切换脚本）也放卷里，方便容器内跑脚本
mkdir -p "$DATA/laishi"
cp -a "$STAGE/system.txt" "$STAGE/persona" "$STAGE/proactive_targets.local.json" \
      "$STAGE/switch_proactive_recipient.py" "$STAGE/set_proactive_opener.py" "$DATA/laishi/" 2>/dev/null || true

# 4) 自研插件 + proactive 插件：先只放目录，plugins.json 交给 AstrBot 自己扫
for p in astrbot_plugin_proactive_chat astrbot_plugin_miruku_knowledge \
         astrbot_plugin_miruku_context_guard astrbot_plugin_miruku_observer; do
  if [ -d "$STAGE/plugins/$p" ]; then
    rm -rf "$DATA/plugins/$p"
    cp -a "$STAGE/plugins/$p" "$DATA/plugins/$p"
    echo "[assemble] plugin ok: $p"
  else
    echo "[assemble] 缺插件: $p"
  fi
done

# 5) 配置与库
mkdir -p "$DATA/config" "$DATA/plugins"
cp -a "$STAGE/config/"*.json "$DATA/config/"
[ -f "$DATA/config/astrbot_plugin_proactive_chat_config.json" ] || { echo "[FAIL] 主动插件配置没落盘"; exit 1; }
cp -a "$STAGE/cmd_config.json" "$DATA/cmd_config.json"
# 会话历史快照（assemble.sh 每次跑都会重新复制，保证与本机一致）
cp -a "$STAGE/data_v4.db" "$DATA/data_v4.db"
rm -f "$DATA/data_v4.db-wal" "$DATA/data_v4.db-shm"   # 快照已 checkpoint，多余

echo "[assemble] 备份在 $BAK"
du -sh "$DATA" 2>/dev/null || true
