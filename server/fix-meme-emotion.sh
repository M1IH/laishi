#!/usr/bin/env bash
# 修「情感模型调用失败 401」导致的零表情
# 背景：generation.emotion.llm.provider_id 曾指向 xiaomi/mimo-v2.6-flash，
#       该 key 已失效（api.xiaomimimo.com 返回 invalid_key 401），
#       情感模型每次调用都失败 → 选择标签为空 → 去重后的最终表情列表: [] → 一条表情都不发。
# 处置：情感模型改用已验证可用的会话 provider（deepseek），不依赖额外 key；概率提到 90 便于观察。
# 注意：provider_id / probability 是插件 init 时读取（meme_manager/main.py:240-255），必须重启。
set -e
CFG=/opt/miruku/astrbot/data/config/meme_manager_config.json
PROVIDER="${1:-deepseek/deepseek-flash}"
PROB="${2:-90}"

python3 - "$CFG" "$PROVIDER" "$PROB" <<'PY'
import json, shutil, sys
p, provider, prob = sys.argv[1], sys.argv[2], int(sys.argv[3])
d = json.load(open(p, encoding="utf-8-sig"))
g = d.setdefault("generation", {})
e = g.setdefault("emotion", {})
llm = e.setdefault("llm", {})
before = (llm.get("provider_id"), e.get("probability"), e.get("max_memes_per_message"))
shutil.copy2(p, p + ".bak.emotion")
llm["provider_id"] = provider
e["probability"] = prob
e["max_memes_per_message"] = 1
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
after = (llm.get("provider_id"), e.get("probability"), e.get("max_memes_per_message"))
print(f"  provider_id : {before[0]!r} -> {after[0]!r}")
print(f"  probability : {before[1]!r} -> {after[1]!r}")
print(f"  max_memes   : {before[2]!r} -> {after[2]!r}")
print(f"  备份        : {p}.bak.emotion")
PY

echo ""
echo "== 重启 astrbot（provider_id 只在插件 init 时读取）=="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 24); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done

echo ""
echo "== 回读生效值 =="
python3 - "$CFG" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8-sig"))
e = d["generation"]["emotion"]
print(f"  provider_id={e['llm'].get('provider_id')!r} probability={e.get('probability')} max={e.get('max_memes_per_message')}")
PY
echo ""
echo "下一步：QQ 里聊 2~3 条，然后看日志是否还有 401："
echo "  docker logs astrbot --since 3m 2>&1 | grep -E '情感模型|最终表情列表' | tail -10"
