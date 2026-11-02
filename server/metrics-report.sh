#!/bin/bash
# 在宿主机上跑聊天质量报告（数据在容器里，先捞出来再分析）
# 用法：bash /opt/miruku/server/metrics-report.sh [--days N] [--json]
set -uo pipefail
SRC=/AstrBot/data/plugin_data/miruku_metrics/metrics.jsonl
TMP=/tmp/miruku_metrics_report.jsonl
SCRIPT=/opt/miruku/server/metrics-report.py

if ! docker ps --format '{{.Names}}' | grep -qx astrbot; then
    echo "astrbot 容器没在跑" >&2
    exit 1
fi

if docker exec astrbot test -f "$SRC"; then
    docker exec astrbot cat "$SRC" > "$TMP"
else
    : > "$TMP"
fi

python3 "$SCRIPT" --file "$TMP" "$@"
