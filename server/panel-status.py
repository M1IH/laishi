#!/usr/bin/env python3
# 面板状态聚合（服务器侧执行，输出单行 JSON；所有 QQ 号一律掩码，绝不输出凭据值）
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
    "disk": sh("df -h / | awk 'NR==2{print $2\" 总 / \"$3\" 已用 / \"$4\" 可用\"}'").strip(),
    "ip": (sh("hostname -I").split() or [""])[0],
}

# ---- 服务 ----
units = {}
for u in ("miruku-xvfb", "miruku-desktop", "miruku-vnc", "miruku-novnc",
          "miruku-heartbeat.timer", "docker"):
    units[u] = (sh(f"systemctl is-active {u}").strip() or "unknown")
containers = {}
for c in ("astrbot", "napcat"):
    st = sh(f"docker inspect -f '{{{{.State.Status}}}}|{{{{.RestartCount}}}}|{{{{.State.StartedAt}}}}' {c}").strip()
    parts = st.split("|")
    containers[c] = ({"status": parts[0], "restarts": parts[1], "started": parts[2]}
                     if len(parts) == 3 else {"status": "missing", "restarts": "?", "started": ""})
out["services"] = {"systemd": units, "containers": containers}

# ---- 链路：进 astrbot 容器读它自己 netns（宿主 ss 查不到跨容器连接）----
ws = sh("docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 01").strip()
ls = sh("docker exec astrbot python3 /AstrBot/data/laishi/ws_probe.py 0A").strip()
out["link"] = {"ws6199_established": int(ws) if ws.isdigit() else -1,
               "ws6199_listen": int(ls) if ls.isdigit() else -1}

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
kc = jload(os.path.join(DATA, "config", "astrbot_plugin_miruku_knowledge_config.json"))
jobs = []
try:
    for j in json.loads(sh("curl -s --max-time 6 http://127.0.0.1:4100/api/jobs") or "{}").get("jobs", []):
        jobs.append({"umo": mask(j.get("id")), "next": (j.get("next_run_time") or "")[:19],
                     "unanswered": j.get("unanswered_count")})
except Exception:
    pass
kroot = kc.get("knowledge_root") or ""
entries = 0
if kroot:
    host_db = kroot.replace("/AstrBot/data", DATA) + "/miruku_knowledge.sqlite3"
    n = sh(f"sqlite3 {host_db} 'select count(*) from entries' 2>/dev/null").strip()
    entries = int(n) if n.isdigit() else 0
pdir = pathlib.Path(DATA) / "plugins"
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
                vers[name] = line.split(":", 1)[1].strip()
                break
out["bot"]["plugin_versions"] = vers

# ---- 心跳最近几行 ----
# 心跳日志里带插件返回的原始 jobs JSON（内含未掩码 UMO），必须过一遍掩码
out["heartbeat"] = [mask(l) for l in sh("tail -8 /var/log/miruku-heartbeat.log").splitlines() if l.strip()]

# ---- 是否需要人工扫码 ----
# QQ 掉线时心跳会写 /opt/miruku/logs/needs-rescan；面板据此显示红条提醒，
# 不必让人去翻日志（2026-10-27 那次掉线就是这么被漏了 3 小时的）。
mark = pathlib.Path("/opt/miruku/logs/needs-rescan")
out["needs_rescan"] = mark.read_text(encoding="utf-8").strip() if mark.is_file() else None

# 最近一次心跳的状态关键字（OK / QQ_OFFLINE / NO_WS_LINK ...）
last_status = ""
for line in reversed(out["heartbeat"]):
    if "status=" in line:
        last_status = line.split("status=", 1)[1].split()[0]
        break
out["last_status"] = last_status

print(json.dumps(out, ensure_ascii=False))
