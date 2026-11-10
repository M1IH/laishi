# -*- coding: utf-8 -*-
import io
import json

CFG = "/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json"
d = json.load(io.open(CFG, encoding="utf-8-sig"))
fs = d["friend_settings"]
e = fs["escalation_settings"]
print("enable", e["enable"])
print("p2", len(e["prompt_2"]), "p3", len(e["prompt_3"]))
print("rule3ok", "分级口径" in fs["context_settings"]["platform_history_prompt"])
print("base_len", len(fs["proactive_prompt"]))
print("head2", e["prompt_2"][:40])
print("head3", e["prompt_3"][:40])

SRC = "/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/services/llm_service.py"
src = io.open(SRC, encoding="utf-8").read()
print("has_func", "def pick_proactive_prompt" in src)
print("has_call", "pick_proactive_prompt(\n            session_config, unanswered_count" in src)
print("has_log", "主动消息等级={prompt_level}" in src)
