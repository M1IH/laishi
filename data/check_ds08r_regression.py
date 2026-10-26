# -*- coding: utf-8 -*-
"""DS-08R 反例回归：合成样本 + 真实样本的判定与退出码必须完全符合预期。

给 Codex 复跑的一条命令；预期全部「符合」，脚本退出 0。

**编码**：无论控制台代码页是什么（GBK/CP936 等），本脚本都给子进程显式设置
``PYTHONIOENCODING=utf-8`` 与 ``PYTHONUTF8=1``，并按 UTF-8 解码子进程输出，
避免受 Windows 代码页影响（上一版未设置时曾因此退出 1）。
"""
import os
import subprocess
import sys
from pathlib import Path

# 本脚本自己的 stdout 也固定为 UTF-8，避免在 GBK 控制台下输出乱码或抛异常。
# 子进程另见 CHILD_ENV。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PY = sys.executable
PROBE = "data/probe_reply_metrics.py"
BASELINE = "2026-10-25T17:00:00+08:00"

# 统一给子进程固定 UTF-8，不依赖外部环境
CHILD_ENV = dict(os.environ)
CHILD_ENV["PYTHONIOENCODING"] = "utf-8"
CHILD_ENV["PYTHONUTF8"] = "1"


def run(args: list[str]) -> tuple[subprocess.CompletedProcess, str]:
    """跑一次探针，返回 (进程结果, 提取出的结论 verdict)。"""
    proc = subprocess.run(
        [PY, PROBE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=CHILD_ENV,
    )
    got = ""
    for line in proc.stdout.splitlines():
        s = line.strip()
        if s.startswith("结论："):
            got = s.split("结论：", 1)[1].split("（", 1)[0].strip()
            break
    return proc, got


# (说明, 额外参数, 期望 verdict（None=不检查）, 期望退出码)
CASES = [
    # ---- 带基线：证据闸参与判定 ----
    ("混版 20 轮（10 旧+10 新）+基线", ["--input", "data/ds08r_synthetic_mixed.json", "--baseline", BASELINE], "UNVERIFIED_VERSION", 1),
    ("全旧版 20 轮 +基线", ["--input", "data/ds08r_synthetic_all_old.json", "--baseline", BASELINE], "UNVERIFIED_VERSION", 1),
    ("全新版 20 轮 +基线（正对照）", ["--input", "data/ds08r_synthetic_verified.json", "--baseline", BASELINE], "PASS", 0),
    ("未确认送达 20 轮 +基线", ["--input", "data/ds08r_synthetic_undelivered.json", "--baseline", BASELINE], "UNVERIFIED_VERSION", 1),
    ("真实 6 轮（证据齐但样本不足）", ["--input", "data/ds08_cx01_rounds.json", "--baseline", BASELINE], "NOT_ENOUGH_DATA", 1),
    # ---- 不带基线：必须一律降级，绝不能 PASS（Codex 复核指出的绕过）----
    ("混版 20 轮 不带基线", ["--input", "data/ds08r_synthetic_mixed.json"], "UNVERIFIED_VERSION", 1),
    ("全新版 20 轮 不带基线", ["--input", "data/ds08r_synthetic_verified.json"], "UNVERIFIED_VERSION", 1),
    ("未确认送达 不带基线", ["--input", "data/ds08r_synthetic_undelivered.json"], "UNVERIFIED_VERSION", 1),
    # ---- 用法错误 ----
    # load_db() 在打开数据库之前就检查 --last，所以用占位路径即可，
    # 不必把本机路径与会话 uuid 写进仓库。
    (
        "缺 --last（用法错误）",
        [
            "--db", "PLACEHOLDER/data_v4.db",
            "--conversation", "PLACEHOLDER-CONVERSATION",
            "--since", "2026-10-25T17:06:00+08:00",
        ],
        None,
        2,
    ),
]

print("用例".ljust(34), "期望".ljust(20), "实际".ljust(20), "退出码".ljust(14), "结果")
print("-" * 104)

ok_all = True
for name, extra, want_verdict, want_code in CASES:
    proc, got = run(extra)
    verdict_ok = want_verdict is None or got == want_verdict
    ok = verdict_ok and proc.returncode == want_code
    ok_all = ok_all and ok
    print(
        name.ljust(34),
        (want_verdict or "—").ljust(20),
        (got or "—").ljust(20),
        f"{proc.returncode}(期望{want_code})".ljust(14),
        "符合" if ok else "**不符合**",
    )
    if not ok:
        # 失败时把子进程 stderr 尾部打出来，便于定位；不含任何正文
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        for line in tail:
            print("      stderr:", line)

print()
print("全部符合预期" if ok_all else "存在不符合项")
raise SystemExit(0 if ok_all else 1)
