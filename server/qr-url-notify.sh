#!/bin/bash
# 隧道 URL 变化时推送新链接（避免用户存的旧链接失效）。
# 由 heartbeat 每 5 分钟调用；只在 URL 真的变了才推。
set -u
APP=/opt/miruku
KEYFILE="$APP/.wechat-sendkey"
URLFILE="$APP/logs/qr-tunnel-url"
SEEN="$APP/logs/qr-tunnel-url.last-pushed"
LOG="$APP/logs/qr-tunnel-notify.log"

url=$(cat "$URLFILE" 2>/dev/null | tr -d '\r\n')
[ -z "$url" ] && exit 0

last=$(cat "$SEEN" 2>/dev/null | tr -d '\r\n')
[ "$url" = "$last" ] && exit 0

key=$(cat "$KEYFILE" 2>/dev/null | tr -d '\r\n')
if [ -z "$key" ]; then
  echo "$(date '+%F %T') no key, skip" >> "$LOG"
  exit 0
fi

tok=$(cat "$APP/logs/qrpage-token" 2>/dev/null | tr -d '\r\n')
full="${url%/}/?t=$tok"
desc="扫码地址更新了（旧链接已失效）。%0A%0A[点这里手机扫码](${full})%0A（电脑关机也能用）"
resp=$(curl -s -m 10 -X POST "https://sctapi.ftqq.com/${key}.send" \
  -d "title=Miruku 扫码地址已更新" -d "desp=${desc}" 2>&1)
case "$resp" in
  *'"code":0'*)
    printf '%s' "$url" > "$SEEN"
    echo "$(date '+%F %T') pushed $url" >> "$LOG"
    ;;
  *)
    echo "$(date '+%F %T') push failed: $(echo "$resp" | head -c 120)" >> "$LOG"
    ;;
esac
