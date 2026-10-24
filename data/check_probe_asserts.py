# -*- coding: utf-8 -*-
"""DS-02 验收辅助：证明探针在「故意破坏」时会非零退出。

Codex 验收要求「检查故意破坏一个预期时会非零退出」，这个脚本把三种破坏
都跑一遍，打印各自的退出码，供复验。

用法：
    <Launcher python> data/_tmp_break_test.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "knowledge"))
sys.path.insert(0, ROOT)

import probe_regression as P  # noqa: E402

CASES = os.path.join(HERE, "regression_cases.json")


def run(argv, mutate=None):
    old_argv = sys.argv
    old_lint = P.lint_severe
    if mutate:
        P.lint_severe = mutate
    sys.argv = ["probe_regression.py"] + argv
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = P.main()
    finally:
        sys.argv = old_argv
        P.lint_severe = old_lint
    return code, buf.getvalue()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ok = True

    code, out = run([])
    print("[基线] 不改任何东西            -> 退出码 %d  %s" % (code, "OK" if code == 0 else "异常"))
    ok &= code == 0

    # 破坏一：把一条负例改成期望命中
    payload = json.load(io.open(CASES, encoding="utf-8"))
    payload["负例"].append({"q": "今天天气不错", "expect": "hit", "slug": "wo-shi-shui", "rank": 1})
    broken = os.path.join(HERE, "_tmp_broken_cases.json")
    with io.open(broken, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    code, out = run(["--cases", broken])
    print("[破坏一] 负例改成 expect=hit    -> 退出码 %d  %s" % (code, "OK" if code == 1 else "异常"))
    ok &= code == 1
    os.remove(broken)

    # 破坏二：注入文本里塞一个内部路径，验证隐私词断言
    code, out = run([], mutate=lambda: ["[maimai/fake] summary 里出现项目路径：C:\\Users\\OTTO\\Desktop"])
    print("[破坏二] lint 报一个严重项      -> 退出码 %d  %s" % (code, "OK" if code == 1 else "异常"))
    ok &= code == 1

    # 破坏三：期望条目名次写错
    payload = json.load(io.open(CASES, encoding="utf-8"))
    payload["正例"].append({"q": "何意味", "expect": "hit", "slug": "he-yi-wei", "rank": 3})
    broken = os.path.join(HERE, "_tmp_broken_cases.json")
    with io.open(broken, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    code, out = run(["--cases", broken])
    print("[破坏三] 期望名次从 1 改成 3     -> 退出码 %d  %s" % (code, "OK" if code == 1 else "异常"))
    ok &= code == 1
    os.remove(broken)

    print("\n三种破坏都能被断言拦住：%s" % ("是" if ok else "否，需要检查探针"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
