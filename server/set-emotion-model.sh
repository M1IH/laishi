#!/usr/bin/env bash
set -e
echo "== 把情感判断模型切到小米 =="
python3 - <<'PY'
import json
p = "/opt/miruku/astrbot/data/config/meme_manager_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
e = d["generation"]["emotion"]["llm"]
before = e.get("provider_id")
e["provider_id"] = "xiaomi/mimo-v2.6-flash"
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  provider_id:", before, "->", e["provider_id"])
print("  enabled:", e.get("enabled"), "| context_turns:", e.get("context_turns"))
PY

echo ""
echo "== 重启 astrbot 生效 =="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 20); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done

echo ""
echo "== 确认加载无报错 =="
docker logs astrbot --since 2m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme_manager|xiaomi|provider' | grep -viE 'DEPRECATION' | tail -8
