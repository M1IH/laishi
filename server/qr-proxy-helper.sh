#!/bin/bash
# 给 PC 面板用的转发助手：输出「固定 40 字节头部 + 原始 PNG」，面板据此还原因点击坐标。
# 头部格式：CROP x  y  HTTP nnn\n  （右补空格到 40 字节，便于面板按固定长度切分）
TOK=$(cat /opt/miruku/logs/qrpage-token 2>/dev/null)
if [ -z "$TOK" ]; then
  printf 'ERR  no qrpage token                    \n'
  exit 0
fi
Q="t=$TOK"
if [ "${QR_FULL:-0}" = "1" ]; then
  Q="$Q&full=1"
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
code=$(curl -s -m 20 -D "$TMP/h" -o "$TMP/p.png" -w '%{http_code}' \
       "http://127.0.0.1:8663/shot?$Q")
cx=$(awk 'tolower($1)=="x-crop-x:"{print $2}' "$TMP/h" | tr -d '\r')
cy=$(awk 'tolower($1)=="x-crop-y:"{print $2}' "$TMP/h" | tr -d '\r')
cx=${cx:-0}
cy=${cy:-0}
HDR=$(printf 'CROP %-5s %-5s HTTP %s' "$cx" "$cy" "$code")
printf '%-40s' "$HDR"
if [ "$code" = "200" ]; then
  cat "$TMP/p.png"
fi
