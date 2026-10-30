#!/bin/bash
set -uo pipefail
docker exec astrbot python3 -c "
import json
cfg = json.load(open('/AstrBot/data/cmd_config.json', encoding='utf-8-sig'))
print('id_whitelist =', json.dumps(cfg['platform_settings']['id_whitelist'], ensure_ascii=False))
"
