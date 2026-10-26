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

append "status=$status up=$astrbot_up/$napcat_up dash=$dash ws6199=$ws jobs=$(echo "$jobs" | tr -d '\n' | head -c 110)"

# 自愈：只动坏的那一侧；NO_WS_LINK 先等一轮自愈窗口（NapCat 自己会重连），
# 连续两轮仍无链路才重启 napcat，避免每次抖动都打断正在进行的登录。
# NapCat 在「尚未扫码登录」时必然没有 6199 链路。此时若照判据重启 napcat，
# 会把用户正在扫的二维码刷掉（登录永远完不成）。因此 WS 自愈要等
# logs/qr-acked 出现（扫码完成后由人/脚本 touch）才生效；在此之前只记日志。
WS_HEAL=off
[ -f "$APP/logs/qr-acked" ] && WS_HEAL=on

case "$status" in
  ASTRBOT_DOWN) append "ALERT self-heal: up astrbot"; docker compose up -d astrbot >>"$LOG" 2>&1 ;;
  NAPCAT_DOWN)  append "ALERT self-heal: up napcat";  docker compose up -d napcat  >>"$LOG" 2>&1 ;;
  DASHBOARD_UNREACH) append "ALERT dashboard unreachable; restart astrbot"; docker restart astrbot >>"$LOG" 2>&1 ;;
  NO_WS_LINK)
    streak_file=$APP/logs/ws-streak
    n=$(cat "$streak_file" 2>/dev/null || echo 0)
    n=$((n+1)); echo "$n" > "$streak_file"
    if [ "$WS_HEAL" = on ]; then
      append "ws link down (streak=$n/2, heal=on)"
      [ "$n" -ge 2 ] && { append "ALERT restart napcat to force reconnect"; docker restart napcat >>"$LOG" 2>&1; echo 0 > "$streak_file"; }
    else
      append "ws link down (heal=off: 未扫码登录，不动 napcat；streak=$n)"
    fi
    ;;
  *) [ "$status" = OK ] && echo 0 > "$APP/logs/ws-streak" ;;
esac
