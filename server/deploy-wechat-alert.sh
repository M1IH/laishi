#!/usr/bin/env bash
# 微信掉线告警：向 heartbeat.sh 注入推送逻辑 + 写密钥 + 发测试消息
#
# 用法：SCT_SENDKEY=SCT123456XXXX bash deploy-wechat-alert.sh
#       （或先改下面的 KEY 变量）
#
# 渠道：Server酱（sct.ftqq.com）—— 免费每天 5 条，微信服务号接收
#       也兼容 PushPlus：改 PUSH_URL 模板即可（见下方注释）
#
# 行为：
#   1. 密钥写 /opt/miruku/.wechat-sendkey（600）
#   2. 备份 heartbeat.sh，在 QQ_OFFLINE 分支注入推送（幂等：已注入则跳过）
#   3. 防轰炸：一个掉线事件只推一次（标记文件 /opt/miruku/logs/wechat-sent，
#      30 分钟内不重推；恢复在线后标记自动清除）
#   4. 发一条测试消息确认 SendKey 有效
set -euo pipefail

KEY="${SCT_SENDKEY:-}"
HEARTBEAT=/opt/miruku/server/heartbeat.sh
KEYFILE=/opt/miruku/.wechat-sendkey
SENTFLAG=/opt/miruku/logs/wechat-sent
NEEDS_RESCAN=/opt/miruku/logs/needs-rescan

if [ -z "$KEY" ] && [ -f "$KEYFILE" ]; then
  KEY=$(cat "$KEYFILE")
fi
if [ -z "$KEY" ]; then
  echo "[FAIL] 未提供 SendKey。用法: SCT_SENDKEY=SCTxxxx bash $0"
  exit 1
fi

echo "== 1. 写密钥 =="
printf '%s' "$KEY" > "$KEYFILE"
chmod 600 "$KEYFILE"
echo "  -> $KEYFILE (${#KEY} 字符)"

echo ""
echo "== 2. 向 heartbeat.sh 注入推送 =="
if grep -q "wechat_push" "$HEARTBEAT"; then
  echo "  已注入过，跳过"
else
  cp -a "$HEARTBEAT" "$HEARTBEAT.bak.$(date +%Y%m%d%H%M%S)"
  # 在 QQ_OFFLINE 分支的 needs-rescan 标记之后插入推送调用
  python3 - "$HEARTBEAT" <<'PYEOF'
import io, sys
path = sys.argv[1]
src = io.open(path, encoding="utf-8").read()
anchor = 'date \'+%F %T\' > "$APP/logs/needs-rescan" 2>/dev/null || true'
inject = anchor + '''
    # 微信推送（2026-10-28）：掉线即通知，不等 OTTO 发现机器人失联
    # 防轰炸：30 分钟内只推一次；恢复在线后清除标记（见脚本末尾）
    if [ ! -f "$SENTFLAG" ] || [ $(( $(date +%s) - $(stat -c %Y "$SENTFLAG" 2>/dev/null || echo 0) )) -gt 1800 ]; then
      wechat_push "$idle_min" && date '+%F %T' > "$SENTFLAG"
    fi'''
if src.count(anchor) != 1:
    raise SystemExit("  !! QQ_OFFLINE 锚点不唯一（%d 处），中止" % src.count(anchor))
src = src.replace(anchor, inject)

# 注入 wechat_push 函数定义（放在 append() 定义之后）
fn_anchor = 'append(){ echo "$(NOW) $*" >> "$LOG"; }'
fn_def = fn_anchor + '''

# Server酱推送：https://sct.ftqq.com/
# 失败只写日志不报错（推送挂了不能影响心跳本身）
wechat_push(){
  local key idle
  key=$(cat "$KEYFILE" 2>/dev/null) || return 0
  idle="${1:-?}"
  local title="Miruku 掉线了"
  local desc="QQ 已 ${idle} 分钟无活动，需要重新扫码。"
  desc="${desc}%0A打开面板（桌面快捷方式）→ NapCat 扫码页扫一下即可。"
  curl -s -m 10 -X POST "https://sctapi.ftqq.com/${key}.send" \\
    -d "title=${title}" -d "desp=${desc}" >/dev/null 2>&1 || \\
    append "WARN wechat push failed"
}'''
if src.count(fn_anchor) != 1:
    raise SystemExit("  !! append() 锚点不唯一（%d 处），中止" % src.count(fn_anchor))
src = src.replace(fn_anchor, fn_def)

# 恢复在线时清除标记（放在 case 块之后、脚本结尾之前）
tail_anchor = "esac"
tail_inject = '''esac

# 恢复在线：清掉"已推送"标记，让下次掉线能再推
if [ "$status" = OK ] && [ -f "$SENTFLAG" ]; then
  rm -f "$SENTFLAG"
  append "wechat: back online, sent-flag cleared"
fi'''
if src.count(tail_anchor) < 1:
    raise SystemExit("  !! 找不到 case 结束的 esac")
# 只替换最后一个 esac（case 块的结束）
idx = src.rfind(tail_anchor)
src = src[:idx] + tail_inject + src[idx+len(tail_anchor):]

io.open(path, "w", encoding="utf-8").write(src)
print("  已注入：wechat_push 函数 + QQ_OFFLINE 推送 + 恢复清标记")
PYEOF
fi

echo ""
echo "== 3. bash -n 语法自检 =="
bash -n "$HEARTBEAT" && echo "  OK"

echo ""
echo "== 4. 发测试消息 =="
HTTP=$(curl -s -m 10 -o /tmp/wt.out -w '%{http_code}' -X POST "https://sctapi.ftqq.com/${KEY}.send" -d "title=Miruku 告警测试" -d "desp=如果你在微信看到这条，说明掉线告警已通。%0A这条是测试，删掉即可。")
BODY=$(cat /tmp/wt.out 2>/dev/null | head -c 200)
if [ "$HTTP" = "200" ]; then
  echo "  测试消息已发出（HTTP $HTTP）"
  echo "  响应: $BODY"
  echo "  请看微信「方糖」服务号是否收到"
else
  echo "  [FAIL] HTTP $HTTP: $BODY"
  echo "  检查 SendKey 是否正确"
  exit 1
fi

echo ""
echo "== 5. 下一步 =="
echo "  心跳脚本下次被 timer 触发（≤5 分钟）自动生效，无需重启任何服务。"
echo "  想立刻验证全链路：手动塞一个假掉线标记——"
echo "    touch /opt/miruku/logs/needs-rescan"
echo "    rm -f /opt/miruku/logs/wechat-sent"
echo "    systemctl start miruku-heartbeat.service  # 或等下一次 timer"
echo "  然后微信应收到「Miruku 掉线了」。验证完删掉 needs-rescan。"
echo ""
echo "  回滚：cp $HEARTBEAT.bak.* $HEARTBEAT && rm -f $KEYFILE"
