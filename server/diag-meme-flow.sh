#!/usr/bin/env bash
# 表情包一条都不发的分层诊断（在服务器上以 root 执行，只读）
# 用法: bash diag-meme-flow.sh
# 输出每一层 PASS/FAIL，FAIL 的第一层就是根因所在层。
DATA=/opt/miruku/astrbot/data
CFG=$DATA/config/meme_manager_config.json
PACK=$DATA/plugin_data/meme_manager/packs/juxueli-meme-pack
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

say() { printf '\n===== %s =====\n' "$1"; }
ok()   { printf '  [PASS] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; FAILED=1; }
warn() { printf '  [WARN] %s\n' "$1"; }
FAILED=0

say "0. 容器"
docker inspect astrbot --format '  status={{.State.Status}} started={{.State.StartedAt}}' 2>/dev/null || bad "容器 astrbot 不存在"

say "1. 插件本体是否在、是否被 AstrBot 加载"
if [ -f "$DATA/plugins/meme_manager/main.py" ]; then
  ok "插件目录存在，文件数 $(find "$DATA/plugins/meme_manager" -type f | wc -l)"
  printf '  version: '; grep -m1 -oE '"version"\s*:\s*"[^"]+"' "$DATA/plugins/meme_manager/metadata.yaml" 2>/dev/null || grep -m1 -oE 'version\s*=\s*"[^"]+"' "$DATA/plugins/meme_manager/main.py" 2>/dev/null || echo "(未知)"
else
  bad "插件目录缺失 $DATA/plugins/meme_manager"
fi
echo "  --- 最近的插件加载日志 ---"
docker logs astrbot 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme_manager' | grep -iE '加载|载入|load|注册|失败|Error|Traceback' | tail -12 | sed 's/^/  /'
if docker logs astrbot 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -qiE 'meme_manager.*(导入|import).*(失败|error)'; then
  bad "插件导入失败（见上面 Traceback）"
fi

say "1b. AstrBot 是否支持插件依赖的钩子（不支持则整个插件 import 失败）"
docker exec astrbot python -c "
from astrbot.core import filter as f
for n in ['on_waiting_llm_request','on_llm_request','on_llm_response','on_decorating_result','after_message_sent']:
    print('  ', n, '=', hasattr(f,n))
" 2>&1 | sed 's/^/  /' || warn "docker exec 失败，跳过"

say "1c. 版本账：插件要求的 AstrBot 版本 vs 实际装的"
REQ=$(grep -m1 -oE 'astrbot_version:\s*"[^"]+"' "$DATA/plugins/meme_manager/metadata.yaml" 2>/dev/null | sed 's/.*"\(.*\)"/\1/')
echo "  插件 metadata 要求: ${REQ:-未知}"
VER=$(docker exec astrbot python -c "import astrbot;print(getattr(astrbot,'__version__',''))" 2>/dev/null | tr -d '\r')
[ -z "$VER" ] && VER=$(docker exec astrbot sh -c "pip show astrbot 2>/dev/null | grep -i '^Version:' | cut -d' ' -f2" 2>/dev/null | tr -d '\r')
echo "  容器内 AstrBot 实际: ${VER:-取不到}"
if [ -n "$VER" ] && [ -n "$REQ" ]; then
  python3 - "$VER" "$REQ" <<'PY'
import re,sys
v,r=sys.argv[1],sys.argv[2]
def tup(s):
    return tuple(int(x) for x in re.findall(r'\d+',s)[:3])
a,b=tup(v),tup(r)
if a and b:
    print("  [PASS] 版本满足" if a>=b else f"  [FAIL] AstrBot {v} < 插件要求 {r} → 插件可能 import 失败/钩子缺失")
PY
fi

say "2. 生效配置（线上真实值，不是 stage 里的）"
python3 - "$CFG" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,encoding='utf-8-sig'))
except Exception as e:
    print("  [FAIL] 配置读取失败:",e); raise SystemExit(0)
g=d.get('generation',{})
e=g.get('emotion',{}) or {}
llm=e.get('llm',{}) or {}
tr=g.get('trigger',{}) or {}
msg=g.get('message',{}) or {}
pr=g.get('prompt',{}) or {}
se=d.get('semantic',{}) or {}
print("  probability            =",e.get('probability'))
print("  max_memes_per_message  =",e.get('max_memes_per_message'))
print("  emotion.llm.enabled    =",llm.get('enabled'))
print("  emotion.llm.provider_id=",repr(llm.get('provider_id')))
print("  emotion.llm.model      =",repr(llm.get('model')))
print("  emotion.llm.ctx_turns  =",llm.get('context_turns'))
print("  trigger.scope          =",tr.get('scope'))
print("  message.enable_mixed   =",msg.get('enable_mixed'),"mixed_probability =",msg.get('mixed_probability'))
print("  prompt.quantity_guidance_enabled =",pr.get('quantity_guidance_enabled'))
print("  semantic.enabled       =",se.get('enabled'),"embedding_provider_id =",repr(se.get('embedding_provider_id')))
PY

say "3. 情感模型 provider 是否真实存在（SPOF 检查）"
python3 - "$DATA" <<'PY'
import json,os,glob,sys
data=sys.argv[1]
cfg=json.load(open(os.path.join(data,'config','meme_manager_config.json'),encoding='utf-8-sig'))
pid=((cfg.get('generation',{}).get('emotion',{}) or {}).get('llm',{}) or {}).get('provider_id') or ''
cands=[os.path.join(data,'cmd_config.json'),os.path.join(data,'config','cmd_config.json')]
pc=None
for c in cands:
    if os.path.isfile(c): pc=c;break
if not pc:
    print("  [WARN] 找不到 AstrBot 主配置 cmd_config.json，跳过 provider 存在性检查")
    raise SystemExit(0)
ac=json.load(open(pc,encoding='utf-8-sig'))
ps=((ac.get('provider_settings') or ac.get('provider') or {}).get('providers')) or []
ids=[]
for p in ps:
    i=p.get('id') or ''
    if i: ids.append(i)
    t=p.get('type','')
    m=(p.get('model_config') or {}).get('model') or ''
    if t and m: ids.append(f"{t}/{m}")
print("  AstrBot 已注册 provider 形态:", sorted(set(ids))[:20])
if not pid:
    print("  [PASS] provider_id 为空 → 复用当前回复 provider，无单点")
elif pid in ids or pid.split('/')[0] in {x.split('/')[0] for x in ids}:
    print(f"  [PASS] {pid} 可解析")
else:
    print(f"  [FAIL] {pid} 在 AstrBot 里不存在 → 情感模型每次调用都会失败 → 永远零表情")
PY

say "4. 表情包分类目录与图片数（0 张 = 该分类永远发不出）"
if [ -d "$PACK" ]; then
  for d in "$PACK"/memes/*/; do
    [ -d "$d" ] || continue
    n=$(find "$d" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.gif' -o -iname '*.webp' \) | wc -l)
    name=$(basename "$d")
    if [ "$n" -eq 0 ]; then bad "分类 $name 有目录但 0 张图"; else printf '  [PASS] %-12s %s 张\n' "$name" "$n"; fi
  done
  echo "  --- 包内 memes_data.json 的分类 vs 目录 ---"
  python3 - "$PACK" <<'PY'
import json,os,sys
p=sys.argv[1]
f=os.path.join(p,'memes_data.json')
if not os.path.isfile(f):
    print("  [FAIL] 缺 memes_data.json"); raise SystemExit(0)
d=json.load(open(f,encoding='utf-8-sig'))
dirs={x for x in os.listdir(os.path.join(p,'memes')) if os.path.isdir(os.path.join(p,'memes',x))} if os.path.isdir(os.path.join(p,'memes')) else set()
keys=set(d.keys())
print("  catalog 分类:",sorted(keys))
print("  有目录无描述:",sorted(dirs-keys) or "无")
print("  有描述无目录:",sorted(keys-dirs) or "无")
PY
else
  bad "包目录缺失 $PACK"
fi

say "5. 关键日志：卡在哪一环"
L() { docker logs astrbot --since "${2:-24h}" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -F "$1"; }
for k in "情感模型选择标签" "情感模型未选择有效标签" "情感模型调用失败" "去重后的最终表情列表"; do
  n=$(L "$k" | wc -l)
  printf '  %-24s %s 条\n' "$k" "$n"
  L "$k" | tail -3 | sed 's/^/      /'
done
echo "  --- 表情相关最近 10 行（去掉 DEPRECATION） ---"
docker logs astrbot --since 24h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme' | grep -viE 'DEPRECATION' | tail -10 | sed 's/^/  /'

say "判定"
TOTAL=$(docker logs astrbot --since 24h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -cF "[meme_manager]" || true)
echo "  24h 内 [meme_manager] 日志总条数 = $TOTAL"
if [ "${TOTAL:-0}" -eq 0 ]; then
  echo "  [FAIL] 插件完全没跑过：不是概率问题，是 origin/scope 闸门或插件未加载"
  echo "         三条可能：①on_waiting_llm_request 没生效 → origin=None → 全部早退；"
  echo "                  ②scope 不是 chat/chat_and_plugin_llm；③插件 import 失败（看第 1 节）"
fi
python3 - "$CFG" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8-sig'))
g=d.get('generation',{}); e=g.get('emotion',{}) or {}; llm=e.get('llm',{}) or {}
prob=int(e.get('probability') or 0)
print("  概率闸门 =",prob, "→", "恒开" if prob>=100 else f"每条回复只有 {prob}% 才进入情感判定")
if prob==0: print("  [FAIL] 概率 0，永远不发")
if not llm.get('enabled'): print("  情感模型关闭 → 依赖回复模型自己打 &&tag&&（需要 prompt 注入成功）")
PY
[ "$FAILED" -eq 0 ] && echo "  上面没有 FAIL 层 → 卡点在第 5 步日志里，按最后出现的那个环节定位" || echo "  有 FAIL 层 → 先修最上面那个 FAIL"
echo
