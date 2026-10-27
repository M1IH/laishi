#!/usr/bin/env bash
# 探测三个 WebUI 能否被 iframe 内嵌（X-Frame-Options / CSP frame-ancestors）
for spec in "astrbot|6185|" "napcat|6099|/webui/" "novnc|6080|/vnc.html"; do
  name=${spec%%|*}; rest=${spec#*|}; port=${rest%%|*}; path=${rest#*|}
  echo "== $name :$port$path =="
  curl -sI --max-time 6 "http://127.0.0.1:$port$path" \
    | grep -iE '^(HTTP/|x-frame-options|content-security-policy|server)' | sed 's/^/   /'
done
echo "== 监听确认 =="
ss -tln | grep -E ':(6185|6099|6080|4100)$' | sed 's/^/   /'
