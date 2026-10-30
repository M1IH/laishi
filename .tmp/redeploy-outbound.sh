#!/bin/bash
set -uo pipefail
HPLUGIN="/opt/miruku/astrbot/data/plugins/astrbot_plugin_miruku_outbound"
CPLUGIN="/AstrBot/data/plugins/astrbot_plugin_miruku_outbound"
cp /tmp/pb/main.py "$HPLUGIN/main.py"
docker exec astrbot python3 -c "import ast; ast.parse(open('$CPLUGIN/main.py').read()); print('SYNTAX_OK')" || exit 1
docker restart astrbot
sleep 45
docker logs astrbot --since 1m 2>&1 | grep -E 'miruku_outbound' | tail -2
