#!/usr/bin/env bash
# 表情包「选中了但发不出去」的包层诊断（服务器 root，只读）
# 用法: bash diag-meme-pack.sh
# 核心问题：绑定的包里有这个分类的目录，但目录里没有图 → 选得出、发不出、且不打日志。
DATA=/opt/miruku/astrbot/data
PD=$DATA/plugin_data/meme_manager
FAILED=0

say() { printf '\n===== %s =====\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; FAILED=1; }
ok()  { printf '  [PASS] %s\n' "$1"; }

say "1. 所有已装包 × 分类 × 图片数（0 张 = 选得中发不出）"
if [ -d "$PD/packs" ]; then
  for p in "$PD"/packs/*/; do
    [ -d "$p" ] || continue
    pid=$(basename "$p")
    total=$(find "$p/memes" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.gif' -o -iname '*.webp' \) 2>/dev/null | wc -l)
    printf '  --- %s  总图 %s 张\n' "$pid" "$total"
    if [ -d "$p/memes" ]; then
      for c in "$p"/memes/*/; do
        [ -d "$c" ] || continue
        n=$(find "$c" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.gif' -o -iname '*.webp' \) | wc -l)
        if [ "$n" -eq 0 ]; then
          printf '      [空] %-12s 0 张\n' "$(basename "$c")"
        else
          printf '           %-12s %s 张\n' "$(basename "$c")" "$n"
        fi
      done
    else
      printf '      [空] 没有 memes 目录\n'
    fi
  done
else
  bad "packs 目录不存在"
fi

say "2. 选包规则与注册表（决定运行时到底读哪个包）"
for f in registry.json selection_rules.json; do
  if [ -f "$PD/$f" ]; then
    echo "  --- $f"
    python3 -c "
import json,sys
d=json.load(open('$PD/$f',encoding='utf-8'))
print(json.dumps(d,ensure_ascii=False,indent=2))
" | sed 's/^/  /'
  else
    bad "缺 $f（插件启动时会重建，等于永远用 builtin-default）"
  fi
done

say "3. 复算插件会选哪个包"
python3 - "$PD" <<'PY'
import json,os,sys
pd=sys.argv[1]
def L(n,d):
    try: return json.load(open(os.path.join(pd,n),encoding='utf-8'))
    except Exception: return d
sel=L('selection_rules.json',{}); reg=L('registry.json',{})
rules=sel.get('rules',[]) if isinstance(sel,dict) else []
inst={str(p.get('id')):bool(p.get('enabled',True)) for p in reg.get('installed_packs',[]) if isinstance(p,dict)}
def exists(i): return os.path.isdir(os.path.join(pd,'packs',i))
def norm(v):
    if isinstance(v,str): return [v.strip()] if v.strip() else []
    if isinstance(v,list): return [str(x).strip() for x in v if str(x).strip()]
    return []
default=[];sess=[];pers=[]
for r in rules:
    if not isinstance(r,dict): continue
    ids=norm(r.get('pack_ids') or r.get('pack_id'))
    if not ids: continue
    sc=str(r.get('scope') or '').lower()
    if sc=='default': default=ids;continue
    ok=[i for i in ids if exists(i) and inst.get(i)]
    if sc=='session' and ok: sess.append((r.get('target'),ok))
    if sc=='persona' and ok: pers.append((r.get('target'),ok))
print("  default 规则指向:",default or "(无 → fallback builtin-default)")
print("  session 规则:",sess or "无")
print("  persona 规则:",pers or "无")
def img_count(pid,cat=None):
    base=os.path.join(pd,'packs',pid,'memes')
    if cat: base=os.path.join(base,cat)
    if not os.path.isdir(base): return -1
    n=0
    for root,_,files in os.walk(base):
        n+=sum(1 for f in files if f.lower().endswith(('.jpg','.jpeg','.png','.gif','.webp')))
    return n
chosen=default or ['builtin-default']
for pid in chosen:
    if not exists(pid): print(f"  [FAIL] {pid} 目录不存在"); continue
    if not inst.get(pid,False): print(f"  [FAIL] {pid} 未在 registry 里 enabled → 会被跳过")
    t=img_count(pid)
    if t<=0: print(f"  [FAIL] 运行时包 {pid} 总图 {t} → 任何分类都发不出（这就是零表情的根因）")
    else: print(f"  [PASS] 运行时包 {pid} 总图 {t} 张")
PY

say "4. 最近选中的分类，在运行时包里有没有图"
python3 - "$PD" <<'PY'
import json,os,re,subprocess,sys
pd=sys.argv[1]
logs=''
try:
    r=subprocess.run(['docker','logs','astrbot','--since','24h'],capture_output=True,text=True,errors='replace')
    logs=(r.stdout or '')+(r.stderr or '')
except Exception as e:
    print("  [WARN] 取日志失败:",e)
sel=[]
for m in re.finditer(r"情感模型选择标签:\s*(\[[^\]]*\])",logs):
    try: sel.extend([x for x in eval(m.group(1)) if isinstance(x,str)])
    except Exception: pass
sel=sorted(set(sel))
print("  24h 内选过的分类:",sel or "无")
try: reg=json.load(open(os.path.join(pd,'registry.json'),encoding='utf-8'))
except Exception: reg={}
try: sr=json.load(open(os.path.join(pd,'selection_rules.json'),encoding='utf-8'))
except Exception: sr={}
pid='builtin-default'
for r in (sr.get('rules') or []):
    if isinstance(r,dict) and str(r.get('scope'))=='default':
        v=r.get('pack_ids') or r.get('pack_id')
        if isinstance(v,str) and v.strip(): pid=v.strip()
        elif isinstance(v,list) and v: pid=str(v[0])
missing=[]
for c in sel:
    d=os.path.join(pd,'packs',pid,'memes',c)
    n=len([f for f in os.listdir(d)]) if os.path.isdir(d) else 0
    flag="OK" if n>0 else "无图"
    print(f"    {c:<12} 在 {pid} 里 {n} 项 → {flag}")
    if n==0: missing.append(c)
print("  无图分类:",missing or "无")
if missing: print("  → 这些分类被选中也只会静默跳过，是零表情的直接原因之一")
PY

say "5. 语义检索状态（描述没完成就不建向量，但这条不影响 legacy 出图）"
docker logs astrbot --since 24h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'meme_manager.*语义|builtin-default 的图片描述' | tail -4 | sed 's/^/  /'

echo
[ "$FAILED" -eq 0 ] && echo "  包层没有 FAIL：若仍零表情，问题在发送阶段（看 _on_decorating_result 是否被 streaming/mixed 分支吞掉）" || echo "  有 FAIL：按上面修，最省事是把 default 规则指向有图的包"
