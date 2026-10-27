#!/usr/bin/env bash
# 验证新判据能抓到掉线：不改真实状态，只把「最近活动时间」推旧再判定
# 做法：直接在 python 里复现判定逻辑，喂一个 3 小时前的时间戳，看是否判 OFFLINE

echo "== 判据逻辑自检（在线 / 掉线 两个输入）=="
python3 - <<'PY'
import datetime, re, subprocess

def idle_minutes_from(logline_dt):
    now = datetime.datetime.now()
    return int((now - logline_dt).total_seconds() / 60)

# 情形 1：5 分钟前有活动 → 应判在线（阈值 70）
recent = datetime.datetime.now() - datetime.timedelta(minutes=5)
idle1 = idle_minutes_from(recent)
print(f"  5 分钟前有活动  -> idle={idle1}  -> {'在线 OK' if idle1 < 70 else '误判掉线!'}")

# 情形 2：3 小时前有活动 → 应判掉线（复现 09:57~12:24 那次）
old = datetime.datetime.now() - datetime.timedelta(hours=3)
idle2 = idle_minutes_from(old)
print(f"  3 小时前有活动  -> idle={idle2} -> {'掉线告警 ✓' if idle2 >= 70 else '漏判!'}")

# 情形 3：边界 69 / 71 分钟
for m in (69, 71):
    t = datetime.datetime.now() - datetime.timedelta(minutes=m)
    i = idle_minutes_from(t)
    print(f"  {m} 分钟前      -> idle={i} -> {'在线' if i < 70 else '掉线'}")

assert idle1 < 70 and idle2 >= 70
print("  ✓ 判据能区分「在线」与「今天那次 3 小时掉线」")
PY

echo ""
echo "== 真实日志里的时间戳解析是否работает（抽最近一条）=="
LAST=$(docker logs napcat --since 150m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E 'ServerTime|接收 <-|发送 ->' | tail -1 \
  | grep -oE '^[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
echo "  抓到的时间戳: [$LAST]"
if [ -n "$LAST" ]; then
  TS=$(date -d "2026-$LAST" +%s)
  NOW=$(date +%s)
  echo "  解析为 epoch=$TS  距今 $(( (NOW-TS)/60 )) 分钟"
else
  echo "  ✗ 没抓到时间戳（解析逻辑有问题）"
fi
