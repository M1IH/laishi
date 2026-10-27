#!/usr/bin/env bash
echo "== 登录结果 =="
docker logs napcat --since 6m 2>&1 | grep -vE '^[0-9a-f]{40,}$' \
  | grep -iE '登录成功|Login|二维码已被扫描|失效|成功' | tail -6 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'

echo ""
echo "== 6199 链路 =="
echo -n "  established: "; docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01 2>/dev/null || echo "?"

echo ""
echo "== AstrBot 是否认到适配器 =="
docker logs astrbot --since 8m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '适配器已连接' | tail -2

echo ""
echo "== 【新判据】NapCat 到腾讯服务器的真实连接 =="
docker exec napcat sh -c '
n=0
for f in /proc/net/tcp /proc/net/tcp6; do
  [ -f "$f" ] || continue
  awk "NR>1 && \$4==\"01\" {print \$3}" "$f"
done | wc -l' 2>/dev/null | sed 's/^/  总 ESTABLISHED: /'

echo ""
echo "== 用 NapCat 的 OneBot 接口验证在线（最权威）=="
docker exec astrbot python3 - <<'PY'
import json, urllib.request
try:
    req = urllib.request.Request("http://napcat:3000/get_login_info")
    with urllib.request.urlopen(req, timeout=8) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    info = d.get("data", {})
    import re
    uin = re.sub(r"(\d{3})\d{4}(\d{3})", r"\1***\2", str(info.get("user_id", "")))
    print(f"  retcode={d.get('retcode')} uin={uin} nickname={info.get('nickname')}")
except Exception as e:
    print("  OneBot HTTP 不可用:", type(e).__name__, str(e)[:70])
PY
