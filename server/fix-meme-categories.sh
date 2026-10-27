#!/usr/bin/env bash
# 把自定义分类目录改名对齐到插件标准标签，让情感模型输出能命中
# 依据：config.py 的 DEFAULT_CATEGORY_DESCRIPTIONS（angry/happy/sad/surprised/
# confused/color/cpu/fool/givemoney/like/see/shy/work/reply/meow/baka/morning/sleep/sigh）
set -euo pipefail
PACK=/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack
TS=$(date +%Y%m%d-%H%M%S)
BAK=/opt/miruku/backup/meme-cats-$TS

echo "== 备份 =="
mkdir -p "$BAK"
cp -a "$PACK/memes" "$BAK/memes"
cp -a "$PACK/memes_data.json" "$BAK/memes_data.json"
echo "  -> $BAK"

# 自定义 -> 标准；同义合并（food/interaction 归到最接近的标准标签）
declare -A MAP=(
  [happy]=happy
  [approval]=like
  [question]=confused
  [surprised]=surprised
  [apology]=sad
  [attack]=baka
  [surrender]=sigh
  [food]=like
  [shy]=shy
  [interaction]=reply
)

echo ""
echo "== 改名（同义合并到同一目录）=="
for old in "${!MAP[@]}"; do
  new=${MAP[$old]}
  src="$PACK/memes/$old"
  dst="$PACK/memes/$new"
  [ -d "$src" ] || { echo "  跳过 $old（不存在）"; continue; }
  if [ "$old" = "$new" ]; then
    echo "  $old 已是标准名，不动"
    continue
  fi
  mkdir -p "$dst"
  # 移动图片并加前缀避免重名
  n=0
  for f in "$src"/*; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    if [ -e "$dst/${old}_$base" ]; then
      base="${base%.*}_$RANDOM.${base##*.}"
    fi
    mv "$f" "$dst/${old}_$base"
    n=$((n+1))
  done
  rmdir "$src" 2>/dev/null || true
  echo "  $old -> $new  (移动 $n 张)"
done

echo ""
echo "== 结果：各标准分类图片数 =="
for d in "$PACK"/memes/*/; do
  [ -d "$d" ] || continue
  n=$(find "$d" -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.gif' -o -name '*.webp' \) | wc -l)
  echo "  $(basename "$d"): $n"
done
echo -n "  总计: "
find "$PACK/memes" -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.gif' -o -name '*.webp' \) | wc -l

echo ""
echo "== 重写 memes_data.json（用标准标签 + 原描述要点）=="
python3 - <<'PY'
import json, os
pack = "/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack"
path = os.path.join(pack, "memes_data.json")
old = json.load(open(path, encoding="utf-8"))

# 标准标签的说明（取自插件 config.py，稍作口语化）
STD = {
    "happy": "开心、轻松回应、心情好、活跃气氛",
    "like": "点赞、夸赞、认可对方、表达喜爱",
    "confused": "疑惑、没听懂、反问、对离谱内容吐槽",
    "surprised": "吃惊、震撼、意外",
    "sad": "道歉、安慰、遗憾、遇到挫折",
    "baka": "玩笑式吐槽、轻微责备、夸张威胁（不可用于严肃冲突）",
    "sigh": "无奈、无语、放弃、感慨",
    "shy": "害羞、被夸、涉及隐私话题",
    "reply": "等待回应、互动、需要确认",
}
new = {}
for cat in sorted(os.listdir(os.path.join(pack, "memes"))):
    d = os.path.join(pack, "memes", cat)
    if not os.path.isdir(d):
        continue
    has = any(os.path.splitext(f)[1].lower() in (".jpg",".png",".gif",".webp")
              for f in os.listdir(d))
    if not has:
        continue
    new[cat] = STD.get(cat, old.get(cat, cat))

json.dump(new, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  写入分类:", list(new))
PY
