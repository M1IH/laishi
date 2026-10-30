import json
from pathlib import Path

p = Path('/AstrBot/data/plugin_data/miruku_outbound/b50_miruku.json')
d = json.load(open(p, encoding='utf-8'))
print('top:', type(d).__name__, len(d))
if isinstance(d, dict):
    for k, v in list(d.items())[:6]:
        print(' ', k, '->', type(v).__name__, (len(v) if isinstance(v, (dict, list)) else repr(v)[:40]))
else:
    print(' sample:', json.dumps(d[0], ensure_ascii=False)[:120])
