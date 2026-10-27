#!/usr/bin/env bash
# 表情包「选得出、发不出」第二层诊断：只读，不改任何文件
# 目的：切到 juxueli-meme-pack 后仍零出图 → 区分「没尝试发」和「发了被 QQ 拒」
set -u
DATA=/opt/miruku/astrbot/data
PD="$DATA/plugin_data/meme_manager"
SINCE="${1:-40m}"

hr() { echo ""; echo "===== $* ====="; }

hr "A. 选包规则回读（确认上次的修复还在）"
python3 - "$PD" <<'PY'
import json, os, sys
pd = sys.argv[1]
def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8-sig"))
    except Exception as e:
        print(f"  [WARN] {os.path.basename(p)} 读取失败: {e}")
        return d
reg = load(os.path.join(pd, "registry.json"), {})
rules = load(os.path.join(pd, "selection_rules.json"), {})
for p in reg.get("installed_packs", []):
    print(f"  pack {p.get('id'):24s} enabled={p.get('enabled')}")
for r in rules.get("rules", []):
    print(f"  rule {r.get('id'):10s} scope={r.get('scope'):10s} pack={r.get('pack_id')}")
PY

hr "B. 发送阶段相关配置（注意：这些是插件 init 时读的，改了必须重启）"
python3 - "$DATA/config/meme_manager_config.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8-sig"))
g = d.get("generation", {})
m = g.get("message", {}) or {}
e = g.get("emotion", {}) or {}
t = g.get("trigger", {}) or {}
for k in ("enable_mixed", "mixed_probability",
          "streaming_compatibility", "send_image_as_base64",
          "convert_static_to_gif", "content_cleanup_rule"):
    print(f"  message.{k:28s} = {m.get(k)!r}")
print(f"  message 全部键                   = {sorted(m)}")
print(f"  emotion.probability              = {e.get('probability')!r}")
print(f"  emotion.max_memes_per_message    = {e.get('max_memes_per_message')!r}")
print(f"  emotion.llm.enabled              = {(e.get('llm') or {}).get('enabled')!r}")
print(f"  trigger.scope                    = {t.get('scope')!r}")
PY

hr "C. 最近 $SINCE 的 meme_manager 原始日志（末 45 行，不过滤）"
docker logs astrbot --since "$SINCE" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -F "meme_manager" | tail -45

hr "D. 最近 $SINCE 里和表情有关的异常"
docker logs astrbot --since "$SINCE" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE '处理消息装饰失败|添加表情图片失败|表情|meme' \
  | grep -iE 'ERROR|WARN|Traceback|失败|异常|Exception' | tail -20

hr "E. NapCat 侧：QQ 到底有没有收到图片段（关键判据）"
NAPCAT=$(docker ps --format '{{.Names}}' | grep -iE 'napcat|qq' | head -1)
if [ -z "$NAPCAT" ]; then
  echo "  [WARN] 没找到 napcat/qq 容器，列出全部容器："
  docker ps --format '  {{.Names}}\t{{.Image}}'
else
  echo "  容器: $NAPCAT"
  docker logs "$NAPCAT" --since "$SINCE" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
    | grep -iE 'image|图片|pic|上传|upload|sendMsg|发送' | tail -30
fi

hr "F. 平台 / 流式开关（决定走 _send_memes_streaming 还是 decorating）"
grep -aoiE '"[a-z_]*stream[a-z_]*"[[:space:]]*:[[:space:]]*[a-z0-9"]+|"[a-z_]*streaming[a-z_]*"' \
  "$DATA/config"/*.json 2>/dev/null | sort -u | head -20
echo "  --- 平台适配器:"
python3 - "$DATA" <<'PY'
import glob, json, os, sys
for p in glob.glob(os.path.join(sys.argv[1], "config", "*.json")):
    try:
        d = json.load(open(p, encoding="utf-8-sig"))
    except Exception:
        continue
    if isinstance(d, dict) and ("platform" in d or "adapters" in d or "platforms" in d):
        print(f"  {os.path.basename(p)}: {json.dumps(d, ensure_ascii=False)[:400]}")
PY

hr "G. 插件日志级别（静默失败要靠 DEBUG 才看得见）"
docker logs astrbot --since "$SINCE" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'log level' | tail -5
echo "  --- 日志级别配置文件候选:"
ls -1 "$DATA/config" 2>/dev/null | grep -iE 'log|plugin_setting' | sed 's/^/    /'

hr "H. 包的分类清单 vs 磁盘目录（键对不上 = 选得中发不出，且无日志）"
python3 - "$PD" <<'PY'
import json, os, sys
pd = sys.argv[1]
base = os.path.join(pd, "packs")
for pid in sorted(os.listdir(base)) if os.path.isdir(base) else []:
    pdir = os.path.join(base, pid)
    if not os.path.isdir(pdir):
        continue
    mf = os.path.join(pdir, "memes_data.json")
    keys = []
    if os.path.isfile(mf):
        try:
            d = json.load(open(mf, encoding="utf-8-sig"))
            if isinstance(d, dict):
                keys = list(d.keys())
        except Exception as e:
            print(f"  [WARN] {pid}/memes_data.json 解析失败: {e}")
    memes_root = os.path.join(pdir, "memes")
    dirs = sorted(
        d for d in (os.listdir(memes_root) if os.path.isdir(memes_root) else [])
        if os.path.isdir(os.path.join(memes_root, d))
    )
    print(f"  --- {pid}")
    print(f"      memes_data.json 分类键 ({len(keys)}): {keys}")
    print(f"      磁盘 memes/ 子目录 ({len(dirs)}): {dirs}")
    only_key = [k for k in keys if k not in dirs]
    only_dir = [k for k in dirs if k not in keys]
    if only_key:
        print(f"      [FAIL] 有描述但无目录（选了必空）: {only_key}")
    if only_dir:
        print(f"      [WARN] 有目录但无描述（模型不会选）: {only_dir}")
PY
echo ""
echo "结论怎么看："
echo "  · C 里有『情感模型选择标签』但 E 里没有任何 image → 插件没把图交出去（看 D 有无异常）"
echo "  · C 有标签 且 E 有 image 段 → 图发到了 QQ，问题在显示侧/被折叠"
echo "  · C 里连『情感模型选择标签』都没有 → 说明这些消息根本没走聊天 LLM 钩子（来源问题）"
