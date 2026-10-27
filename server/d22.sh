#!/usr/bin/env bash
echo "== 重启 astrbot =="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 20); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done

echo ""
echo "== 包识别情况 =="
docker logs astrbot --since 3m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme_manager|pack|分类|memes_data|juxueli' | grep -viE 'DEPRECATION|pip install' | tail -12

echo ""
echo "== memes_data.json 现在有内容了吗 =="
python3 - <<'PY'
import json
p = "/opt/miruku/astrbot/data/plugin_data/meme_manager/packs/juxueli-meme-pack/memes_data.json"
d = json.load(open(p, encoding="utf-8"))
if isinstance(d, dict):
    print("  顶层键:", list(d))
    for k in ("memes", "items", "categories", "category"):
        v = d.get(k)
        if isinstance(v, (list, dict)):
            print(f"  {k}: {len(v)} 项")
            if isinstance(v, dict) and v:
                print("    样例:", list(v)[:10])
            elif isinstance(v, list) and v:
                print("    样例:", str(v[0])[:150])
else:
    print("  list, ", len(d), "条")
PY
