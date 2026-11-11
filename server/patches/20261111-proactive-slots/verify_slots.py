# -*- coding: utf-8 -*-
"""线上回读：确认时段配置、prompt 长度、以及每个会话算出的下一次触发时间。"""
import io
import json
import sys
import time
import zoneinfo
from datetime import datetime

root = "/AstrBot/data/plugins/astrbot_plugin_proactive_chat"
sys.path.insert(0, "/AstrBot/data/plugins")

cfg = json.loads(
    io.open(
        "/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json",
        encoding="utf-8-sig",
    ).read()
)
sch = cfg["friend_settings"]["schedule_settings"]
print("slots_enable:", sch.get("slots_enable"))
print("slots:", sch.get("slots"))
print("jitter:", sch.get("slot_jitter_minutes"))
print("prompt_len:", len(cfg["friend_settings"]["proactive_prompt"]))
print("prompt_has_short:", "像「在干嘛呢」这样只问一句也可以" in cfg["friend_settings"]["proactive_prompt"])

src = io.open(root + "/utils/time_utils.py", encoding="utf-8").read()
print("has_next_slot_trigger:", "def next_slot_trigger(" in src)
sched_src = io.open(root + "/core/services/scheduler_service.py", encoding="utf-8").read()
print("has_slot_target:", "_slot_target" in sched_src)

# 直接算未来 4 次，验证窗口
ns = {}
body = src[src.index("def _parse_hhmm(") : src.index("def local_day_key(")]
frag = src[src.index("def parse_slot_list(") :]
header = "import random\nimport zoneinfo\nfrom datetime import datetime, timedelta\n_DAY_MINUTES = 1440\n"
exec(header + body + frag, ns)

tz = zoneinfo.ZoneInfo("Asia/Shanghai")
now = time.time()
print("\n--- 从当前时刻起连算 5 次 ---")
for i in range(5):
    ts = ns["next_slot_trigger"](sch["slots"], sch["slot_jitter_minutes"], now, tz, sch.get("quiet_hours", ""))
    if ts is None:
        print("  None")
        break
    print("  ", datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M:%S"))
    now = ts + 1

state = json.loads(
    io.open(
        "/AstrBot/data/plugin_data/astrbot_plugin_proactive_chat/session_data.json",
        encoding="utf-8",
    ).read()
)
print("\n--- session_data ---")
for k, v in state.items():
    if not isinstance(v, dict):
        continue
    nxt = v.get("next_trigger_time")
    when = (
        datetime.fromtimestamp(nxt, tz).strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(nxt, (int, float))
        else None
    )
    print(f"{k}: count={v.get('unanswered_count')} date={v.get('unanswered_date')} next={when}")
