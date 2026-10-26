#!/usr/bin/env bash
# 预检：compose.yaml 的 YAML 合法性（本地无 python3/yaml 时用 Launcher 的 python）
set -euo pipefail
cd "$(dirname "$0")"
PY="${1:-python}"
"$PY" precheck.py
