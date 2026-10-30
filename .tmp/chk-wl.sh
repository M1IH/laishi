#!/bin/bash
set -uo pipefail
docker exec astrbot python3 -c "
import json
cfg = json.load(open('/AstrBot/data/cmd_config.json', encoding='utf-8-sig'))
ps = cfg.get('platform_settings', {})
print('enable_id_white_list =', ps.get('enable_id_white_list'))
print('id_whitelist =', json.dumps(ps.get('id_whitelist'), ensure_ascii=False, indent=1))
print('wl_ignore_admin_on_friend =', ps.get('wl_ignore_admin_on_friend'))
print('friend_message_needs_wake_prefix =', ps.get('friend_message_needs_wake_prefix'))
"
