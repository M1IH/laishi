#!/usr/bin/env bash
# 把表情绑定切到「有图的包」（服务器 root）。规则文件每条消息现读，无需重启。
# 用法: bash fix-meme-pack.sh [PACK_ID]     默认 juxueli-meme-pack
#       bash fix-meme-pack.sh --list        只列出候选包与图片数
set -e
DATA=/opt/miruku/astrbot/data
PD=$DATA/plugin_data/meme_manager
PACK=${1:-juxueli-meme-pack}

count_imgs() {
  find "$1" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.gif' -o -iname '*.webp' \) 2>/dev/null | wc -l
}

if [ "$PACK" = "--list" ]; then
  echo "== 候选包 =="
  for p in "$PD"/packs/*/; do
    [ -d "$p" ] || continue
    printf '  %-24s %s 张\n' "$(basename "$p")" "$(count_imgs "$p/memes")"
  done
  exit 0
fi

[ -d "$PD/packs/$PACK" ] || { echo "包不存在: $PD/packs/$PACK"; echo "先跑 --list 看有哪些"; exit 1; }
N=$(count_imgs "$PD/packs/$PACK/memes")
[ "$N" -gt 0 ] || { echo "包 $PACK 的 memes 里 0 张图，换一个"; exit 1; }
echo "目标包: $PACK（$N 张图）"

[ -f "$PD/registry.json" ] && cp -a "$PD/registry.json" "$PD/registry.json.bak.$(date +%Y%m%d-%H%M%S)"
[ -f "$PD/selection_rules.json" ] && cp -a "$PD/selection_rules.json" "$PD/selection_rules.json.bak.$(date +%Y%m%d-%H%M%S)"
echo "已备份 registry.json / selection_rules.json"

python3 - "$PD" "$PACK" <<'PY'
import json,os,sys,datetime
pd,pid=sys.argv[1],sys.argv[2]
REG=os.path.join(pd,'registry.json'); SEL=os.path.join(pd,'selection_rules.json')
def load(p,d):
    try:
        with open(p,encoding='utf-8') as f: return json.load(f)
    except Exception: return d
def save(p,d):
    with open(p,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2)

reg=load(REG,{"schema_version":1,"installed_packs":[]})
if not isinstance(reg,dict): reg={"schema_version":1,"installed_packs":[]}
inst=reg.setdefault('installed_packs',[])
hit=None
for p in inst:
    if isinstance(p,dict) and str(p.get('id'))==pid: hit=p;break
if hit is None:
    inst.append({"id":pid,"name":pid,"version":"1.0.0","enabled":True,
                 "installed_at":datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print(f"  registry: 新增 {pid} 并 enabled")
elif not hit.get('enabled',True):
    hit['enabled']=True; print(f"  registry: {pid} 置 enabled")
else:
    print(f"  registry: {pid} 已 enabled")
save(REG,reg)

sel=load(SEL,{"schema_version":1,"rules":[]})
if not isinstance(sel,dict): sel={"schema_version":1,"rules":[]}
rules=sel.setdefault('rules',[])
done=False
for r in rules:
    if isinstance(r,dict) and str(r.get('scope'))=='default':
        old=r.get('pack_id') or r.get('pack_ids')
        r['pack_id']=pid; r.pop('pack_ids',None)
        print(f"  selection_rules: default {old!r} -> {pid!r}")
        done=True
        break
if not done:
    rules.append({"id":"default","scope":"default","pack_id":pid})
    print(f"  selection_rules: 新建 default -> {pid!r}")
save(SEL,sel)

# 回读确认
reg2=load(REG,{}); sel2=load(SEL,{})
print("  回读 default =", [r.get('pack_id') for r in sel2.get('rules',[]) if isinstance(r,dict) and r.get('scope')=='default'])
print("  回读 enabled =", [p.get('id') for p in reg2.get('installed_packs',[]) if isinstance(p,dict) and p.get('enabled',True)])
PY

echo ""
echo "== 包内分类（模型现在只会在这些里选）=="
for c in "$PD/packs/$PACK"/memes/*/; do
  [ -d "$c" ] || continue
  printf '  %-12s %s 张\n' "$(basename "$c")" "$(count_imgs "$c")"
done

cat <<EOF

规则文件是每条消息现读的，**不用重启**。
下一步：在 QQ 里聊 4~6 条，然后
  bash diag-meme-flow.sh | tail -20     # 看情感模型选了什么分类
  bash diag-meme-pack.sh                # 确认选的分类在 $PACK 里有图
若仍零表情，把 diag-meme-pack.sh 完整输出贴回。
EOF
