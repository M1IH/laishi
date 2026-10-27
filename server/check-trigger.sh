#!/usr/bin/env bash
echo "===== 自动触发器状态（这是现在唯一的主主动机制）====="
curl -s --max-time 8 http://127.0.0.1:4100/api/status | python3 -c "
import sys,json,datetime
d=json.load(sys.stdin)
print('  scheduler_running:', d.get('scheduler_running'))
print('  jobs_count:', d.get('jobs_count'))
print('  auto_trigger_timers:', d.get('auto_trigger_timers'))
for c in d.get('auto_trigger_cards', []):
    rem=c.get('remaining_seconds',0)
    print('  卡片:', c.get('session_id','')[:35])
    print('    剩余: {:.0f} 分钟'.format(rem/60), '| 状态:', c.get('status'))
    print('    after_minutes:', c.get('auto_trigger_after_minutes'))
"
