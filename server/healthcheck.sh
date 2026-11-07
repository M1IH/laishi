#!/usr/bin/env bash
# 供 setup-ssh-key.ps1 与面板共用：检查 SSH 可达性（不碰密钥内容）
# 服务器地址从环境变量或项目根 .env 的 MIRUKU_SSH 读取，
# 公开仓库只带 RFC 5737 占位地址 203.0.113.10。
if [ -z "${MIRUKU_SSH:-}" ] && [ -f "$(dirname "$0")/../.env" ]; then
    MIRUKU_SSH=$(awk -F= '/^[[:space:]]*MIRUKU_SSH[[:space:]]*=/ {
        sub(/^[^=]*=/, ""); gsub(/["\047\r]/, ""); sub(/[[:space:]]+$/, ""); print; exit
    }' "$(dirname "$0")/../.env")
fi
MIRUKU_SSH=${MIRUKU_SSH:-root@203.0.113.10}
echo "== server reachable =="
ssh -o BatchMode=yes -o ConnectTimeout=10 "$MIRUKU_SSH" 'echo CONNECT_OK' 2>&1 | tail -1
echo "== containers =="
docker ps --format '{{.Names}}: {{.Status}}'
echo "== link =="
echo -n "  established: "; docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01
