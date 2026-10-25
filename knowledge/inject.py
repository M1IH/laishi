#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一条消息转成可直接拼进 prompt 的「可参考的知识」块。

给运行期接入用（方案 A：预检索注入）。只输出文本，不做网络请求。

用法：
    python knowledge/inject.py "他问我夏玛是谁"
    python knowledge/inject.py "来世说他在打鸟加" --limit 2
    python knowledge/inject.py "随便聊聊" --max-chars 400

退出码：0 有命中并输出；0 无命中（不输出内容）；2 数据库缺失。
调用方拿到空 stdout 就别注入，别硬塞。

在 AstrBot 插件里也可以直接 import：
    from knowledge.query import search
    from knowledge.inject import build_block
    block = build_block("他问我夏玛是谁")
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from query import DEFAULT_DB, search  # noqa: E402

HEADER = "可参考的知识（答时只用最相关的一条，一两句话说完；不要罗列、不要逐条复述、不要说“知识库”）："

# 成绩问句的显式意图词。只在**已有注入块**的情况下才用，用来补一条兜底规则。
SCORE_INTENT = ("多少分", "几分", "打多少", "什么评级", "评级是",
                "多少r", "r值", "b50", "best50")

# 表外曲目的兜底规则。为什么要在注入块里补这一条：
# b50 只覆盖 50 首，而「ロキ多少分」这类问句只会命中**曲子背景**条目（16.5 分），
# 「b50 之外的歌不要报数字」那条只有 1.0–1.8 分，永远过不了 10.0 的阈值。
# 也就是：**最需要这条规则的时刻，恰恰是它不会被注入的时刻。**
# 放在这里补，等于给「问成绩」这个意图单独挂一条护栏。
SCORE_GUARD = "（b50 只记最好的 50 首：上面没写成绩的歌就说“没怎么刷过”，不要报数字）"


def build_block(message: str, limit: int = 3, min_score: float = 10.0,
                max_chars: int = 600, db_path: str = DEFAULT_DB) -> str:
    """返回可直接注入的文本块；没有足够相关的条目时返回空字符串。

    min_score 比 query.py 里 search 的展示下限（1.0）高得多：注入是每轮都做的，
    宁可少注入，也不要把弱相关的条目塞进上下文。

    阈值 10.0 是用真实语料标定出来的（data/inject_sample.py）：
    调到 8.0 时命中率 17%，全是误命中——「看你忙一天」注入《忙シー日》、
    「学校对面的」注入 Panopticon；10.0 时剩下的是「出勤」「改模」「何意味」
    这类真在聊的。调低会让模型看起来什么都知道，代价是闲聊里莫名提一首歌，
    比不知道更出戏。

    注意这个阈值**不是**误命中的主要防线：单字标题、ASCII 子串、日常词别名
    这些问题都在 query.py 的 score() 里按类型单独挡掉（见那边的注释）。
    只靠抬高阈值会把真话题一起挡掉——「墓守这歌怎么样」曾被压到 9.0。
    """
    if not message or not message.strip():
        return ""
    results = search(db_path, message, None, limit, include_sensitive=False)
    picked = [r for r in results if r["score"] >= min_score]
    if not picked:
        return ""
    lines = [HEADER]
    used = len(HEADER)
    for r in picked:
        line = "- %s：%s" % (r["title"], r["summary"])
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    if len(lines) == 1:
        return ""
    # 问成绩、但块里没有一条按曲目写死的成绩 → 补兜底规则（理由见 SCORE_GUARD）。
    question = message.lower()
    if any(w in question for w in SCORE_INTENT) and not any(
        r.get("topic") == "b50" for r in picked
    ):
        if used + len(SCORE_GUARD) <= max_chars:
            lines.append(SCORE_GUARD)
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="生成知识注入块")
    ap.add_argument("message", nargs="+", help="对方这条消息的文本")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--min-score", type=float, default=10.0)
    ap.add_argument("--max-chars", type=int, default=600)
    args = ap.parse_args()
    if not os.path.exists(args.db):
        print("数据库不存在：%s" % args.db, file=sys.stderr)
        return 2
    block = build_block(" ".join(args.message), args.limit, args.min_score,
                        args.max_chars, args.db)
    if block:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
