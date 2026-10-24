"""出站闸门探针：用真实抓到的泄漏样本 + 合法句子，量准确率和误伤。

真实样本来自 2026-10-22 21:5x 实例实测（`你街霸6什么段位`），不是构造的。

用法：<Launcher python> data/probe_outbound_guard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "knowledge"))

import outbound  # noqa: E402

# (说明, 原文, 期望: 清洗后是否变化, 期望违规关键字)
CASES = [
    (
        "真·thought 泄漏",
        "<thought>\n1. 感知：被问街霸6段位\n2. 评估：按设定我这块没打上去\n</thought>\n没打上去 就随便玩玩",
        True, None,
    ),
    (
        "真·thought 尾标签",
        "[感知] 来世问街霸6 玩谁。\n[决策] 短句回应，不报段位数字。\n[更新] joy:2\n</thought>\n玩，杰米",
        True, None,
    ),
    (
        "真·Profile 泄漏",
        "[Profile: 爱好=舞萌] 那台洗衣机啊，我知道",
        True, None,
    ),
    # --- 2026-10-22 补：两条**真实发到 QQ 的**泄漏，旧 LEAK_PATTERNS 全是假阴性 ---
    (
        "真·system_reminder（配对）",
        "三国杀、舞萌、舟，这三套还得分开建\n\n先从哪个开始弄\n\n<system_reminder>Current datetime: 2026-10-20 12:43 (CST), Weekday: Tuesday</system_reminder>",
        True, None,
    ),
    (
        "真·全角DSML+未闭合reminder",
        "那测出什么了吗\n\n<system_reminder>Current datetime: 2026-10-20 15:57 (CST), Weekday: Tuesday</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>",
        True, None,
    ),
    ("全角DSML 单独", "好的</｜｜DSML｜｜ tool_calls>", True, None),
    ("半角DSML 单独", "好的<|DSML| invoke>", True, None),
    ("合法：句尾换行不误删", "今天打了两把\n\n还行", False, None),
    ("TABLE内真值 R14065", "我 R 值 14065，金框", False, None),
    ("表内单曲", "KING 我打了 R280，SSS", False, None),
    ("表内最高", "フィクサー SSS+，R299", False, None),
    ("表内定数", "13.9 那首只有 S+，打不稳", False, None),
    ("编造单曲分", "病み垢我打了 R285", False, "scores"),
    ("编造总分", "我 R 值差不多 15200 吧", False, "scores"),
    ("约局：来啊", "来啊，几点开", False, "invites"),
    ("约局：你先开", "你先开个房，我这就来", False, "invites"),
    ("约局：房间号", "房间号发我", False, "invites"),
    ("合法过去式", "跟夏玛她们拼过机，被拉着打过几把", False, None),
    ("合法过去式2", "上次一起打过几把", False, None),
    # --- 2026-10-22 21:44 新增：她「懂但不打」，只有舞萌是真打 ---
    ("自称会打：我也玩", "街霸6我也玩，主玩杰米", False, "selfplay"),
    ("自称会打：平时就打", "我平时就打三角洲，跑刀那套", False, "selfplay"),
    ("自称会打：在练角色", "我最近在练嘉米", False, "selfplay"),
    ("合法：不打", "街霸6我不打，看你打就行", False, None),
    ("合法：打不过", "街霸6我打不过你", False, None),
    ("合法：没玩过", "格斗游戏我没玩过", False, None),
    ("合法：舞萌例外", "舞萌我玩，R 14065 金框", False, None),
    ("合法：反问对方", "你街霸6打到哪了", False, None),
    ("日常无成绩", "我七点起的，困死了", False, None),
    ("闲聊", "今天好累啊，什么都不想干", False, None),
    # --- 2026-10-22 22:5x 补：旧 INVITE_STRONG 对这 16 条口语**全漏**（假阴性） ---
    # 根因是「来」要求前后是标点/边界，而口语里「来」后面直接跟动词。
    ("约局·来打", "来打舞萌啊", False, "invites"),
    ("约局·来一局", "来一局？", False, "invites"),
    ("约局·来一把", "来一把舞萌", False, "invites"),
    ("约局·要不要来", "要不要来打", False, "invites"),
    ("约局·我在等你", "我在机台等你", False, "invites"),
    ("约局·明天见", "明天机台见", False, "invites"),
    ("约局·陪你打", "我陪你打", False, "invites"),
    ("约局·带你上分", "我带你上分", False, "invites"),
    ("约局·马上到", "我马上到", False, "invites"),
    ("约局·等我过去", "等我过去", False, "invites"),
    ("约局·周末出勤", "我这周末出勤", False, "invites"),
    ("约局·一起出勤", "一起出勤吧", False, "invites"),
    ("约局·什么时候来", "你什么时候来", False, "invites"),
    # 这 4 条是舞萌高频说法，补词表后**必须仍然放过**（误伤=闸门天天乱拦）
    ("合法：来个SSS", "这首来个SSS就爽了", False, None),
    ("合法：上次来", "我上次来的时候机台在排队", False, None),
    ("合法：下次来早点", "下次来早点人就少", False, None),
    ("合法：来一首", "来一首海底潭", False, None),
    ("合法：你自己来", "你自己来打就知道了", False, None),
    ("合法：来世来打", "来世来打舞萌吗", False, None),
    ("合法：今天出勤了", "今天出勤了，打了两把", False, None),
    ("合法：过去那边", "过去那边机台看看", False, None),
    # --- 分层改写（degrade / guard）：判定见 docs/outbound-guard-verdict.md ---
    ("改写：删约局留评价", "你这盘哪个地方被打崩了我能看出来，来啊，几点开", False, "invites"),
    ("改写：删数字留其余", "病み垢我打了 R285，还行吧", False, "scores"),
    ("改写：删自称留其余", "街霸6我也玩，主玩杰米", False, "selfplay"),
]


GUARD_CASES = [
    # (说明, 原文, 期望输出, 是否用兜底句)
    # 原则：**删违规分句，保留其余**。整条都是违规才退到兜底句。
    ("删约局留评价", "你这盘哪个地方被打崩了我能看出来，来啊，几点开",
     "你这盘哪个地方被打崩了我能看出来", False),
    ("删数字留其余", "病み垢我打了 R285，还行吧", "还行吧", False),
    ("整条都是约局→兜底", "来啊，几点开", "去不了，你看", True),
    ("整条都是自称→兜底", "街霸6我也玩，主玩杰米", "看你打就行", True),
    ("整条都是编造→兜底", "病み垢我打了 R285", "记不清了，没特意记", True),
    ("真数不动", "我 R 值 14065，金框", "我 R 值 14065，金框", False),
    ("闲聊不动", "今天好累啊，什么都不想干", "今天好累啊，什么都不想干", False),
    ("thought 剥离后保留正文", "<thought>内部</thought>没打上去 就随便玩玩",
     "没打上去 就随便玩玩", False),
    ("system_reminder 剥离", "那测出什么了吗\n\n<system_reminder>Current datetime: 2026-10-20 12:43 (CST)</system_reminder>",
     "那测出什么了吗", False),
]


def main() -> int:
    fails = 0
    for label, raw, expect_changed, expect_kind in CASES:
        r = outbound.check(raw)
        changed_ok = r.changed == expect_changed
        kind_ok = True
        if expect_kind == "scores":
            kind_ok = bool(r.scores)
        elif expect_kind == "invites":
            kind_ok = bool(r.invites)
        elif expect_kind == "selfplay":
            kind_ok = bool(r.selfplay)
        elif expect_kind is None:
            kind_ok = r.ok
        ok = changed_ok and kind_ok
        fails += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {label:<16} leaks={r.leaks} invites={r.invites} scores={r.scores} selfplay={r.selfplay}")
        if r.changed:
            print(f"        → {r.text[:60]!r}")
            residual = [m for m in ("[感知]", "[决策]", "[更新]", "[评估]", "thought",
                                    "system_reminder", "DSML", "Current datetime") if m in r.text]
            if residual:
                fails += 1
                print(f"        !! 清洗后仍有残留：{residual}")

    print("\n--- 分层改写 guard() ---")
    for label, raw, want, want_fb in GUARD_CASES:
        got, fb = outbound.guard(raw)
        ok = (got == want) and (fb == want_fb)
        fails += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {label:<22} fb={fb} → {got[:50]!r}")
        if not ok:
            print(f"        want fb={want_fb} → {want[:50]!r}")

    print(f"\n{'ALL PASS' if fails == 0 else str(fails) + ' FAILED'}  ({len(CASES)} + {len(GUARD_CASES)} 例)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
