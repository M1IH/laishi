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

jobs=$(curl -s --max-time 8 http://127.0.0.1:4100/api/jobs 2>/dev/null || echo '{}')

status=OK
[ "$astrbot_up" = true ] || status=ASTRBOT_DOWN
[ "$napcat_up" = true ] || [ "$status" != OK ] || status=NAPCAT_DOWN
case "$dash" in 200|401|403) ;; *) [ "$status" = OK ] && status=DASHBOARD_UNREACH ;; esac
if [ "$status" = OK ]; then
  [ "$ws" -ge 1 ] || status=NO_WS_LINK
  [ "$ws" = -1 ] && status=EXEC_FAIL
fi

# 落盘前掩码：jobs 原文里带未掩码的 QQ 号，日志文件不该写明文
append_masked(){ echo "$(NOW) $*" | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g' >> "$LOG"; }
append_masked "status=$status up=$astrbot_up/$napcat_up dash=$dash ws6199=$ws jobs=$(echo "$jobs" | tr -d '\n' | head -c 110)"

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
