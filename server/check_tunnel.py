# -*- coding: utf-8 -*-
"""隧道端到端验证：本机回环四个端口现在必须全部经隧道到云端
（本机 AstrBot 已停，若还能回 200/401 说明隧道通）。只读。"""
import json
import urllib.error
import urllib.request

CHECKS = [
    ("astrbot", "http://127.0.0.1:6185/api/v1/system-config"),
    ("napcat-webui", "http://127.0.0.1:6099/webui/"),
    ("novnc", "http://127.0.0.1:6080/vnc.html"),
    ("proactive-console", "http://127.0.0.1:4100/api/jobs"),
]

for name, url in CHECKS:
    try:
        r = urllib.request.urlopen(url, timeout=8)
        body = r.read()[:120]
        print(f"{name:18s} {r.status} len={len(body)} {body[:80]!r}")
    except urllib.error.HTTPError as e:
        print(f"{name:18s} HTTP {e.code}（服务活着，需登录/重定向）")
    except Exception as e:
        print(f"{name:18s} FAIL {type(e).__name__} {str(e)[:60]}")

import psutil  # venv python has it
p = psutil.Process(568)
print("\nPID568:", p.name(), " ".join(p.cmdline())[:150])
