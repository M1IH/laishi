#!/usr/bin/env bash
# 强制重排：删掉旧任务再让它按新配置重建
set -uo pipefail
echo "== 重排前 =="
curl -s --max-time 6 http://127.0.0.1:4100/api/jobs | python3 -c "
import sys,json,datetime
d=json.load(sys.stdin); now=datetime.datetime.now()
for j in d.get('jobs',[]):
    t=j.get('next_run_time','')[:19]
    print('  ', t, '（{:+.0f} 分钟）'.format((datetime.datetime.fromisoformat(t)-now).total_seconds()/60) if t else '')
"

UMO="miruku:FriendMessage:10000001"

echo ""
echo "== 取消旧任务 =="
curl -s -X DELETE --max-time 10 "http://127.0.0.1:4100/api/jobs/${UMO}" | head -c 200; echo

echo ""
echo "== 重启 astrbot 让插件按新配置重建排期 =="
docker restart astrbot >/dev/null 2>&1
for i in $(seq 1 20); do
  sleep 5
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 http://127.0.0.1:6185/api/v1/system-config 2>/dev/null || echo 000)
  case "$code" in 401|200) echo "  就绪 t+$((i*5))s"; break ;; esac
done
sleep 8

echo ""
echo "== 重排后 =="
curl -s --max-time 8 http://127.0.0.1:4100/api/jobs | python3 -c "
import sys,json,datetime
d=json.load(sys.stdin); now=datetime.datetime.now()
js=d.get('jobs',[])
print('  jobs 数:', len(js))
for j in js:
    t=j.get('next_run_time','')[:19]
    if t:
        mins=(datetime.datetime.fromisoformat(t)-now).total_seconds()/60
        print('  下次:', t, '（{:+.0f} 分钟）'.format(mins))
    print('  配置的间隔:', j.get('schedule_min_interval_minutes'), '-', j.get('schedule_max_interval_minutes'))
"

echo ""
echo "== 插件日志：重建排期 =="
docker logs astrbot --since 2m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '主动消息' | grep -E '安排|恢复|设置自动' | tail -4 \
  | sed -E 's/([0-9]{3})\d{4}([0-9]{3})/\1***\2/g'
