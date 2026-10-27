# -*- coding: utf-8 -*-
"""把心跳的在线判据改成「通过 AstrBot 的 6199 WS 通道问 NapCat」。

之前两次都选错了：
  1) 数 /proc/net/tcp 的 ESTABLISHED —— QQ 不走普通 TCP socket，在线时也数不到
  2) 请求 http://napcat:3000/get_status —— NapCat 的 httpServers 是空的，
     它只开了 websocketClients（连 AstrBot:6199），HTTP 接口根本不存在

正确做法：从 AstrBot 容器连接 ws://127.0.0.1:6199/ws（那是 NapCat 主动连进来的
反向 WS），发一个 OneBot 动作 get_status，等回包。回包正常 = NapCat 主体活着
且 QQ 在线；连不上/超时 = 掉线。这是业务层真探活，不依赖任何网络实现细节。
"""
from pathlib import Path

p = Path("server/heartbeat.sh")
src = p.read_text(encoding="utf-8")

start = src.find("# 「QQ 是否真的在线」判据")
end = src.find('jobs=$(curl -s --max-time 8 http://127.0.0.1:4100/api/jobs')
if start < 0 or end < 0:
    raise SystemExit(f"[FAIL] 锚点未找到 start={start} end={end}")

block = '''# 「QQ 是否真的在线」判据（2026-10-27 事故后新增，最关键的一条）
#
# 为什么必须加：当天 09:57 QQ 掉线，之后 3 小时收发全断，而旧心跳一直报 OK——
# 因为它只看容器间 6199 有没有 ESTABLISHED。NapCat 断网时那条 TCP 还挂着
# （对端没发 FIN，TCP 自己不知道），于是「容器 running + ws6199=1」看着完美无缺。
#
# 试过但**不可用**、别再走回头路：
#   ① 数 /proc/net/tcp 的 ESTABLISHED —— QQ 不走普通 TCP socket。实测在线收发
#      完全正常（日志里同时有 接收<- 和 发送->）时，该表也数不出到腾讯的连接，
#      恒 0~1，拿它当判据只会天天误报。
#   ② 请求 http://napcat:3000/get_status —— NapCat 的 httpServers 是空数组，
#      它只开了 websocketClients（主动连 AstrBot:6199），HTTP 接口不存在，
#      必然连接失败。
#
# 可用判据：**通过 6199 反向 WS 发一个 OneBot 动作**。NapCat 是从里面连进来的，
# 所以 astrbot 容器的 127.0.0.1:6199 就通到它。发 get_status 等回包：
#   · 有回包  → NapCat 主体活着、QQ 在线（业务层真探活）
#   · 无回包  → 掉线/等扫码，需要人扫
qq_online=false
qstat=$(docker exec astrbot python3 -c '
import asyncio, json
try:
    import websockets
except Exception:
    print("NO_WS_LIB"); raise SystemExit

async def probe():
    try:
        async with websockets.connect("ws://127.0.0.1:6199/ws", open_timeout=5,
                                      close_timeout=2) as ws:
            await ws.send(json.dumps({"action": "get_status", "params": {}}))
            raw = await asyncio.wait_for(ws.recv(), timeout=6)
            d = json.loads(raw)
            data = d.get("data") or {}
            ok = d.get("status") in ("ok", "async", "failed") or d.get("retcode") in (0, 1)
            online = data.get("online")
            print("OK" if ok and online is not False else "BAD")
    except Exception as e:
        print("BAD")
try:
    asyncio.run(probe())
except Exception:
    print("BAD")
' 2>/dev/null || echo BAD)
[ "$qstat" = "OK" ] && qq_online=true

napcat_proc=$(docker exec napcat sh -c 'ps aux 2>/dev/null | grep -c "[n]apcat.mjs" || echo 0' 2>/dev/null || echo 0)

'''
src = src[:start] + block + src[end:]
p.write_text(src, encoding="utf-8")
print("[ok] 判据已改为 6199 WS 业务探活")
