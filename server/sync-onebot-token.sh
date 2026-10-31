#!/bin/bash
# 把 SnowLuma 的 OneBot HTTP accessToken 同步进 astrbot 容器（供 miruku_backfill 用）
# token 只在 SnowLuma 重新生成账号配置时才变，所以每轮心跳同步一次足够。
set -uo pipefail

SRC=/var/lib/docker/volumes/qq-gateway-data/_data/config/onebot.json
DEST=/AstrBot/data/plugin_data/miruku_backfill/onebot_token.txt

TOKEN=$(python3 - "$SRC" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8-sig") as f:
        cfg = json.load(f)
    for s in ((cfg.get("networks") or {}).get("httpServers") or []):
        tok = str(s.get("accessToken") or "").strip()
        if tok:
            print(tok)
            break
except Exception:
    pass
PY
)

if [ -z "$TOKEN" ]; then
    echo "TOKEN_SYNC=NO_TOKEN"
    exit 0
fi

docker exec astrbot mkdir -p "$(dirname "$DEST")" 2>/dev/null
printf '%s' "$TOKEN" | docker exec -i astrbot sh -c "cat > $DEST" && \
  echo "TOKEN_SYNC=OK len=${#TOKEN}" || echo "TOKEN_SYNC=FAIL"
