#!/bin/bash
# 部署 anysearch 搜索结果截断（2026-10-31）
# 用法：把 server/patches/20261031-anysearch-truncate/ 下 5 个文件传到 /root/uploads/ 后执行
#   scp server/patches/20261031-anysearch-truncate/* root@HOST:/root/uploads/
#   ssh root@HOST "tr -d '\r' < /root/deploy-anysearch-truncate.sh > /root/d.sh && bash /root/d.sh"
set -uo pipefail

D=/AstrBot/data/plugins/astrbot_plugin_anysearch
C=/AstrBot/data/config
U=/root/uploads
TS=$(date +%Y%m%d-%H%M%S)
BK=/opt/miruku/backups/asb-$TS.tar

echo "=== 1. backup ==="
docker exec -i astrbot sh -c "tar -cf /tmp/asb-bk.tar -C /AstrBot/data/plugins astrbot_plugin_anysearch -C /AstrBot/data/config astrbot_plugin_anysearch_config.json" \
  && docker cp astrbot:/tmp/asb-bk.tar "$BK" \
  && echo "BACKUP=$BK size=$(stat -c%s "$BK")"

echo "=== 2. copy files ==="
for f in client.py tools.py main.py _conf_schema.json; do
  docker cp "$U/$f" "astrbot:$D/$f" || exit 1
done
docker cp "$U/config.json" "astrbot:$C/astrbot_plugin_anysearch_config.json" || exit 1
echo "COPIED"

echo "=== 3. syntax check ==="
docker exec -i astrbot sh -c "cd $D && python3 -m py_compile client.py tools.py main.py && echo PYCOMPILE_OK"

echo "=== 4. truncation unit test (no restart) ==="
cat > /tmp/t_asb.py <<'PY'
import asyncio, sys
sys.path.insert(0, "/AstrBot/data/plugins")
import importlib
import astrbot_plugin_anysearch.client as m
importlib.reload(m)
C = m.AnySearchClient(api_key="", timeout=40, tool_result_max_chars=4000)
print("max_chars =", C.tool_result_max_chars)
r = asyncio.run(C.search("maimai 海底譚 作曲", max_results=5))
print(f"SEARCH chars={len(r)}")
assert len(r) < 4600, "truncate failed"
assert "已截断" in r, "notice missing"
r2 = asyncio.run(C.batch_search([
    {"query": "maimai 海底譚 作曲", "max_results": 5},
    {"query": "舞萌 Xevel 谱面", "max_results": 5},
]))
print(f"BATCH chars={len(r2)}")
assert len(r2) <= 8100, "batch budget failed"
print("TRUNCATE_OK")
PY
docker cp /tmp/t_asb.py astrbot:/tmp/t_asb.py
docker exec -i astrbot python3 /tmp/t_asb.py 2>&1 | tail -15

echo "=== 5. restart & verify ==="
docker restart astrbot >/dev/null
sleep 40
docker exec -i astrbot sh -c "grep -c _truncate $D/client.py; grep -c tool_result_max_chars $C/astrbot_plugin_anysearch_config.json"
docker logs --since 2m astrbot 2>&1 | grep -aE "Loaded .* personas|armed:|恢复任务|适配器已连接" | tail -8
echo "DONE"
