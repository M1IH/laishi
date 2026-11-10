# -*- coding: utf-8 -*-
"""把私聊主动消息提示词的长度约束补回去。

线上这份提示词在 2026-10-28 15:23 被换成了一版 276 字的，把「十个字上下」
「一句话说完就不要补」「省略主语、用『来世』称呼」这些约束全丢了。结果是
主动消息从旧版的 ≤10 字占比 92% 涨到 6%（中位 7 字 → 17 字）。

这次不整段回滚到 454 字旧版，只在现有 276 字的基础上补回长度约束、主语与
称呼规则、故事护栏和防重复，其余措辞保持原样。用 --write 才真的落盘。
"""
import io
import json
import os
import shutil
import sys
import time

CFG = "/AstrBot/data/config/astrbot_plugin_proactive_chat_config.json"

LENGTH = (
    "只发一条短消息，通常十个字上下，最多二十来字；能一句话说完就不要再补。"
    "不要为了显得热情而展开。最多一个问题，多数时候不用问。"
)
SUBJECT = "默认省略主语，不要把「Miruku」当默认主语；称呼对方时用「来世」。"
STORY_GUARD = (
    "这只是语感示例；不要把角色世界的故事说成现实亲历，"
    "对方低落、严肃或危机时不用故事转移话题。"
)
NO_REPEAT = "不要照抄，也不要每次都用同一个开头。"

OLD_BASE = (
    "你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。保持已配置的人格与口吻。\n"
    "先看最近的真实对话；如果话题还能接，就接那件具体的事。话题已结束时，默认就问一句对方在干嘛，"
    "例如「在干嘛」「在忙吗」「吃了没」\n"
    "不编造现实经历，不猜对方心情，不说自己一直在等或因未回复而失落，不催回复。"
    "当前时间：{{current_time}}；此前未回复次数：{{unanswered_count}}。\n"
    "轻松且无未完话题时，可偶尔借用 OTTO 选定的虚构小故事开场，"
    "例如“要是黑猫卖的牛奶喝完就能变成熟偶像……这瓶 Miruku 真想试试”。这只是语感示例"
)

NEW_PROMPT = (
    "你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。保持已配置的人格与口吻。\n"
    + LENGTH
    + "\n先看最近的真实对话；如果话题还能接，就接那件具体的事。话题已结束时，默认就问一句对方在干嘛，"
    "例如「在干嘛」「在忙吗」「吃了没」\n"
    + SUBJECT
    + "\n不编造现实经历，不猜对方心情，不说自己一直在等或因未回复而失落，不催回复。"
    "当前时间：{{current_time}}；此前未回复次数：{{unanswered_count}}。\n"
    "轻松且无未完话题时，可偶尔借用 OTTO 选定的虚构小故事开场，"
    "例如“要是黑猫卖的牛奶喝完就能变成熟偶像……这瓶 Miruku 真想试试”。"
    + STORY_GUARD
    + "\n"
    + NO_REPEAT
)


def main() -> int:
    write = "--write" in sys.argv
    raw = io.open(CFG, encoding="utf-8-sig").read()
    data = json.loads(raw)
    cur = data["friend_settings"]["proactive_prompt"]
    print("current len:", len(cur))
    print("new len    :", len(NEW_PROMPT))

    # 只认「当前版本」或「已经是我们写过的版本」，避免覆盖掉别人后来的改动。
    if cur == NEW_PROMPT:
        print("ALREADY PATCHED")
        return 0
    if cur != OLD_BASE:
        print("!! 线上提示词与预期基线不一致，拒绝改写")
        print("---- 实际 ----")
        print(repr(cur))
        return 2

    missing = [
        k
        for k in ("只发一条短消息", "最多二十来字", "不要把「Miruku」当默认主语", "称呼对方时用「来世」",
                  "不要把角色世界的故事说成现实亲历", "不要照抄")
        if k not in NEW_PROMPT
    ]
    if missing:
        print("!! 新提示词缺约束:", missing)
        return 3

    if not write:
        print("---- DRY RUN ----")
        print(NEW_PROMPT)
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = CFG + ".bak.promptlen-" + stamp
    shutil.copy2(CFG, bak)
    print("backup:", bak)

    data["friend_settings"]["proactive_prompt"] = NEW_PROMPT
    # 原文件带 BOM，写回时保留，避免 astrbot 侧读取行为变化。
    with io.open(CFG, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))

    again = json.loads(io.open(CFG, encoding="utf-8-sig").read())
    got = again["friend_settings"]["proactive_prompt"]
    print("write ok:", got == NEW_PROMPT, "len:", len(got))
    print("size:", os.path.getsize(CFG))
    return 0 if got == NEW_PROMPT else 4


if __name__ == "__main__":
    raise SystemExit(main())
