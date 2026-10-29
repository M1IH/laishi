#!/usr/bin/env python3
# 面板状态聚合（服务器侧执行，输出单行 JSON；所有 QQ 号一律掩码，绝不输出凭据值）
# 2026-10-29: SnowLuma 版 —— QQ 在线状态改从 snowluma 容器 hook 日志判断，
#             napcat 保留为 stopped 对照；心跳 timer 已停（SnowLuma 场景未改造）。
import json
import os
import pathlib
import re
import socket
import subprocess

DATA = "/opt/miruku/astrbot/data"


def sh(cmd, t=12):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t).stdout
    except Exception:
        return ""


def mask(v):
    return re.sub(r"(\d{3})\d{4}(\d{3})", r"\1***\2", str(v or ""))


def jload(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


out = {}

# ---- 主机 ----
mem = sh("free -m").splitlines()
m1 = mem[1].split() if len(mem) > 1 else ["0"] * 7
m2 = mem[2].split() if len(mem) > 2 else ["0"] * 3
out["host"] = {
    "hostname": socket.gethostname(),
    "os": sh(". /etc/os-release; echo $PRETTY_NAME").strip(),
    "kernel": sh("uname -r").strip(),
    "cpu_cores": (sh("nproc").strip() or "?"),
    "uptime": sh("uptime -p").strip().replace("up ", ""),
    "load": (sh("cat /proc/loadavg").split() + ["", "", ""])[:3],
    "mem_total_mb": int(m1[1]), "mem_used_mb": int(m1[2]), "mem_avail_mb": int(m1[6]),
    "swap_total_mb": int(m2[1]),
    "disk": sh("df -h / | awk 'NR==2{print $2\" total / \"$3\" used / \"$4\" free\"}'").strip(),
    "ip": (sh("hostname -I").split() or [""])[0],
}

# ---- 服务 ----
units = {}
for u in ("docker", "miruku-heartbeat.timer"):
    units[u] = (sh(f"systemctl is-active {u}").strip() or "unknown")
containers = {}
for c in ("astrbot", "snowluma", "napcat"):
    st = sh(f"docker inspect -f '{{{{.State.Status}}}}|{{{{.RestartCount}}}}|{{{{.State.StartedAt}}}}' {c}").strip()
    parts = st.split("|")
    containers[c] = ({"status": parts[0], "restarts": parts[1], "started": parts[2]}
                     if len(parts) == 3 else {"status": "missing", "restarts": "?", "started": ""})
out["services"] = {"systemd": units, "containers": containers}

# ---- 链路：进 astrbot 容器读它自己 netns（宿主 ss 查不到跨容器连接）----
ws = sh("docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01").strip()
ls_ = sh("docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 0A").strip()
out["link"] = {"ws6199_established": int(ws) if ws.isdigit() else -1,
               "ws6199_listen": int(ls_) if ls_.isdigit() else -1}

# ---- QQ 在线（SnowLuma hook 日志）：最后一条 login 相关行定生死 ----
hook = sh('docker exec snowluma sh -c "grep -hE \'login detected|awaiting login\' /app/data/logs/*.log 2>/dev/null" | tail -3')
hlines = [l.strip() for l in hook.splitlines() if l.strip()]
last_hook = hlines[-1] if hlines else ""
wscl = sh('docker exec snowluma sh -c "grep -h \'WS-Client\' /app/data/logs/*.log 2>/dev/null" | tail -3')
wlines = [l.strip() for l in wscl.splitlines() if l.strip()]
last_ws = wlines[-1] if wlines else ""
ab_ws = sh("docker logs astrbot --tail 300 2>&1 | grep -E 'aiocqhttp' | tail -2")
out["qq"] = {
    "online": ("login detected" in last_hook) if last_hook else None,  # None=未知
    "detail": last_hook,
    "wsclient": ("connected" if ("connected" in last_ws and "closed" not in last_ws)
                 else ("disconnected" if last_ws else "unknown")),
    "wsclient_detail": last_ws,
    "adapter_log": ab_ws.strip()[-300:],
}

# ---- 机器人 ----
cmd = jload(os.path.join(DATA, "cmd_config.json"))
plats = []
for p in cmd.get("platform", []):
    c = p.get("config") if isinstance(p.get("config"), dict) else p
    plats.append({"id": p.get("id"), "type": p.get("type"), "enable": p.get("enable"),
                  "ws": f"{c.get('ws_reverse_host')}:{c.get('ws_reverse_port')}"})
pc = jload(os.path.join(DATA, "config", "astrbot_plugin_proactive_chat_config.json"))
fs = pc.get("friend_settings", {}) or {}
sch = fs.get("schedule_settings", {}) or {}
ats = fs.get("auto_trigger_settings", {}) or {}
jobs = []
jobs_raw = sh('docker exec astrbot python3 -c "import urllib.request;'
              "print(urllib.request.urlopen('http://127.0.0.1:4100/api/jobs',timeout=6).read().decode())\"")
try:
    for j in json.loads(jobs_raw.strip().splitlines()[-1]).get("jobs", []):
        jobs.append({"umo": mask(j.get("id")), "next": (j.get("next_run_time") or "")[:19],
                     "unanswered": j.get("unanswered_count")})
except Exception:
    pass
kc = jload(os.path.join(DATA, "config", "astrbot_plugin_miruku_knowledge_config.json"))
kroot = kc.get("knowledge_root") or ""
entries = 0
if kroot:
    host_db = kroot.replace("/AstrBot/data", DATA) + "/miruku_knowledge.sqlite3"
    n = sh(f"sqlite3 {host_db} 'select count(*) from entries' 2>/dev/null").strip()
    entries = int(n) if n.isdigit() else 0
pdir = pathlib.Path(DATA) / "plugins"
mc = jload(os.path.join(DATA, "config", "meme_manager_config.json"))
gen = mc.get("generation") or {}
emo = gen.get("emotion") or {}
msg = gen.get("message") or {}
llm = emo.get("llm") if isinstance(emo.get("llm"), dict) else {}
out["bot"] = {
    "platforms": plats,
    "providers": [{"id": x.get("id"), "enable": x.get("enable")} for x in cmd.get("provider", [])],
    "provider_sources": [{"id": x.get("id"), "base": x.get("api_base", ""),
                          "cred": "SET" if x.get("key") else "none"}
                         for x in cmd.get("provider_sources", [])],
    "persona": ((cmd.get("agent_runner") or {}).get("config", {}) or {}).get("persona", {})
               .get("persona_id"),
    "proactive": {
        "enable": fs.get("enable"),
        "recipients": [mask(x) for x in (fs.get("session_list") or [])],
        "interval_minutes": [sch.get("min_interval_minutes"), sch.get("max_interval_minutes")],
        "quiet_hours": sch.get("quiet_hours"),
        "max_unanswered": sch.get("max_unanswered_times"),
        "auto_trigger": ats.get("enable_auto_trigger"),
        "auto_trigger_after_minutes": ats.get("auto_trigger_after_minutes"),
    },
    "meme": {
        "probability": emo.get("probability"),
        "mixed_probability": msg.get("mixed_probability"),
        "max_memes": (emo.get("max_memes_per_message")
                      or gen.get("max_memes_per_message")),
        "emotion_llm": llm.get("provider_id") or emo.get("provider_id"),
    },
    "jobs": jobs,
    "knowledge": {"target_qq": mask(kc.get("target_qq")), "entries": entries},
    "plugins": sorted(p.name for p in pdir.iterdir() if p.is_dir()) if pdir.is_dir() else [],
}

# ---- 插件版本（读 metadata.yaml 的 version 行，不解析 YAML）----
vers = {}
for name in out["bot"]["plugins"]:
    m = pdir / name / "metadata.yaml"
    if m.is_file():
        for line in m.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("version:"):
                vers[name] = line.split(":", 1)[1].split("#", 1)[0].strip().strip('"')
                break
out["bot"]["plugin_versions"] = vers

# ---- 心跳最近几行（timer 停用中，仅作历史参考）----
out["heartbeat"] = [mask(l) for l in sh("tail -8 /var/log/miruku-heartbeat.log").splitlines() if l.strip()]
out["heartbeat_active"] = units.get("miruku-heartbeat.timer") == "active"

# ---- 是否需要人工扫码（遗留机制，heartbeat 停用后不再产生）----
mark = pathlib.Path("/opt/miruku/logs/needs-rescan")
out["needs_rescan"] = mark.read_text(encoding="utf-8").strip() if mark.is_file() else None

print(json.dumps(out, ensure_ascii=False))
