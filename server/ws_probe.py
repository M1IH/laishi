#!/usr/bin/env python3
# 6199 链路探针（在 astrbot 容器内执行：读自己 netns 的 /proc/net/tcp）
# 0x1837 = 6199；01 = ESTABLISHED，0A = LISTEN
import sys

state = sys.argv[1] if len(sys.argv) > 1 else "01"
n = 0
for f in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        with open(f) as fh:
            for line in fh.read().splitlines()[1:]:
                p = line.split()
                if p[1].endswith(":1837") and p[3] == state:
                    n += 1
    except OSError:
        pass
print(n)
