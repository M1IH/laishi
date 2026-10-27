#!/usr/bin/env bash
echo "== 语义检索配置（决定 AI 能否按语境挑表情）=="
python3 - <<'PY'
import json
p = "/opt/miruku/astrbot/data/config/meme_manager_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
sem = d.get("semantic", {})
print("  enabled            =", sem.get("enabled"))
print("  min_score          =", sem.get("min_score"))
print("  top_k              =", sem.get("top_k"))
print("  embedding_provider =", repr(sem.get("embedding_provider_id")))
print("  vision_provider    =", repr(sem.get("vision_provider_id")))
print("  auto_collect       =", (d.get("auto_collect") or {}).get("enabled"))
PY

echo ""
echo "== 语义索引构建结果（关键：没索引就只能靠关键词）=="
docker logs astrbot --since 8m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'semantic|索引|index|embedding' | grep -viE 'DEPRECATION|pip install' | tail -8 || echo "  （无索引日志）"

echo ""
echo "== 系统里可用的 embedding provider =="
curl -s --max-time 8 http://127.0.0.1:6185/api/v1/providers 2>/dev/null | head -c 300; echo
echo ""
echo "== 索引目录 =="
ls -la /opt/miruku/astrbot/data/plugin_data/meme_manager/semantic_indexes/ 2>/dev/null
