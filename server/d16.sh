#!/usr/bin/env bash
# 验证她到底能不能发出表情：看插件怎么触发发送、有哪些触发路径
echo "== 插件的发送指令/触发方式 =="
grep -oE '"[^"]*表情[^"]*"' /opt/miruku/astrbot/data/plugins/meme_manager/main.py 2>/dev/null | head -12

echo ""
echo "== 注册的指令（Mixin 绑定的 15 个）=="
docker logs astrbot --since 10m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'Mixin|绑定到插件' | tail -3

echo ""
echo "== 注册给 LLM 的工具（AI 自主发图靠它）=="
docker logs astrbot --since 10m 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'Added llm tool|search_memes' | tail -5

echo ""
echo "== 关键：AI 发图是否需要 LLM 主动调工具（需要工具权限/白名单）=="
python3 - <<'PY'
import json
p = "/opt/miruku/astrbot/data/cmd_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
ps = d.get("provider_settings", {})
for k in ("enable", "display_reasoning_text"):
    print(f"  provider_settings.{k} = {ps.get(k)}")
# 工具相关
ar = (d.get("agent_runner") or {}).get("config", {})
print("  agent_runner.runner_type =", (d.get("agent_runner") or {}).get("runner_type"))
print("  tool/permission 相关键:", [k for k in ar if "tool" in k.lower() or "perm" in k.lower()])
PY
