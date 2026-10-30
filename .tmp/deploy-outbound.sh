#!/bin/bash
# 出站闸门部署 v2：宿主卷直接写入（容器内路径 /AstrBot/... = 宿主 /opt/miruku/astrbot/data/...）
set -uo pipefail
HPLUGIN="/opt/miruku/astrbot/data/plugins/astrbot_plugin_miruku_outbound"
HDATA="/opt/miruku/astrbot/data/plugin_data/miruku_outbound"
CPLUGIN="/AstrBot/data/plugins/astrbot_plugin_miruku_outbound"
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p /opt/miruku/backups

echo "=== 0. 清理上一轮误建（容器 overlay 里的 /opt/miruku）==="
docker exec astrbot sh -c "rm -rf /opt/miruku/astrbot 2>/dev/null; ls /opt/miruku 2>/dev/null" || true

echo "=== 1. 宿主备份 ==="
if [ -d "$HPLUGIN" ]; then
  mkdir -p "/opt/miruku/backups/outbound-plugin-$TS" && cp -r "$HPLUGIN/." "/opt/miruku/backups/outbound-plugin-$TS/" && echo "backup -> outbound-plugin-$TS"
else
  echo "no previous plugin dir"
fi

echo "=== 2. 宿主落位（宿主卷直写）==="
mkdir -p "$HPLUGIN" "$HDATA"
cp /tmp/pb/main.py /tmp/pb/outbound_core.py /tmp/pb/metadata.yaml "$HPLUGIN/"
cp /tmp/mmdata/data/maimai/b50_miruku.json /tmp/mmdata/data/maimai/song_list.json "$HDATA/"
ls -la "$HPLUGIN" "$HDATA" | head -12

echo "=== 3. 容器内可见性 + 语法校验 ==="
docker exec astrbot python3 -c "import ast; [ast.parse(open('$CPLUGIN/' + f).read()) for f in ('main.py','outbound_core.py')]; print('SYNTAX_OK')" || exit 1

echo "=== 4. 生产数据 guard 冒烟 ==="
docker exec astrbot python3 -c "
import os, sys
os.environ['OUTBOUND_DATA_DIR'] = '/AstrBot/data/plugin_data/miruku_outbound'
sys.path.insert(0, '$CPLUGIN')
import outbound_core as ob
print('songs =', len(ob.song_levels()), '| truth =', len(ob._load_truth()))
cases = [
    ('<thought>内部</thought>没打上去 就随便玩玩', '没打上去 就随便玩玩'),
    ('来啊，几点开', '去不了，你看'),
    ('病み垢我打了 R285', '记不清了，没特意记'),
    ('我 R 值 14065，金框', None),
]
bad = 0
for src_text, want in cases:
    fixed, fb = ob.guard(src_text)
    ok = (fixed == want) if want is not None else (fixed == src_text)
    if not ok: bad += 1
    print(('PASS' if ok else 'FAIL'), repr(fixed), 'fb=', fb)
print('SMOKE', 'OK' if bad == 0 else 'FAILED')
"

echo "=== 5. 重启 AstrBot ==="
docker restart astrbot

echo "=== 6. armed 验证 ==="
sleep 45
docker logs astrbot --since 2m 2>&1 | grep -E 'miruku_outbound|skipping it' | tail -5
