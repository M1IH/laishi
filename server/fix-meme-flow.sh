#!/usr/bin/env bash
# 修表情包触发率（在服务器上以 root 执行）
# 用法:
#   bash fix-meme-flow.sh              # 默认：概率拉满 + 情感模型复用回复 provider + 打开频率指导
#   bash fix-meme-flow.sh --force      # 强制把 provider_id 清空（即使能解析到）
#   bash fix-meme-flow.sh --from-tags  # 关掉情感模型，改由回复模型自己打 &&tag&&（情感模型一直失败的兜底）
set -e
DATA=/opt/miruku/astrbot/data
CFG=$DATA/config/meme_manager_config.json
MODE=${1:-}

[ -f "$CFG" ] || { echo "找不到 $CFG"; exit 1; }
cp -a "$CFG" "$CFG.bak.$(date +%Y%m%d-%H%M%S)"
echo "已备份: $CFG.bak.*"

python3 - "$DATA" "$MODE" <<'PY'
import json,os,sys
data,mode=sys.argv[1],sys.argv[2]
p=os.path.join(data,'config','meme_manager_config.json')
d=json.load(open(p,encoding='utf-8-sig'))
g=d.setdefault('generation',{})
e=g.setdefault('emotion',{})
llm=e.setdefault('llm',{})
pr=g.setdefault('prompt',{})

# 1) 概率闸门拉满：真正的节流交给 quantity_guidance（约 4 条 1 张）+ 情感模型的选择
before=e.get('probability')
e['probability']=100
e['max_memes_per_message']=1

# 2) 频率指导必须开，否则 100% 会变成每句都配图
pr['quantity_guidance_enabled']=True

# 3) 情感模型：消除 provider 单点
if mode=='--from-tags':
    llm['enabled']=False
    print("  情感模型: enabled=False（改为回复模型打 tag 模式）")
else:
    llm['enabled']=True
    pid=llm.get('provider_id') or ''
    ok=False
    for c in (os.path.join(data,'cmd_config.json'),os.path.join(data,'config','cmd_config.json')):
        if not os.path.isfile(c): continue
        ac=json.load(open(c,encoding='utf-8-sig'))
        ps=((ac.get('provider_settings') or ac.get('provider') or {}).get('providers')) or []
        ids=set()
        for x in ps:
            if x.get('id'): ids.add(x['id'])
            t=x.get('type',''); m=(x.get('model_config') or {}).get('model') or ''
            if t and m: ids.add(f"{t}/{m}")
        ok = pid in ids or (pid and pid.split('/')[0] in {i.split('/')[0] for i in ids})
        break
    if mode=='--force' or not ok:
        print(f"  provider_id: {pid!r} 不可解析 → 清空，复用回复 provider")
        llm['provider_id']=''
        llm.pop('model',None)
    else:
        print(f"  provider_id: {pid!r} 可解析，保留")

json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
print("  probability:",before,"->",e['probability'])
print("  quantity_guidance_enabled:",pr['quantity_guidance_enabled'])
print("  max_memes_per_message:",e['max_memes_per_message'])
PY

echo ""
echo "== 重启 astrbot =="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 24); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done

echo ""
echo "== 重启后回读 =="
python3 - "$CFG" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8-sig'))
e=d['generation']['emotion']; llm=e.get('llm',{})
print("  probability =",e.get('probability'),"| max_memes =",e.get('max_memes_per_message'))
print("  emotion.llm.enabled =",llm.get('enabled'),"| provider_id =",repr(llm.get('provider_id')))
print("  quantity_guidance =",d['generation'].get('prompt',{}).get('quantity_guidance_enabled'))
PY

echo ""
echo "== 最近插件日志 =="
docker logs astrbot --since 2m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'meme_manager' | grep -viE 'DEPRECATION' | tail -8 | sed 's/^/  /'

cat <<EOF

下一步：在 QQ 里连发 6~8 条，然后跑
  bash diag-meme-flow.sh
看第 5 节三条日志：
  - 完全没有「情感模型」字样  → 概率/scope 之前就被拦了，看第 2、3 层
  - 有「情感模型调用失败」    → provider 还是坏的，改用 --from-tags
  - 有「未选择有效标签」      → 模型判断"配图会歪曲原意"，属正常保守，继续聊几句再观察
  - 有「选择标签」但没有图    → 卡在第 4 节图片目录
EOF
