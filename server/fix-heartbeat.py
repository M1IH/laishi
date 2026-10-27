# -*- coding: utf-8 -*-
"""把 heartbeat.sh 里失效的「数 TCP 连接」判据换成 OneBot 业务探活。

原因：QQ 不走普通 TCP socket，在线收发完全正常时 /proc/net/tcp 里也数不出
到腾讯的连接（实测恒 0~1），拿它当判据会天天误报。改用 NapCat 的 OneBot
HTTP 接口 get_status —— 由 napcat.mjs 提供，只有主体活着且在线才应答。
"""
from pathlib import Path

p = Path("server/heartbeat.sh")
src = p.read_text(encoding="utf-8")

start_marker = "# QQ 到**外网**的 ESTABLISHED 连接数"
end_marker = 'jobs=$(curl -s --max-time 8 http://127.0.0.1:4100/api/jobs'

i = src.find(start_marker)
j = src.find(end_marker)
if i < 0 or j < 0:
    raise SystemExit(f"[FAIL] 找不到锚点 i={i} j={j}")

new_block = '''# 「QQ 是否真的在线」判据（2026-10-27 事故后新增，最关键的一条）
#
# 为什么必须加：当天 09:57 QQ 掉线，之后 3 小时收发全断，而旧心跳一直报 OK——
# 因为它只看容器间 6199。NapCat 断网时那条 TCP 还挂着（对端没发 FIN，
# TCP 自己不知道），于是「容器 running + ws6199=1」看起来完美无缺。
#
# 试过但**不可用**、别再走回头路：
#   数 /proc/net/tcp 的 ESTABLISHED —— QQ 不走普通 TCP socket。实测在线收发
#   完全正常（日志里同时有 接收<- 与 发送->）时，该表里也数不出到腾讯的连接
#   （恒 0~1），拿它当判据只会天天误报。
#
# 可用判据：**NapCat 的 OneBot HTTP 接口**。它由 napcat.mjs 提供，只有主体活着
# 且 QQ 在线才会正常应答；掉线/等扫码时 napcat.mjs 停摆，请求直接失败。
# 这是业务层探活，不猜网络实现细节。
qq_online=false
qstat=$(docker exec astrbot python3 -c '
import json, urllib.request
try:
    with urllib.request.urlopen("http://napcat:3000/get_status", timeout=6) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    data = d.get("data") or {}
    ok = d.get("retcode") in (0, 1) and d.get("status") in ("ok", "async", "failed")
    online = data.get("online")
    print("OK" if ok and online is not False else "BAD")
except Exception:
    print("BAD")
' 2>/dev/null || echo BAD)
[ "$qstat" = "OK" ] && qq_online=true

napcat_proc=$(docker exec napcat sh -c 'ps aux 2>/dev/null | grep -c "[n]apcat.mjs" || echo 0' 2>/dev/null || echo 0)

'''
src = src[:i] + new_block + src[j:]

# 状态判定：用 qq_online 代替 qqconn
old_check = '''  # 先判 QQ 是否真的在线（阈值 2：掉线时实测 0，在线 5+，留足抖动余量）
  if [ "$qqconn" -ge 0 ] && [ "$qqconn" -lt 2 ]; then
    status=QQ_OFFLINE
  elif ! [ "$ws" -ge 1 ]; then
    status=NO_WS_LINK
  fi'''
new_check = '''  # 先判 QQ 是否真的在线（业务层探活，见上面注释）
  if [ "$qq_online" != true ]; then
    status=QQ_OFFLINE
  elif ! [ "$ws" -ge 1 ]; then
    status=NO_WS_LINK
  fi'''
if old_check not in src:
    raise SystemExit("[FAIL] 找不到状态判定块")
src = src.replace(old_check, new_check)

# 日志字段替换
src = src.replace('qqconn=$qqconn', 'qq_online=$qq_online')
# 告警文案
src = src.replace(
    'append "ALERT QQ_OFFLINE: 到腾讯的连接只剩 $qqconn 条 —— 需要人工重扫二维码（勿自动重启）"',
    'append "ALERT QQ_OFFLINE: OneBot 接口无应答，QQ 已掉线 —— 需要人工重扫二维码（勿自动重启）"')

p.write_text(src, encoding="utf-8")
print("[ok] heartbeat.sh 已重写")
print("残留 qqconn 引用:", src.count("qqconn"))
