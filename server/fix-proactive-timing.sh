#!/usr/bin/env bash
set -e
echo "== 调整主动消息节奏（90-240 分钟 -> 30-75 分钟）=="
python3 - <<'PY'
import json
p = "/opt/miruku/astrbot/data/config/astrbot_plugin_proactive_chat_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
f = d["friend_settings"]
s = f["schedule_settings"]
a = f["auto_trigger_settings"]

before = (s.get("min_interval_minutes"), s.get("max_interval_minutes"),
          a.get("auto_trigger_after_minutes"))
# 原 90-240 太长：一下午（4 小时）最多 1-2 次，且每次回复都会重置排期。
# 改 30-75：正常聊天间隔下一次主动在半小时到一小时一刻之间，
# 既不频催，也不会"一下午没动静"。
s["min_interval_minutes"] = 30
s["max_interval_minutes"] = 75
# 静默自动触发 120 -> 60 分钟：他 1 小时没说话就主动找一次
a["auto_trigger_after_minutes"] = 60
a["enable_auto_trigger"] = True
# 保持不限制回复次数（OTTO 之前的决定）
s["max_unanswered_times"] = 0
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

after = (s["min_interval_minutes"], s["max_interval_minutes"],
         a["auto_trigger_after_minutes"])
print("  间隔:", before[0], "-", before[1], "->", after[0], "-", after[1], "分钟")
print("  静默触发:", before[2], "->", after[2], "分钟")
print("  quiet_hours:", s.get("quiet_hours"), "（不动）")
print("  max_unanswered:", s.get("max_unanswered_times"), "（不限制，不动）")
PY

echo ""
echo "== 重启 astrbot 应用配置 =="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 20); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done

echo ""
echo "== 新的排期 =="
sleep 5
curl -s --max-time 8 http://127.0.0.1:4100/api/jobs | python3 -c "
import sys,json,datetime
d=json.load(sys.stdin)
now=datetime.datetime.now()
for j in d.get('jobs',[]):
    nxt=j.get('next_run_time','')[:19]
    print('  下次:', nxt)
    try:
        t=datetime.datetime.fromisoformat(nxt)
        print('  距现在: {:.0f} 分钟'.format((t-now).total_seconds()/60))
    except Exception: pass
print('  jobs 数:', len(d.get('jobs',[])))
"
