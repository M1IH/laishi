#!/usr/bin/env bash
# 下午问题排查：主动消息为何没发 / 表情为何没出
echo "===== 1. 当前时间与运行状态 ====="
date
docker ps --format '  {{.Names}}: {{.Status}}'

echo ""
echo "===== 2. 主动消息任务（关键：有没有排期）====="
curl -s --max-time 8 http://127.0.0.1:4100/api/jobs | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
jobs = d.get('jobs', [])
print('  jobs 数量:', len(jobs))
for j in jobs:
    print('   ', re.sub(r'(\d{3})\d{4}(\d{3})', r'\1***\2', j.get('id','')),
          '| next:', j.get('next_run_time','')[:19],
          '| unanswered:', j.get('unanswered_count'))
    print('    schedule:', j.get('schedule_min_interval_minutes'), '-', j.get('schedule_max_interval_minutes'), 'min',
          '| quiet:', j.get('quiet_hours'))
"

echo ""
echo "===== 3. 今天下午主动消息的实际发送记录 ====="
docker logs astrbot --since 8h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '主动消息' | grep -viE 'DEPRECATION' | tail -20 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'

echo ""
echo "===== 4. 下午有没有收到/发出过消息（判断链路）====="
docker logs napcat --since 8h 2>&1 | grep -vE '^[0-9a-f]{40,}$' | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '接收 <-|发送 ->' | tail -12 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'

echo ""
echo "===== 5. 表情插件是否被调用过 ====="
docker logs astrbot --since 8h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme|search_memes|表情' | grep -viE 'DEPRECATION|Loaded plugin|Loading plugin' | tail -10 || echo "  （无表情相关日志）"
