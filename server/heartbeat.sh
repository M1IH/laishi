#!/usr/bin/env bash
# Miruku 心跳与自愈（D4 第 1/3/4 条的实现载体）——每 5 分钟由 systemd timer 跑一次
# 2026-10-30 v2：QQ 载体从 NapCat 换成 SnowLuma，判据全面重写。
#
# 四项判据：
#   A 两容器 running（astrbot + snowluma）
#   B AstrBot dashboard 可访问（401 也算活着，000 才是不通）
#   C SnowLuma↔AstrBot 的 6199 链路 ESTABLISHED
#     ——不能在宿主 netns 里 ss 查（跨容器连接不在宿主 socket 表里），
#     唯一可信读法是进 astrbot 容器读它自己 netns 的 /proc/net/tcp。
#   D 主动任务有排期（插件控制台 4100 已在 compose 里映射到宿主回环）
#
# QQ 业务层在线判定（v2 核心变更）：
#   SnowLuma 按天写 /app/data/logs/snowluma-YYYY-MM-DD.log（宿主卷直读），
#   登录成功记 `login detected`，凭据失效/登出记 `awaiting login`。
#   这是事件驱动信号，比 NapCat 时代的「70 分钟无活动」启发式可靠。
#   登录可能发生在昨天（之后一直在线），所以合并昨天+今天两个文件取最后一条。
set -uo pipefail

LOG=/var/log/miruku-heartbeat.log
APP=/opt/miruku
SNOW_LOGDIR=/var/lib/docker/volumes/qq-gateway-data/_data/logs
# 微信告警
KEYFILE="$APP/.wechat-sendkey"
SENTFLAG="$APP/logs/wechat-sent"
NOW(){ date '+%F %T'; }
append(){ echo "$(NOW) $*" >> "$LOG"; }

# Server酱推送：https://sct.ftqq.com/
# 成功/失败都写日志（推送是唯一的"人不在场也能知道"的通道，静默失败等于没装）
wechat_push(){
  local key resp
  key=$(cat "$KEYFILE" 2>/dev/null) || { append "WARN wechat: no key file"; return 1; }
  local title="Miruku 掉线了"
  local desc="QQ 登录态失效，需要重新扫码。"
  desc="${desc}%0A打开桌面「Miruku 面板」快捷方式 → noVNC·扫码页，点确认后用手机 QQ 扫码。"
  resp=$(curl -s -m 10 -X POST "https://sctapi.ftqq.com/${key}.send" \
    -d "title=${title}" -d "desp=${desc}" 2>&1) || { append "WARN wechat push curl failed"; return 1; }
  case "$resp" in
    *'"code":0'*) append "wechat push OK"; return 0 ;;
    *) append "WARN wechat push rejected: $(echo "$resp" | head -c 160)"; return 1 ;;
  esac
}

cd "$APP"

astrbot_up=$(docker inspect -f '{{.State.Running}}' astrbot 2>/dev/null || echo false)
snowluma_up=$(docker inspect -f '{{.State.Running}}' snowluma 2>/dev/null || echo false)

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

# QQ 业务层在线判定（SnowLuma 事件驱动）
# v3 修复（2026-10-31 实锤 bug）：`login detected` 只在真正登录的那一刻打一次，
# 之后一直在线就不会再打。v2 只读"昨天+今天"两个文件 → 跨天之后永远找不到事件，
# 判成 no-signal/QQ_OFFLINE，误报掉线（实际机器人当时正常收发消息）。
# 改为：①扫全部日志（近 7 个文件）取最后一次登录事件；②今天日志近期有活动 = 正向确认。
qq_online=false
login_state=no-signal
TODAY=$(date +%F)
last_login=$(ls -1 "$SNOW_LOGDIR"/snowluma-*.log 2>/dev/null | sort | tail -7 \
  | xargs -r grep -hE 'login detected|awaiting login' 2>/dev/null | tail -1)
case "$last_login" in
  *"login detected"*) qq_online=true;  login_state=online ;;
  *"awaiting login"*) qq_online=false; login_state=awaiting ;;
  *) qq_online=false; login_state=no-signal ;;
esac
# 正向确认：今天日志 15 分钟内有写入 = 会话真的在跑（事件在流动）。
# 只用于把 no-signal 升级成 online，绝不覆盖 awaiting（凭据失效时日志仍在轮询，不能算在线）。
if [ "$login_state" = no-signal ]; then
  tf="$SNOW_LOGDIR/snowluma-$TODAY.log"
  if [ -f "$tf" ] && [ $(( $(date +%s) - $(stat -c %Y "$tf" 2>/dev/null || echo 0) )) -le 900 ]; then
    qq_online=true; login_state=online-by-activity
  fi
fi

jobs=$(curl -s --max-time 8 http://127.0.0.1:4100/api/jobs 2>/dev/null || echo '{}')

status=OK
[ "$astrbot_up" = true ] || status=ASTRBOT_DOWN
[ "$snowluma_up" = true ] || { [ "$status" != OK ] || status=SNOWLUMA_DOWN; }
case "$dash" in 200|401|403) ;; *) [ "$status" = OK ] && status=DASHBOARD_UNREACH ;; esac
if [ "$status" = OK ]; then
  # 先判 QQ 是否真的在线（业务层探活，见头部注释）
  if [ "$qq_online" != true ]; then
    status=QQ_OFFLINE
  elif ! [ "$ws" -ge 1 ]; then
    status=NO_WS_LINK
  fi
  [ "$ws" = -1 ] && status=EXEC_FAIL
fi

# 落盘前掩码：jobs 原文里带未掩码的 QQ 号，日志文件不该写明文
append_masked(){ echo "$(NOW) $*" | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g' >> "$LOG"; }
append_masked "status=$status up=$astrbot_up/$snowluma_up dash=$dash ws6199=$ws qq_login=$login_state jobs=$(echo "$jobs" | tr -d '\n' | head -c 100)"

# 自愈（v2）：
# - astrbot 侧问题照旧重启 astrbot；
# - SnowLuma 容器 DOWN 用 docker start 拉起（登录态在卷里，重启安全）；
# - QQ_OFFLINE（awaiting login）= 登录态凭据失效，重启无法修复（10-29 16:51 s26 实证），
#   只告警等人工扫码，绝不自动重启 snowluma。
case "$status" in
  ASTRBOT_DOWN) append "ALERT self-heal: up astrbot"; docker compose up -d astrbot >>"$LOG" 2>&1 ;;
  SNOWLUMA_DOWN) append "ALERT self-heal: start snowluma"; docker start snowluma >>"$LOG" 2>&1 ;;
  DASHBOARD_UNREACH) append "ALERT dashboard unreachable; restart astrbot"; docker restart astrbot >>"$LOG" 2>&1 ;;
  QQ_OFFLINE)
    # 登录态失效，需人工扫码（勿自动重启，见 case 上方注释）
    append "ALERT QQ_OFFLINE: SnowLuma 报 awaiting login（登录态失效）—— 需人工扫码（noVNC），勿自动重启"
    date '+%F %T' > "$APP/logs/needs-rescan" 2>/dev/null || true
    # 微信推送：掉线即通知；30 分钟内只推一次；恢复在线后清除标记（见脚本末尾）
    if [ ! -f "$SENTFLAG" ] || [ $(( $(date +%s) - $(stat -c %Y "$SENTFLAG" 2>/dev/null || echo 0) )) -gt 1800 ]; then
      wechat_push && date '+%F %T' > "$SENTFLAG"
    fi
    ;;
  NO_WS_LINK)
    # SnowLuma 侧自带 5 秒重连；链路长期不通通常是对端（AstrBot）的问题
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
      append "ALERT ws link down but astrbot is listening -> 等 SnowLuma 自动重连；若下轮仍断则 QQ 大概率掉线"
    else
      append "ALERT ws link down and no 6199 listener; restart astrbot"
      docker restart astrbot >>"$LOG" 2>&1
    fi
    ;;
esac

# 恢复在线：清掉"已推送"标记，让下次掉线能再推
if [ "$status" = OK ] && [ -f "$SENTFLAG" ]; then
  rm -f "$SENTFLAG"
  append "wechat: back online, sent-flag cleared"
fi

# 在线时同步 OneBot HTTP token（miruku_backfill 空窗补拉要用）
# token 只读宿主卷里的 onebot.json（容器内看不见宿主路径），变了就同步一次。
# 不放在 QQ_OFFLINE 分支：SnowLuma 没登录时配置可能还在生成中，同步到半成品 token 更糟。
if [ "$status" = OK ]; then
  sync_out=$("$APP/server/sync-onebot-token.sh" 2>&1) || sync_out="TOKEN_SYNC=FAIL"
  case "$sync_out" in
    TOKEN_SYNC=OK*) : ;;            # 正常，不写日志（每 5 分钟一条噪音没意义）
    *) append "WARN onebot token sync: $sync_out" ;;
  esac
fi
