# -*- coding: utf-8 -*-
"""DS-08R 的 PASS 闸穷举矩阵：证明「只有一种组合能给 PASS」。

比 `check_ds08r_regression.py` 更严：它对**每套样本 × 带/不带基线**做笛卡尔积，
逐格断言判定与退出码，并额外施加一条铁律——**任何非 PASS 都不许退出 0**。

复跑（退出码 0 = 全部符合）：

    <venv>/Scripts/python.exe data/check_ds08r_matrix.py

预期：10 格全绿；唯一 ``PASS`` 出现在「全新版 + 带基线 + 已确认送达 + 样本 20 轮」。

编码：本脚本把自己和子进程都固定为 UTF-8，不受 Windows 控制台代码页影响。
"""
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PY = sys.executable
PROBE = "data/probe_reply_metrics.py"
BASELINE = "2026-10-25T17:00:00+08:00"

CHILD_ENV = dict(os.environ)
CHILD_ENV["PYTHONIOENCODING"] = "utf-8"
CHILD_ENV["PYTHONUTF8"] = "1"

# (样本名, 路径, 是否带基线, 期望 verdict)
# 说明：6 轮真实样本低于 20 轮门槛，`NOT_ENOUGH_DATA` 与 `UNVERIFIED_VERSION`
# 都合法（Codex 复核明确「样本不足可保留 NOT_ENOUGH_DATA」）；两者都非零退出、都不给 PASS。
MATRIX = [
    ("混版", "data/ds08r_synthetic_mixed.json", False, "UNVERIFIED_VERSION"),
    ("混版", "data/ds08r_synthetic_mixed.json", True, "UNVERIFIED_VERSION"),
    ("全旧", "data/ds08r_synthetic_all_old.json", False, "UNVERIFIED_VERSION"),
    ("全旧", "data/ds08r_synthetic_all_old.json", True, "UNVERIFIED_VERSION"),
    ("全新", "data/ds08r_synthetic_verified.json", False, "UNVERIFIED_VERSION"),
    ("全新", "data/ds08r_synthetic_verified.json", True, "PASS"),
    ("未送达", "data/ds08r_synthetic_undelivered.json", False, "UNVERIFIED_VERSION"),
    ("未送达", "data/ds08r_synthetic_undelivered.json", True, "UNVERIFIED_VERSION"),
    ("真实6轮", "data/ds08_cx01_rounds.json", False, "NOT_ENOUGH_DATA"),
    ("真实6轮", "data/ds08_cx01_rounds.json", True, "NOT_ENOUGH_DATA"),
]

fails: list[tuple] = []
print("样本".ljust(12), "带基线".ljust(8), "期望".ljust(20), "实际".ljust(20), "退出码", "结果")
print("-" * 88)

for name, path, with_base, want in MATRIX:
    args = [PY, PROBE, "--input", path]
    if with_base:
        args += ["--baseline", BASELINE]
    p = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=CHILD_ENV
    )
    got = ""
    for line in p.stdout.splitlines():
        s = line.strip()
        if s.startswith("结论："):
            got = s.split("结论：", 1)[1].split("（", 1)[0].strip()
            break
    ok = got == want
    # 铁律：任何非 PASS 都不许退出 0
    if want != "PASS" and p.returncode == 0:
        ok = False
    if not ok:
        fails.append((name, with_base, want, got, p.returncode))
    print(
        name.ljust(12),
        ("是" if with_base else "否").ljust(8),
        want.ljust(20),
        (got or "—").ljust(20),
        p.returncode,
        "符合" if ok else "**不符合**",
    )

print()
if fails:
    print("不符合项：")
    for f in fails:
        print("  ", f)
    raise SystemExit(1)
print("矩阵全部符合：唯一能给 PASS 的组合是「全新 + 带基线 + 已确认送达 + 样本足」")
