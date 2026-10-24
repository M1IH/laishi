# -*- coding: utf-8 -*-
"""DS-02 知识检索回归探针（自动断言版）。

用法：
    <Launcher python> data/probe_regression.py            # 只打印汇总，失败非零退出
    <Launcher python> data/probe_regression.py -v         # 逐条打印
    <Launcher python> data/probe_regression.py --json     # 机器可读

退出码：
    0  全部用例通过
    1  有用例失败（期望不符 / 隐私词泄漏 / 超长 / 敏感项被注入）
    2  环境问题（库缺失、用例文件坏）

只读：不改数据库、不改条目、不发网络请求、不发 QQ 消息。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "knowledge"))

from inject import build_block  # noqa: E402
from query import DEFAULT_DB, search  # noqa: E402
import lint as lint_mod  # noqa: E402

CASES_PATH = os.path.join(HERE, "regression_cases.json")
MAX_CHARS = 600

# 注入文本里绝不能出现的东西。宁可误报也不放过：
# 这些一旦进 prompt，就会变成模型嘴里的话。
LEAK_PATTERNS = [
    (re.compile(r"[A-Za-z]:\\"), "Windows 绝对路径"),
    (re.compile(r"/Users/|/home/"), "Unix 绝对路径"),
    (re.compile(r"Desktop|\.astrbot_launcher|来世\\\\", re.I), "项目内部路径"),
    (re.compile(r"\.py\b|\.sqlite3?\b|\.json\b"), "内部文件名"),
    (re.compile(r"api[_-]?key|jwt|secret|token", re.I), "凭证字样"),
    (re.compile(r"\b\d{6,12}\b"), "疑似 QQ 号/长数字 ID"),
    (re.compile(r"prompts?/|persona/|个性化语言"), "内部目录"),
    (re.compile(r"部署|提示词|知识库文件", re.I), "内部机制用语"),
]


def check_leak(text: str) -> list[str]:
    found = []
    for pattern, label in LEAK_PATTERNS:
        m = pattern.search(text)
        if m:
            found.append("%s（命中 %r）" % (label, m.group(0)))
    return found


def lint_severe() -> list[str]:
    """复用 knowledge/lint.py 的判据，把「严重」级问题返回给探针做断言。

    lint.py 自己跑时默认退出码是 0（只有 --strict 才返回 1），
    所以这里不调用它的 main()，而是直接用 scan_text 扫注入路径。
    """
    problems = []
    for path in sorted(lint_mod.SRC.glob("*.json")):
        data = json.load(io.open(path, encoding="utf-8"))
        topic = data.get("topic", path.stem)
        for e in data.get("entries", []):
            slug = e.get("slug", "?")
            for field in lint_mod.INJECTED:
                for why, hit in lint_mod.scan_text(e.get(field, "")):
                    problems.append("[%s/%s] %s 里出现%s：%s" % (topic, slug, field, why, hit))
            if len(e.get("summary", "")) > 60:
                problems.append("[%s/%s] summary 超 60 字（%d）"
                                % (topic, slug, len(e["summary"])))
    return problems


def rank_of(results: list[dict], slug: str | None, topic: str | None) -> int | None:
    """在注入候选（score >= 10.0）里找期望条目，返回 1 起的名次。"""
    for i, r in enumerate(results, start=1):
        if slug and r["slug"] == slug:
            return i
        if not slug and topic and r["topic"] == topic:
            return i
    return None


def run_case(case: dict) -> tuple[bool, str, dict]:
    q = case["q"]
    expect = case["expect"]
    results = [r for r in search(DEFAULT_DB, q, None, 5, include_sensitive=False)
               if r["score"] >= 10.0]
    block = build_block(q)
    info = {
        "q": q,
        "expect": expect,
        "block": block,
        "top": ["%s(%s|%s)" % (r["title"], r["topic"], r["score"]) for r in results[:3]],
    }
    problems: list[str] = []

    if expect == "hit":
        slug = case.get("slug")
        topic = case.get("topic")
        rank = rank_of(results, slug, topic)
        want = case.get("rank", 1)
        cap = case.get("max_rank")
        info["rank"] = rank
        if not block:
            problems.append("期望注入，实际为空")
        elif rank is None:
            problems.append("期望条目不在前 5：%s" % (slug or topic))
        elif cap is not None:
            if rank > cap:
                problems.append("期望不差于第 %d 名，实际第 %d 名" % (cap, rank))
        elif rank != want:
            problems.append("期望第 %d 名，实际第 %d 名" % (want, rank))
    else:
        if block:
            problems.append("期望不注入，实际注入：%s" % " / ".join(info["top"]))

    # 附加断言：not_slug 不能出现在注入里
    bad = case.get("not_slug")
    if bad:
        hits = [r for r in results if r["slug"] == bad]
        if hits and block:
            problems.append("不应注入的条目 %s 出现在结果里（%s）" % (bad, hits[0]["score"]))

    # 全局不变量：长度、隐私
    if len(block) > MAX_CHARS:
        problems.append("注入文本 %d 字符，超过 %d" % (len(block), MAX_CHARS))
    leaks = check_leak(block)
    if leaks:
        problems.append("隐私/内部信息泄漏：" + "；".join(leaks))

    return (not problems), "；".join(problems), info


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="知识检索回归探针（自动断言）")
    ap.add_argument("-v", "--verbose", action="store_true", help="逐条打印")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--cases", default=CASES_PATH)
    ap.add_argument("--no-lint", action="store_true",
                    help="跳过 lint 严重项检查（默认会检查，严重项即失败）")
    args = ap.parse_args()

    if not os.path.exists(DEFAULT_DB):
        print("数据库不存在：%s" % DEFAULT_DB, file=sys.stderr)
        return 2
    if not os.path.exists(args.cases):
        print("用例文件不存在：%s" % args.cases, file=sys.stderr)
        return 2
    try:
        with io.open(args.cases, encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        print("用例文件不是合法 JSON：%s" % exc, file=sys.stderr)
        return 2

    groups = [(k, v) for k, v in payload.items() if k != "meta" and isinstance(v, list)]
    total = passed = 0
    failures: list[dict] = []
    details: list[dict] = []
    lint_problems: list[str] = []
    if not args.no_lint:
        lint_problems = lint_severe()

    for group, cases in groups:
        if args.verbose and not args.as_json:
            print("\n=== %s ===" % group)
        for case in cases:
            total += 1
            ok, reason, info = run_case(case)
            info["group"] = group
            info["ok"] = ok
            details.append(info)
            if ok:
                passed += 1
            else:
                failures.append({"group": group, "reason": reason, **info})
            if args.as_json:
                continue
            if args.verbose:
                mark = "ok  " if ok else "FAIL"
                print("%s %-24s %s" % (mark, case["q"], reason or " / ".join(info["top"])[:80]))
            elif not ok:
                print("FAIL [%s] %s -> %s" % (group, case["q"], reason))

    if args.as_json:
        print(json.dumps({
            "total": total, "passed": passed, "failed": total - passed,
            "failures": failures, "lint_severe": lint_problems, "cases": details,
        }, ensure_ascii=False, indent=2))
        return 0 if (passed == total and not lint_problems) else 1

    print("\n知识检索回归：%d/%d 通过，%d 失败" % (passed, total, total - passed))
    if lint_problems:
        print("lint 严重项 %d 处（注入路径不干净）：" % len(lint_problems))
        for p in lint_problems[:20]:
            print("  · " + p)
        if len(lint_problems) > 20:
            print("  … 其余 %d 处略" % (len(lint_problems) - 20))
    if failures or lint_problems:
        if failures:
            print("失败清单：")
            for f in failures:
                print("  [%s] %s —— %s" % (f["group"], f["q"], f["reason"]))
        return 1
    print("全部通过（含隐私词、长度、敏感项、lint 严重项断言）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
