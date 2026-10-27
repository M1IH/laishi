#!/usr/bin/env bash
echo "===== 主动消息：今天到底有没有'到点主动发出'过 ====="
docker logs astrbot --since 10h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '开始生成第|已发送完成|未能送达|自动触发任务已创建|满足条件' | tail -20 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'

echo ""
echo "===== 主动消息：排期时间有没有真的到点 ====="
docker logs astrbot --since 10h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -E '安排下一次主动消息' | tail -6 \
  | sed -E 's/([0-9]{3})[0-9]{4}([0-9]{3})/\1***\2/g'

echo ""
echo "===== 关键：现在几点，下一个排期是几点 ====="
date '+  现在 %F %T'
curl -s --max-time 6 http://127.0.0.1:4100/api/jobs | python3 -c "
import sys,json
d=json.load(sys.stdin)
for j in d.get('jobs',[]):
    print('  下次:', j.get('next_run_time','')[:19], '| 未回复:', j.get('unanswered_count'))
"

echo ""
echo "===== 表情：为什么总是空列表 ====="
docker logs astrbot --since 10h 2>&1 | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -iE 'meme' | grep -viE 'DEPRECATION' | grep -E '分类|标签|列表|选择|概率|跳过|无候选' | tail -14

echo ""
echo "===== 表情插件当前配置核心项 ====="
python3 -c "
import json
d=json.load(open('/opt/miruku/astrbot/data/config/meme_manager_config.json',encoding='utf-8-sig'))
g=d.get('generation',{})
print('  scope        =', g.get('trigger',{}).get('scope'))
print('  prob         =', g.get('emotion',{}).get('probability'))
print('  max_per_msg  =', g.get('emotion',{}).get('max_memes_per_message'))
print('  emotion.llm  =', g.get('emotion',{}).get('llm',{}).get('enabled'))
print('  semantic     =', d.get('semantic',{}).get('enabled'), '| embedding:', repr(d.get('semantic',{}).get('embedding_provider_id')))
"
