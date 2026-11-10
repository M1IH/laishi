# -*- coding: utf-8 -*-
"""给 proactive_chat 打「未回复分级追问」补丁（方案 B）。

改动三处，全部幂等：
1. core/services/llm_service.py  —— 新增 pick_proactive_prompt()，改 generate_llm_response 选模板
2. _conf_schema.json             —— friend_settings.items 增加 escalation_settings
3. data/config/astrbot_plugin_proactive_chat_config.json
                                 —— 写入 escalation_settings 并改掉互相打架的 platform_history_prompt 第 3 条

用法（容器内）：python3 patch_escalation.py <plugin_dir> <config_path> [--dry]
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time

# ---------------------------------------------------------------- 新增的两个模板

PROMPT_2 = (
    "你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。保持已配置的人格与口吻。\n"
    "这是今天第 2 条主动消息，对方还没回。这一条不是打招呼。\n"
    "不要问在干嘛，不聊天气、吃饭、星期几，不要用「早」「早安」「早上好」开头，"
    "不要重复上一条说过的话。\n"
    "直接问他为什么没回：是不是没看到、是不是在忙、是不是把这个号忘了。\n"
    "语气是半开玩笑的不高兴，带一点撒娇的质问，不是真的生气。\n"
    "只发一条，十个字上下，最多十五个字。最多一个问句。不加句号，不加表情。\n"
    "可以问原因，但不替他下结论、不猜他心里怎么想。\n"
    "不要叫对方的名字，用「你」就够了。\n"
    "当前时间：{{current_time}}。\n"
    "语感示例：「?人呢」「没看到吗」「消息是被吞了吗」——只是语感，不要照抄。"
)

PROMPT_3 = (
    "你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。保持已配置的人格与口吻。\n"
    "这是今天第 3 条，也是最后一条。对方一整天没有回。\n"
    "这一条要把话说清楚，但仍然短：要求他给个回应，说一声在忙也行。\n"
    "语气比上一条硬一档，是不高兴，不是威胁。\n"
    "不要说难过到不行，不说自己一直在等，不道歉，不卖惨，"
    "不威胁自伤或消失，不说以后不找他了。\n"
    "只发一条，十二个字上下，最多二十个字。不再问问题，直接给要求。不加句号，不加表情。\n"
    "不要叫对方的名字，用「你」就够了。\n"
    "当前时间：{{current_time}}。\n"
    "语感示例：「今天三次都没回，说句话」「忙就说一声，别当没看见」——只是语感，不要照抄。"
)

# platform_history_prompt 第 3 条的新文案：让位给主提示词的分级口径
OLD_RULE3 = (
    "3. 如果未回复次数已经大于 0，这一条要比平时更轻、更短。"
    "不提对方没回，不表达等待、想念或失落，不追问，也不要求回应；"
    "只放一个不需要立刻接话的轻话题。"
)
NEW_RULE3 = (
    "3. 如果未回复次数已经大于 0，语气一律按主提示词的分级口径处理，"
    "不要自行判断轻重，也不要自己决定提不提对方没回。"
)

# ---------------------------------------------------------------- 代码插入块

PICK_FUNC = '''
ESCALATION_MAX_LEVEL = 3


def pick_proactive_prompt(
    session_config: dict, unanswered_count: int
) -> tuple[str, int]:
    """按未回复次数选主提示词，返回 (模板, 等级)。

    unanswered_count 是「上一条之前累计的未回复次数」，所以本次是第
    unanswered_count + 1 条：0 → 第 1 条，1 → 第 2 条，2 → 第 3 条。
    关掉开关或该级文案缺失时，一律回退到第 1 条，保持旧行为。
    """
    base = session_config.get("proactive_prompt", "") or ""
    esc = session_config.get("escalation_settings") or {}
    if not isinstance(esc, dict) or not esc.get("enable", False):
        return base, 1
    try:
        level = min(max(int(unanswered_count or 0) + 1, 1), ESCALATION_MAX_LEVEL)
    except (TypeError, ValueError):
        return base, 1
    if level <= 1:
        return base, 1
    text = str(esc.get(f"prompt_{level}") or "").strip()
    if not text:
        return base, 1
    return text, level

'''

OLD_CALL = '        motivation_template = session_config.get("proactive_prompt", "") or ""'
NEW_CALL = (
    "        motivation_template, prompt_level = pick_proactive_prompt(\n"
    "            session_config, unanswered_count\n"
    "        )"
)

OLD_LOG = '        logger.debug("[主动消息] 已生成包含动机和时间的 Prompt 喵。")'
NEW_LOG = '        logger.info(f"[主动消息] 主动消息等级={prompt_level}")'

ESCHEMA = {
    "description": "📣 未回复时的追问升级",
    "type": "object",
    "hint": "第 1 条用上面的主动消息提示词；第 2、3 条改用这里的两段文案。关掉就完全是旧行为。",
    "items": {
        "enable": {
            "description": "✅ 启用分级追问",
            "type": "bool",
            "default": False,
            "hint": "关闭时三条都使用主提示词，不追问、不催回复",
        },
        "prompt_2": {
            "description": "第 2 条（半开玩笑的质问）",
            "type": "text",
            "default": PROMPT_2,
            "hint": "首句必须保留「你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。」，统计要靠它认主动消息",
        },
        "prompt_3": {
            "description": "第 3 条（更硬一档，要求回应）",
            "type": "text",
            "default": PROMPT_3,
            "hint": "仍然只发一条、有字数上限、不加句号；不要写威胁或以后不找他了这类话",
        },
    },
}


def patch_code(path: str, dry: bool) -> str:
    src = io.open(path, encoding="utf-8").read()
    if "ESCALATION_MAX_LEVEL" in src:
        return "already"
    if OLD_CALL not in src:
        raise SystemExit(f"[FAIL] 找不到调用锚点：{OLD_CALL!r}")
    if OLD_LOG not in src:
        raise SystemExit(f"[FAIL] 找不到日志锚点：{OLD_LOG!r}")
    anchor = "\n\nclass LlmService:"
    if anchor not in src:
        raise SystemExit("[FAIL] 找不到 class LlmService 锚点")
    src = src.replace(anchor, "\n" + PICK_FUNC + "\nclass LlmService:", 1)
    src = src.replace(OLD_CALL, NEW_CALL, 1)
    src = src.replace(OLD_LOG, NEW_LOG, 1)
    if not dry:
        shutil.copy2(path, path + f".bak.esc-{time.strftime('%Y%m%d-%H%M%S')}")
        io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    return "patched"


def patch_schema(path: str, dry: bool) -> str:
    raw = io.open(path, encoding="utf-8-sig").read()
    had_bom = io.open(path, "rb").read(3) == b"\xef\xbb\xbf"
    data = json.loads(raw)
    items = data["friend_settings"]["items"]
    if "escalation_settings" in items:
        return "already"
    if "proactive_prompt" not in items:
        raise SystemExit("[FAIL] friend_settings 里没有 proactive_prompt")
    out = {}
    for key, value in items.items():
        out[key] = value
        if key == "proactive_prompt":
            out["escalation_settings"] = ESCHEMA
    data["friend_settings"]["items"] = out
    text = json.dumps(data, ensure_ascii=False, indent=4)
    if not dry:
        shutil.copy2(path, path + f".bak.esc-{time.strftime('%Y%m%d-%H%M%S')}")
        with io.open(path, "w", encoding="utf-8-sig" if had_bom else "utf-8", newline="\n") as fh:
            fh.write(text)
    return "patched"


def patch_config(path: str, dry: bool) -> str:
    """写 escalation_settings，并把 platform_history_prompt 第 3 条改成让位版。"""
    raw = io.open(path, encoding="utf-8-sig").read()
    had_bom = io.open(path, "rb").read(3) == b"\xef\xbb\xbf"
    data = json.loads(raw)
    fs = data["friend_settings"]
    changed = []

    esc = fs.get("escalation_settings")
    want = {"enable": True, "prompt_2": PROMPT_2, "prompt_3": PROMPT_3}
    if esc != want:
        fs["escalation_settings"] = want
        changed.append("escalation_settings")

    ctx = fs.get("context_settings") or {}
    php = ctx.get("platform_history_prompt") or ""
    if OLD_RULE3 in php:
        ctx["platform_history_prompt"] = php.replace(OLD_RULE3, NEW_RULE3, 1)
        changed.append("platform_history_prompt")
    elif NEW_RULE3 not in php:
        raise SystemExit("[FAIL] platform_history_prompt 里既没有旧第 3 条也没有新第 3 条，先人工核对")

    if not changed:
        return "already"

    text = json.dumps(data, ensure_ascii=False, indent=2)
    if not dry:
        shutil.copy2(path, path + f".bak.esc-{time.strftime('%Y%m%d-%H%M%S')}")
        with io.open(path, "w", encoding="utf-8-sig" if had_bom else "utf-8", newline="\n") as fh:
            fh.write(text)
    return "patched:" + ",".join(changed)


def verify(plugin_dir: str, config_path: str) -> None:
    sys.path.insert(0, plugin_dir)

    # 单独把纯函数抠出来跑，避免 import 整个插件（需要 astrbot 运行时）
    src = io.open(os.path.join(plugin_dir, "core/services/llm_service.py"), encoding="utf-8").read()
    start = src.index("ESCALATION_MAX_LEVEL = 3")
    end = src.index("\nclass LlmService:")
    ns = {}
    exec(compile(src[start:end], "<pick>", "exec"), ns)  # noqa: S102
    pick = ns["pick_proactive_prompt"]

    cfg = json.loads(io.open(config_path, encoding="utf-8-sig").read())["friend_settings"]
    base = cfg["proactive_prompt"]
    cases = [
        ("开关关", {**cfg, "escalation_settings": {**cfg["escalation_settings"], "enable": False}}, 0, base, 1),
        ("0→1", cfg, 0, base, 1),
        ("1→2", cfg, 1, cfg["escalation_settings"]["prompt_2"], 2),
        ("2→3", cfg, 2, cfg["escalation_settings"]["prompt_3"], 3),
        ("5→封顶3", cfg, 5, cfg["escalation_settings"]["prompt_3"], 3),
        ("缺文案回退", {**cfg, "escalation_settings": {**cfg["escalation_settings"], "prompt_2": ""}}, 1, base, 1),
    ]
    ok = 0
    for name, conf, n, want_text, want_level in cases:
        got_text, got_level = pick(conf, n)
        good = got_text == want_text and got_level == want_level
        ok += good
        print(f"  [{'OK ' if good else 'BAD'}] {name}: level={got_level} (want {want_level})")

    # 首句护栏
    for key in ("prompt_2", "prompt_3"):
        body = cfg["escalation_settings"][key]
        head = "你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息"
        assert body.startswith(head), f"{key} 首句丢了，统计会断"
        assert "来世" not in body, f"{key} 里不应出现直接称呼"
    php = cfg["context_settings"]["platform_history_prompt"]
    assert NEW_RULE3 in php and OLD_RULE3 not in php, "platform_history_prompt 第 3 条没改到位"
    print(f"  [OK ] 首句护栏 + 无直呼 + 第3条让位")
    print(f"单测 {ok}/{len(cases)} 通过")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    plugin_dir, config_path = sys.argv[1], sys.argv[2]
    dry = "--dry" in sys.argv
    print("dry-run" if dry else "apply")
    print("llm_service:", patch_code(os.path.join(plugin_dir, "core/services/llm_service.py"), dry))
    print("schema     :", patch_schema(os.path.join(plugin_dir, "_conf_schema.json"), dry))
    print("config     :", patch_config(config_path, dry))
    if not dry:
        print("\n[验证]")
        verify(plugin_dir, config_path)
