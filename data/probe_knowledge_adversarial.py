"""DS-06 独立对抗探针：直接调用生产知识注入 handler + 生产 build_block。

不加载 AstrBot、不碰运行实例、不发 QQ。只 import 生产插件的 `MirukuKnowledge`
与 `knowledge/inject.py`，用假 event / req 走完整判定路径。

正负成对：每个「不该注入」的用例都配一个「该注入」的对照，并在同一轮里断言
对照真的注入过——避免探针写成「一律判不注入」也能全绿。

「库缺失 / 库损坏 / 空库 / 运行中删库」四种场景放在**子进程**里跑：
`inject.py` 会把 `query` 模块塞进 `sys.modules`，同进程里换 knowledge_root
会复用旧模块（这本身是审计发现之一），不隔离就测不准。

用法：
    python data/probe_knowledge_adversarial.py
    python data/probe_knowledge_adversarial.py --verbose
    python data/probe_knowledge_adversarial.py --allow-known
    python data/probe_knowledge_adversarial.py --scenario broken   # 内部用

退出码：0 全过；1 有失败（含未登记）；2 环境问题（找不到生产文件）。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = Path(
    r"C:\Users\OTTO\.astrbot_launcher\instances"
    r"\298681be-6ba8-4137-818c-28ed67ec9176\core"
)
INSTANCE_PLUGIN = CORE / "data/plugins/astrbot_plugin_miruku_knowledge/main.py"
REPO_PLUGIN = ROOT / "plugins/astrbot_plugin_miruku_knowledge/main.py"
KNOWLEDGE = ROOT / "knowledge"
DB = KNOWLEDGE / "miruku_knowledge.sqlite3"

BASE_PROMPT = "你是 Miruku。"
MARK = "<!-- miruku-knowledge -->"
TARGET = "10000002"
BASE_CFG = {
    "knowledge_root": str(KNOWLEDGE),
    "target_qq": TARGET,
    "platform_id": "miruku",
}

# 已知、暂不修的缺陷（登记后 `--allow-known` 才算过）。2026-10-24 F1 修完后清空。
KNOWN_BUGS: dict[str, str] = {}
# 已销账（留档，不要再登记）——F1：三条 b50 曲目的自然问法原本静默不注入
#   QUEEN 9.97 / Cthugha 9.92 / 不思議の国のクリスマス 7.00。
# 修法在 `knowledge/query.py`：新增 `loose_query()`（保留单字停用词、只摘
# 「多少分 / 什么评级 / 多少r」），别名在 clean 形式匹配不上时用它兜底。
# 三条用例现在按普通正例断言。

# 注入块正文里**永远不该出现**的内部痕迹（MARK 自身不算，先剥掉）。
FORBIDDEN_IN_BLOCK = (
    "knowledge/src",
    "sqlite3",
    ".sqlite3",
    "b50.json",
    "Traceback",
    "<!--",
)


class Event:
    def __init__(self, message, private=True, sender=TARGET, platform="miruku"):
        self.message_str = message
        self._private = private
        self._sender = sender
        self._platform = platform

    def is_private_chat(self):
        return self._private

    def get_sender_id(self):
        return self._sender

    def get_platform_id(self):
        return self._platform


class Req:
    def __init__(self, prompt=BASE_PROMPT):
        self.system_prompt = prompt


def load_handler():
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    spec = importlib.util.spec_from_file_location("miruku_knowledge_adv", REPO_PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_plugin(module, **cfg):
    plugin = object.__new__(module.MirukuKnowledge)
    plugin.config = dict(BASE_CFG, **cfg)
    plugin._build_block = None
    plugin._root = None
    return plugin


def make_builder():
    if str(KNOWLEDGE) not in sys.path:
        sys.path.insert(0, str(KNOWLEDGE))
    spec = importlib.util.spec_from_file_location("adv_inject", KNOWLEDGE / "inject.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# name, message, expect_inject, needle, pair(对照用例名)
CASES = [
    ("private-target", "KING 你多少分", True, ("KING",), None),
    ("private-other", "KING 你多少分", False, (), "private-target"),
    ("group-target", "KING 你多少分", False, (), "private-target"),
    ("platform-other", "KING 你多少分", False, (), "private-target"),
    ("empty", "", False, (), "song-title"),
    ("blank", "   ", False, (), "song-title"),
    ("sticker-only", "[图片:0A1B2C.jpg]", False, (), "song-title"),
    ("casual", "今天好累", False, (), "song-title"),
    ("casual-wrong", "在吗", False, (), "song-title"),
    ("song-title", "KING 你多少分", True, ("KING", "280"), None),
    ("song-alias", "鸟加怎么打", True, ("鸟加",), None),
    ("machine", "洗衣机是什么意思", True, ("洗衣机",), None),
    ("below-threshold", "school 的作业", False, (), "song-title"),
    ("b50-real", "KING 你多少分", True, ("280",), None),
    ("out-of-b50", "ロキ你多少分", True, ("ロキ", "只记最好的 50 首"), None),
    ("out-of-b50-noguard", "ロキ这歌怎么样", True, ("ロキ",), None),
    ("sf6-knows-not-plays", "你也打街霸6吗", True, ("街霸",), None),
    ("maimai-self", "你打舞萌吗", True, ("舞萌", "14065"), None),
    ("vtuber-ok", "hololive是什么", True, ("hololive",), None),
    ("sensitive-kaohe", "开盒是什么意思", False, (), "vtuber-ok"),
    ("sensitive-yanshang", "炎上是什么意思", False, (), "vtuber-ok"),
    ("sensitive-weipi", "卫批是什么", False, (), "vtuber-ok"),
    # —— F1（2026-10-24 已修）：b50 里真实有成绩、自然问法原本静默不注入 ——
    ("b50-queen", "QUEEN 多少分", True, ("QUEEN", "277"), None),
    ("b50-cthugha", "Cthugha 多少分", True, ("Cthugha", "281"), None),
    ("b50-fushigi", "不思議の国のクリスマス 多少分", True, ("クリスマス", "288"), None),
    # —— F1 修复的负对照：宽松兜底不能把日常词重新放进来 ——
    ("loose-neg-zhende", "真的假的", False, (), "b50-queen"),
    ("loose-neg-xuexiao", "学校的猫", False, (), "b50-queen"),
    ("loose-neg-jianyu", "监狱里那个", False, (), "b50-queen"),
]


async def run_case(plugin, case):
    name, msg, expect, needle, _pair = case
    ev = Event(msg)
    if name == "private-other":
        ev = Event(msg, sender="10001")
    elif name == "group-target":
        ev = Event(msg, private=False)
    elif name == "platform-other":
        ev = Event(msg, platform="webchat")
    req = Req()
    base = req.system_prompt
    await plugin.add_knowledge(ev, req)
    prompt = req.system_prompt
    injected = MARK in prompt
    growth = prompt[len(base):] if prompt.startswith(base) else ""
    problems = []
    if injected != expect:
        problems.append(f"注入={injected} 期望={expect}")
    if injected:
        if not prompt.startswith(base):
            problems.append("注入时改动了原 system_prompt 开头")
        body = growth.rstrip()
        if body.endswith(MARK):
            body = body[: -len(MARK)]
        if not growth.rstrip().endswith(MARK):
            problems.append("注入块未以 MARK 结尾")
        if "可参考的知识" not in body:
            problems.append("注入块缺少表头")
        for n in needle:
            if n not in body:
                problems.append(f"缺少期望内容「{n}」")
        for bad in FORBIDDEN_IN_BLOCK:
            if bad in body:
                problems.append(f"注入块泄漏内部痕迹「{bad}」")
        if len(growth) > 640:
            problems.append(f"注入块过长 {len(growth)} 字符")
        if name.startswith("out-of-b50"):
            if re.search(r"单曲\s*R|R\s?\d{3}|定数\s?\d", body):
                problems.append("表外曲目注入了具体成绩数字")
    else:
        if prompt != base:
            problems.append("不注入时 system_prompt 被改动")
    return name, problems


# ---------- 子进程场景（隔离 sys.modules 与文件锁） ----------

def _stage_root(root: Path, with_db: str | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for f in ("inject.py", "query.py"):
        (root / f).write_text(
            (KNOWLEDGE / f).read_text(encoding="utf-8"), encoding="utf-8"
        )
    if with_db == "copy":
        shutil.copy(DB, root / "miruku_knowledge.sqlite3")
    elif with_db == "empty":
        sqlite3.connect(root / "miruku_knowledge.sqlite3").close()
    elif with_db == "corrupt":
        (root / "miruku_knowledge.sqlite3").write_bytes(b"not a database")


async def scenario_main(kind: str) -> int:
    module = load_handler()
    tmp = Path(tempfile.mkdtemp(prefix=f"adv-{kind}-"))
    root = tmp / "k"
    out = {"scenario": kind, "injected": False, "escaped": None, "first_injected": None}
    try:
        if kind == "missing":
            _stage_root(root, None)
            plugin = make_plugin(module, knowledge_root=str(root))
            req = Req()
            await plugin.add_knowledge(Event("KING 你多少分"), req)
            out["injected"] = MARK in req.system_prompt
        elif kind in ("corrupt", "empty"):
            _stage_root(root, kind)
            plugin = make_plugin(module, knowledge_root=str(root))
            req = Req()
            await plugin.add_knowledge(Event("KING 你多少分"), req)
            out["injected"] = MARK in req.system_prompt
        elif kind == "deleted":
            _stage_root(root, "copy")
            plugin = make_plugin(module, knowledge_root=str(root))
            first = Req()
            await plugin.add_knowledge(Event("KING 你多少分"), first)
            out["first_injected"] = MARK in first.system_prompt
            (root / "miruku_knowledge.sqlite3").unlink()
            req = Req()
            await plugin.add_knowledge(Event("KING 你多少分"), req)
            out["injected"] = MARK in req.system_prompt
        else:
            out["escaped"] = f"unknown scenario {kind}"
    except BaseException as exc:  # noqa: BLE001
        out["escaped"] = type(exc).__name__
        out["message"] = str(exc)[:200]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


# ---------- 主流程 ----------

async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--allow-known", action="store_true")
    ap.add_argument("--scenario")
    args = ap.parse_args()
    if args.scenario:
        return await scenario_main(args.scenario)

    for p in (REPO_PLUGIN, KNOWLEDGE / "inject.py", DB):
        if not p.exists():
            print(f"环境缺失：{p}", file=sys.stderr)
            return 2

    module = load_handler()
    inject = make_builder()
    plugin = make_plugin(module)

    repo_h = hashlib.sha256(REPO_PLUGIN.read_bytes()).hexdigest()
    inst_h = (
        hashlib.sha256(INSTANCE_PLUGIN.read_bytes()).hexdigest()
        if INSTANCE_PLUGIN.exists()
        else "missing"
    )
    print(f"插件源码 sha256 仓库={repo_h[:16]} 实例={inst_h[:16]} 一致={repo_h == inst_h}")
    print(f"知识库 {DB.name} {DB.stat().st_size} 字节")

    results = await asyncio.gather(*[run_case(plugin, c) for c in CASES])
    status = {name: not probs for name, probs in results}
    failed, known, unknown = [], [], []
    for name, probs in results:
        if not probs:
            if args.verbose:
                print(f"PASS {name}")
            continue
        if name in KNOWN_BUGS:
            known.append(name)
            print(f"KNOWN {name}: {'; '.join(probs)}")
        else:
            unknown.append(name)
            failed.append(name)
            print(f"FAIL {name}: {'; '.join(probs)}")

    for name, _msg, _expect, _needle, pair in CASES:
        if pair and not status.get(pair, False):
            unknown.append(f"pair:{name}")
            print(f"FAIL pair:{name} 的对照 {pair} 未通过，负例断言不成立")

    special: list[str] = []

    # 幂等
    p = make_plugin(module)
    req = Req()
    await p.add_knowledge(Event("KING 你多少分"), req)
    first = req.system_prompt
    await p.add_knowledge(Event("KING 你多少分"), req)
    if req.system_prompt != first or first.count(MARK) != 1 or first.count("可参考的知识") != 1:
        special.append("重复调用不是幂等（MARK 数 %d）" % req.system_prompt.count(MARK))

    # target_qq 留空
    p_nt = make_plugin(module, target_qq="")
    req_nt = Req()
    await p_nt.add_knowledge(Event("KING 你多少分"), req_nt)
    if req_nt.system_prompt != BASE_PROMPT:
        special.append("target_qq 留空仍注入了")

    # 长输入上界
    req_l = Req()
    await make_plugin(module).add_knowledge(
        Event("KING 你多少分" + "啊" * 4000), req_l
    )
    growth = req_l.system_prompt[len(BASE_PROMPT):]
    if len(growth) > 640:
        special.append(f"长输入下注入块 {len(growth)} 字符，超过上界")

    # 子进程：四条库异常场景
    for kind in ("missing", "corrupt", "empty", "deleted"):
        cp = subprocess.run(
            [sys.executable, str(Path(__file__)), "--scenario", kind],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        line = [ln for ln in cp.stdout.splitlines() if ln.startswith("{")]
        data = json.loads(line[-1]) if line else {}
        if data.get("escaped"):
            special.append(f"场景 {kind} 逃逸异常 {data['escaped']}")
        if data.get("injected"):
            special.append(f"场景 {kind} 仍然注入了")
        if kind == "deleted" and not data.get("first_injected"):
            special.append("场景 deleted 前置失败：热缓存后首次没注入")
        if args.verbose:
            print(f"scenario {kind}: {data}")

    # F4（2026-10-24 已修）：load_entries 缺库原来抛 SystemExit（BaseException），
    # 插件的 `except Exception` 接不住，会把整个进程带走。现在改抛 RuntimeError。
    try:
        inject.build_block(
            "KING 你多少分",
            db_path=str(Path(tempfile.gettempdir()) / "no_such_adv.sqlite3"),
        )
        special.append("build_block 在库不存在时没有抛异常")
    except SystemExit:
        special.append(
            "build_block 库缺失仍抛 SystemExit（BaseException）——插件接不住，F4 回归"
        )
    except RuntimeError:
        pass  # 期望行为：普通异常，调用方能接住
    except Exception as exc:  # noqa: BLE001
        special.append(
            f"build_block 库缺失抛了 {type(exc).__name__}，期望 RuntimeError"
        )

    # 记录（不判红）：SCORE_GUARD 盲区
    blind = inject.build_block("ミクマリ多少分")
    print(f"记录：build_block('ミクマリ多少分') = {blind!r}（无块→兜底规则不生效）")

    for s in special:
        unknown.append(s)
        print(f"FAIL {s}")

    case_pass = sum(1 for _n, probs in results if not probs)
    special_pass = 4 - len(special)
    bad = len(failed) + len(known) + len(unknown)
    print(
        f"\n共 {len(CASES)} 条用例 + 4 项专项：通过 {case_pass + max(special_pass, 0)} / "
        f"失败/已登记 {bad}（未登记 {len(unknown)} / 已登记 {len(known)}）"
    )
    if args.allow_known:
        # 已登记的缺陷可以放过，但没登记的一个都不放过。
        if unknown:
            print("未登记的失败不允许放过")
            return 1
        return 0
    # 默认模式：已登记的缺陷也算失败——不许把已知故障伪装成全过。
    if known:
        print(f"已登记缺陷 {len(known)} 条仍存在（加 --allow-known 才放过）")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
