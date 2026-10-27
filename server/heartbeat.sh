#!/usr/bin/env bash
# Miruku 心跳与自愈（D4 第 1/3/4 条的实现载体）——每 5 分钟由 systemd timer 跑一次
#
# 四项判据：
#   A 两容器 running
#   B AstrBot dashboard 可访问（401 也算活着，4000 才是不通）
#   C NapCat↔AstrBot 的 6199 链路 ESTABLISHED
#     ——注意：**不能**在宿主 netns 里 ss 查（跨容器连接不在宿主 socket 表里），
#     也不能信插件 /api/status 的 ws_connections（本机实测该字段与实际不符）；
#     唯一可信读法是进 astrbot 容器读它自己 netns 的 /proc/net/tcp。
#   D 主动任务有排期（插件控制台 4100 已在 compose 里映射到宿主回环）
set -uo pipefail

LOG=/var/log/miruku-heartbeat.log
APP=/opt/miruku
NOW(){ date '+%F %T'; }
append(){ echo "$(NOW) $*" >> "$LOG"; }

cd "$APP"

astrbot_up=$(docker inspect -f '{{.State.Running}}' astrbot 2>/dev/null || echo false)
napcat_up=$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null || echo false)

dash=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:6185/api/v1/system-config || echo 000)

# 6199 = 0x1837；ESTABLISHED = 01。tcp6 一并查。
ws=$(docker exec astrbot python3 -c '
import glob
n=0
for f in ("/proc/net/tcp","/proc/net/tcp6"):
    try:
        for line in open(f).read().splitlines()[1:]:
            p=line.split()
            if p[1].endswith(":1837") and p[3]=="01": n+=1
    except OSError: pass
print(n)
' 2>/dev/null || echo -1)

# 「QQ 是否真的在线」判据（2026-10-27 事故后新增，最关键的一条）
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
last_active=$(docker logs napcat --since 150m 2>&1 \
  | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E 'ServerTime|接收 <-|发送 ->' \
  | tail -1 \
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

jobs=$(curl -s --max-time 8 http://127.0.0.1:4100/api/jobs 2>/dev/null || echo '{}')

status=OK
[ "$astrbot_up" = true ] || status=ASTRBOT_DOWN
[ "$napcat_up" = true ] || [ "$status" != OK ] || status=NAPCAT_DOWN
case "$dash" in 200|401|403) ;; *) [ "$status" = OK ] && status=DASHBOARD_UNREACH ;; esac
if [ "$status" = OK ]; then
  # 先判 QQ 是否真的在线（业务层探活，见上面注释）
  if [ "$qq_online" != true ]; then
    status=QQ_OFFLINE
  elif ! [ "$ws" -ge 1 ]; then
    status=NO_WS_LINK
  fi
  [ "$ws" = -1 ] && status=EXEC_FAIL
fi

# 落盘前掩码：jobs 原文里带未掩码的 QQ 号，日志文件不该写明文
append_masked(){ echo "$(NOW) $*" | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g' >> "$LOG"; }
append_masked "status=$status up=$astrbot_up/$napcat_up dash=$dash ws6199=$ws qq_online=$qq_online idle_min=$idle_min jobs=$(echo "$jobs" | tr -d '\n' | head -c 100)"

# 自愈：只动坏的那一侧；NO_WS_LINK 先等一轮自愈窗口（NapCat 自己会重连），
# 连续两轮仍无链路才重启 napcat，避免每次抖动都打断正在进行的登录。
# 链路断的处置（2026-10-26 实测后收紧）：
# 原设计「连续两轮无链路就 docker restart napcat」被证明**有害**——重启 NapCat
# 会让 QQ 登录态失效（实测：23:33 重启进二维码等待 → 23:39 快速登录报
# 「登录态已失效」），等于把一次可自愈的抖动升级成必须人工重扫。
# NapCat 自身带 1 秒重连，链路长期不通通常是**对端**（AstrBot）的问题，
# 所以只重启 astrbot；真需要重扫时交给人，不自动动 napcat。
case "$status" in
  ASTRBOT_DOWN) append "ALERT self-heal: up astrbot"; docker compose up -d astrbot >>"$LOG" 2>&1 ;;
  NAPCAT_DOWN)  append "ALERT self-heal: up napcat";  docker compose up -d napcat  >>"$LOG" 2>&1 ;;
  DASHBOARD_UNREACH) append "ALERT dashboard unreachable; restart astrbot"; docker restart astrbot >>"$LOG" 2>&1 ;;
  QQ_OFFLINE)
    # 2026-10-27 事故：QQ 掉线时容器和 6199 全都正常，只有到腾讯的连接归零。
    # 这种状态**不能靠重启修复**——重启会让登录态失效，还得人工扫码，反而更糟。
    # 所以只做一件事：把告警写清楚，等人来扫。同时写一个标记文件，
    # 面板会显示「需扫码」红条，不必去翻日志。
    append "ALERT QQ_OFFLINE: NapCat 已 $idle_min 分钟无活动，QQ 疑似掉线 —— 需人工重扫二维码（勿自动重启）"
    date '+%F %T' > "$APP/logs/needs-rescan" 2>/dev/null || true
    ;;
  NAPCAT_BODY_GONE)
    append "ALERT napcat.mjs 进程不在了（容器仍 running）；重启容器"
    docker restart napcat >>"$LOG" 2>&1
    ;;
  NO_WS_LINK)
    # 先看 astrbot 侧 6199 有没有在听；没在听就是 astrbot 的锅，重启它
    listen=$(docker exec astrbot python3 -c "
n=0
for f in ('/proc/net/tcp','/proc/net/tcp6'):
    try:
        for l in open(f).read().splitlines()[1:]:
            p=l.split()
            if p[1].endswith(':1837') and p[3]=='0A': n+=1
    except OSError: pass
print(n)" 2>/dev/null || echo 0)
    if [ "$listen" -ge 1 ]; then
      append "ALERT ws link down but astrbot is listening -> 大概率 QQ 登录态失效，需人工扫码（不自动重启 napcat）"
    else
      append "ALERT ws link down and no 6199 listener; restart astrbot"
      docker restart astrbot >>"$LOG" 2>&1
    fi
    ;;
esac
