#!/usr/bin/env bash
# 供 setup-ssh-key.ps1 与面板共用：检查 SSH 可达性（不碰密钥内容）
echo "== server reachable =="
ssh -o BatchMode=yes -o ConnectTimeout=10 root@203.0.113.10 'echo CONNECT_OK' 2>&1 | tail -1
echo "== containers =="
docker ps --format '{{.Names}}: {{.Status}}'
echo "== link =="
echo -n "  established: "; docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01
