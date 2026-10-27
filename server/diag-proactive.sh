#!/usr/bin/env bash
echo "===== 主动消息：关键参数 ====="
python3 -c "
import json
d=json.load(open('/opt/miruku/astrbot/data/config/astrbot_plugin_proactive_chat_config.json',encoding='utf-8-sig'))
f=d.get('friend_settings',{})
s=f.get('schedule_settings',{})
a=f.get('auto_trigger_settings',{})
print('  enable             =', f.get('enable'))
print('  min_interval       =', s.get('min_interval_minutes'), '分钟')
print('  max_interval       =', s.get('max_interval_minutes'), '分钟')
print('  quiet_hours        =', s.get('quiet_hours'))
print('  max_unanswered     =', s.get('max_unanswered_times'))
print('  auto_trigger       =', a.get('enable_auto_trigger'))
print('  auto_after_minutes =', a.get('auto_trigger_after_minutes'))
print()
print('  session_list       =', f.get('session_list'))
"

echo ""
echo "===== 排期逻辑：为什么'回了就重置' ====="
echo "  日志实证：16:01-16:02 你每回一句，就'已取消任务 + 重新安排下一次'"
echo "  结果：聊得越勤 -> 排期越往后推 -> 一下午一条都不主动发"

echo ""
echo "===== 当前时间 vs 下次排期 ====="
date '+  现在: %F %T'
curl -s --max-time 6 http://127.0.0.1:4100/api/jobs | python3 -c "
import sys,json
d=json.load(sys.stdin)
for j in d.get('jobs',[]):
    print('  下次:', j.get('next_run_time','')[:19], '| 未回复:', j.get('unanswered_count'))
"
