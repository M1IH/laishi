# -*- coding: utf-8 -*-
"""心跳在线判据最终版：NapCat 日志里的「握手/时间同步」活跃度。

踩过的三个坑（都写进注释，防止以后有人再走一遍）：
  ① /proc/net/tcp 数 ESTABLISHED —— QQ 不走普通 TCP socket。实测在线收发
     完全正常时该表也数不出到腾讯的连接（恒 0~1），必然误报。
  ② http://napcat:3000/get_status —— onebot11 配置里 httpServers 是空数组，
     NapCat 只开了 websocketClients（主动连 astrbot:6199），没有 HTTP 接口。
  ③ 自己连 ws://127.0.0.1:6199/ws 发 OneBot 动作 —— 6199 是 AstrBot 的平台
     适配器端口，协议是 AstrBot 自己的握手，不是裸 OneBot WS。实测连上后
     发动作收不到任何回包（超时）。
  另外 `ps aux | grep napcat.mjs` 计数恒为 0，也不可用（进程名对不上）。

可用信号：NapCat 每隔一小时输出一行 `[ServerTime] 时间同步完成`，这是它
与腾讯服务器维持会话的副产物；QQ 掉线后这行会停止（实测 09:57 掉线后
直到 12:24 重启都没有新的 ServerTime）。做法：看日志里最近一条
ServerTime / 收发记录的时间戳，超过 70 分钟没有任何动静 = 疑似掉线。
（阈值取 70 分钟：心跳本身是每小时一次，留 10 分钟余量。）
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
# （对端没发 FIN，TCP 自己不知道），于是「容器 running + ws6199=1」看着天衣无缝。
#
# 试过但**全部不可用**，别再走回头路（每一条都实测过）：
#   ① 数 /proc/net/tcp 的 ESTABLISHED —— QQ 不走普通 TCP socket。在线收发
#      完全正常时该表也数不出来（恒 0~1），用它当判据只会天天误报。
#   ② http://napcat:3000/get_status —— onebot11 里 httpServers 是空数组，
#      NapCat 只开了 websocketClients，根本没有 HTTP 接口。
#   ③ 自己连 ws://127.0.0.1:6199 发 OneBot 动作 —— 6199 是 AstrBot 的平台
#      适配器端口，走它自己的握手协议，发动作收不到回包（实测超时）。
#   ④ ps aux | grep napcat.mjs —— 进程名对不上，计数恒 0。
#
# 可用信号：NapCat 每小时输出一行 `[ServerTime] 时间同步完成`，是与腾讯维持
# 会话的副产物；QQ 掉线后这行就停了（实测 09:57 掉线 → 12:24 重启前无新行）。
# 做法：取日志里最近一条 「ServerTime / 接收 / 发送」的时间戳，超过 70 分钟
# 没动静就判疑似掉线（心跳本身 60 分钟一次，留 10 分钟余量）。
qq_online=false
last_active=$(docker logs napcat --since 150m 2>&1 \\
  | sed 's/\\x1b\\[[0-9;]*m//g' \\
  | grep -E 'ServerTime|接收 <-|发送 ->' \\
  | tail -1 \\
  | grep -oE '^[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}' || true)
if [ -n "$last_active" ]; then
  last_ts=$(date -d "2026-$last_active" +%s 2>/dev/null || echo 0)
  now_ts=$(date +%s)
  if [ "$last_ts" -gt 0 ]; then
    idle_min=$(( (now_ts - last_ts) / 60 ))
    [ "$idle_min" -lt 70 ] && qq_online=true
  fi
else
  idle_min=-1
fi

'''
src = src[:start] + block + src[end:]

# 日志字段：把 napcat_proc 换成 idle_min
src = src.replace("napcat_proc=$napcat_proc", "idle_min=$idle_min")

p.write_text(src, encoding="utf-8")
print("[ok] 判据改为日志活跃度（ServerTime/收发时间戳）")
print("  残留 napcat_proc:", src.count("napcat_proc"))
