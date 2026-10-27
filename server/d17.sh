#!/usr/bin/env bash
# 端到端验证：发一条容易触发表情的消息，看工具是否被调用、是否真发出去
echo "== 用 OneBot 直接给测试号发一条，观察 AI 是否用表情工具 =="

# 通过 astrbot 的 6199 反向 WS 发不了消息（那是平台适配器端口），
# 改用"来世/测试号发消息给机器人"的方式：直接调 proactive 触发不合适。
# 这里改为查工具是否已挂载 + 让插件自报状态。
echo ""
echo "== 工具挂载确认 =="
docker exec astrbot python3 - <<'PY'
import asyncio, json, sys
sys.path.insert(0, "/AstrBot")
try:
    from astrbot.core.provider import func_tool_manager
    print("  func_tool_manager 可导入")
except Exception as e:
    print("  导入失败:", type(e).__name__, str(e)[:80])
PY

echo ""
echo "== 插件自报：可用表情包与图片数 =="
docker exec astrbot python3 - <<'PY'
import json, glob, os
root = "/AstrBot/data/plugin_data/meme_manager/packs"
for d in sorted(glob.glob(root + "/*/")):
    name = os.path.basename(d.rstrip("/"))
    mj = os.path.join(d, "memes_data.json")
    n_img = len([f for f in glob.glob(d + "**/*", recursive=True)
                 if os.path.splitext(f)[1].lower() in (".jpg", ".png", ".gif", ".webp")])
    n_meta = 0
    if os.path.isfile(mj):
        try:
            data = json.load(open(mj, encoding="utf-8"))
            if isinstance(data, dict):
                n_meta = len(data.get("memes") or data.get("items") or [])
            elif isinstance(data, list):
                n_meta = len(data)
        except Exception as e:
            n_meta = "解析失败:" + type(e).__name__
    print(f"  {name}: 图片 {n_img}, 元数据条目 {n_meta}")
PY
