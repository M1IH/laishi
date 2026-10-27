#!/usr/bin/env bash
set -e
echo "== 提高表情触发概率 30 -> 65，并开启频率指导 =="
python3 - <<'PY'
import json
p = "/opt/miruku/astrbot/data/config/meme_manager_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
g = d.setdefault("generation", {})
e = g.setdefault("emotion", {})
before = e.get("probability")
e["probability"] = 65
e["max_memes_per_message"] = 1
pr = g.setdefault("prompt", {})
# 开启「每约 4 条回复配 1 张」的节奏指导，避免只有 30% 时才配图
pr["quantity_guidance_enabled"] = True
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  probability:", before, "->", e["probability"])
print("  quantity_guidance_enabled:", pr["quantity_guidance_enabled"])
print("  max_memes_per_message:", e["max_memes_per_message"])
PY

echo ""
echo "== 重启 astrbot 让新分类与配置生效 =="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 20); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done

echo ""
echo "== 插件识别到的分类 =="
docker logs astrbot --since 2m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme_manager' | grep -viE 'DEPRECATION' | tail -8
