# -*- coding: utf-8 -*-
"""把线上主动消息提示词原样打出来，便于逐字比对。"""
import io
import json

P = "/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json"
d = json.load(io.open(P, encoding="utf-8-sig"))
for key in ("friend_settings", "group_settings"):
    prompt = d[key]["proactive_prompt"]
    print("=" * 20, key, len(prompt))
    print(prompt)
    print("=" * 20, "repr")
    print(repr(prompt))
