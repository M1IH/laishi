import json
import subprocess

# 1) QQ 在线状态
logs = subprocess.run(
    ["docker", "exec", "snowluma", "sh", "-c",
     "grep -hE 'login detected|awaiting login' /app/data/logs/*.log 2>/dev/null | tail -2"],
    capture_output=True, text=True).stdout.strip()
print("QQ:", logs or "(no logs)")
ws = subprocess.run(
    ["docker", "exec", "snowluma", "sh", "-c",
     "grep -h 'WS-Client' /app/data/logs/*.log 2>/dev/null | tail -1"],
    capture_output=True, text=True).stdout.strip()
print("WS:", ws or "(none)")

# 2) jobs 当前排期
out = subprocess.run(
    ["docker", "exec", "astrbot", "python3", "-c",
     "import urllib.request,json;"
     "print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:4100/api/jobs')),ensure_ascii=False)[:400])"],
    capture_output=True, text=True)
print("JOBS:", out.stdout.strip() or out.stderr.strip()[:200])

# 3) 出站闸门插件最近日志
lg = subprocess.run(
    ["docker", "logs", "astrbot", "--since", "20h"],
    capture_output=True, text=True).stdout
gl = [l for l in lg.splitlines() if "miruku_outbound" in l]
print("OUTBOUND_LOG(最近20h):")
for l in gl[-5:]:
    print(" ", l[-150:])
