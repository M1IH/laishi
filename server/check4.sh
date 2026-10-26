#!/usr/bin/env bash
echo "== dash =="
curl -s -o /dev/null -w '6185 -> %{http_code}\n' --max-time 5 http://127.0.0.1:6185/api/v1/system-config
echo "== plugin console =="
curl -s --max-time 5 http://127.0.0.1:4100/api/jobs | head -c 200; echo
echo "== astrbot recent =="
docker logs astrbot 2>&1 | tail -6 | sed 's/\x1b\[[0-9;]*m//g'
echo "== webui token (this deployment only) =="
grep NAPCAT_WEBUI_TOKEN /opt/miruku/.env
echo "== napcat alive =="
docker exec napcat python3 -c "print('napcat-alive')" 2>/dev/null || docker inspect -f '{{.State.Status}}' napcat
echo "== heartbeat latest =="
tail -2 /var/log/miruku-heartbeat.log
