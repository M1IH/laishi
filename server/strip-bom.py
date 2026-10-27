# -*- coding: utf-8 -*-
"""去掉 heartbeat.sh 开头的 UTF-8 BOM（PS 5.1 的 Set-Content -Encoding UTF8 会加），
否则 shebang 失效、`bash script` 报 No such file or directory。"""
from pathlib import Path

p = Path("server/heartbeat.sh")
raw = p.read_bytes()
if raw.startswith(b"\xef\xbb\xbf"):
    p.write_bytes(raw[3:])
    print("[ok] 已移除 BOM")
else:
    print("[ok] 无 BOM，无需处理")

# 同时确认没有 CRLF
data = p.read_bytes()
print("  CRLF:", data.count(b"\r\n"), " LF:", data.count(b"\n"))
