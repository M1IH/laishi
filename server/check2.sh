#!/usr/bin/env bash
echo "== napcat real logs =="
docker logs napcat 2>&1 | grep -Ev '^[0-9a-f]{40,}$' | tail -14
echo "== napcat listeners =="
docker exec napcat bash -lc "ss -tln | tail -6" 2>&1 || true
echo "== host listeners =="
ss -tln | grep -E ':(6099|3001|6185|4100)$' || echo "(none yet)"
echo "== astrbot internal 6199 =="
docker exec astrbot bash -lc "ss -tln | grep 6199 || netstat -tln 2>/dev/null | grep 6199 || echo no-6199-listener" 2>&1 | tail -2
echo "== heartbeat log =="
tail -3 /var/log/miruku-heartbeat.log 2>/dev/null || echo "(empty)"
