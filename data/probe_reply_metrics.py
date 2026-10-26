# -*- coding: utf-8 -*-
"""DS-08 探针：C-19 回复体量指标（中位 / P90 / 长度比 / 问句收尾 / 句数）。

为什么需要它
------------
CX-01 之后需要判断「她是不是还太长」，但日志里的 ``Prepare to send`` 只是
**准备发送**，不等于对方真的收到气泡；而库里又混着改版前后的回复。
本脚本只做一件事：**给定明确的样本集，算出可复现的聚合指标**，并把
「样本不足」「跨版本混算」这两种情况变成显式失败，而不是给出一个好看的平均数。

三种输入
--------
::

    # 1. 算法自检（固定合成样例，不需要任何真实数据）
    <venv>/Scripts/python.exe data/probe_reply_metrics.py --selftest

    # 2. 明确输入文件（推荐：人工从日志/库里摘出同版本、已确认气泡的若干轮）
    <venv>/Scripts/python.exe data/probe_reply_metrics.py --input rounds.json --baseline 2026-10-25T17:00:00+08:00

    # 3. 只读指定会话（必须同时给 --since 版本边界，否则拒绝运行）
    <venv>/Scripts/python.exe data/probe_reply_metrics.py \
        --db <instance>/core/data/data_v4.db \
        --conversation <uuid> --since 2026-10-25T17:06:00+08:00 --last 20

输入文件格式（``rounds.json``）::

    {
      "label": "cx01-r1",
      "cases": [
        {"id": "R1", "peer": "……", "bot": "……", "bot_time": "2026-10-25T17:10:00+08:00", "delivered": "confirmed", "exempt": "emotion"},
        {"id": "R2", "peer": "……", "bot": "……", "bot_time": "2026-10-25T17:11:00+08:00", "delivered": "confirmed"}
      ]
    }

``exempt`` 取值 ``emotion`` 或 ``crisis`` 时，该例**不参与长度比判据**
（``prompts/system.txt`` L5 明确给情绪与危机留了长度例外），但仍然统计长度。

判据（来自 CX-01 派单）
------------------------
- 中位长度 ≤ 15 字
- P90 ≤ 30 字
- 每轮「她 / 对方」长度比 ≤ 2（情绪、危机例外）
- 问句收尾率 ≤ 15%
- **样本 < 20 轮 → ``NOT_ENOUGH_DATA``**，不给通过结论

隐私边界
--------
只输出长度、比例、用例编号与聚合值；**不打印回复正文、不打印 QQ 号**。
会话 UUID 只以 8 位哈希出现。数据库用 ``mode=ro`` 打开，绝不写入。

退出码：0 全部判据通过；1 有判据未通过或数据不足；2 用法错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------- 判据阈值（与 CX-01 派单一致，改这里要同步改文档）----------
MAX_MEDIAN = 15
MAX_P90 = 30
MAX_RATIO = 2.0
MAX_QUESTION_RATE = 0.15
MIN_SAMPLES = 20

# 句末疑问标记：humanlike 会剥掉问号，所以不能只看 “？”
# 注意「呢」不能直接放进来——「我在这呢」「Miruku 在这呢」是陈述句收语气词。
# 「呢」的处理见 MODAL_TAIL + BARE_PRONOUN：先剥语气词，剩下的若是光杆代词才算问。
QUESTION_TAIL = re.compile(
    r"(吗|什么|怎么|多少|哪儿|哪里|哪家|哪个|几点|要不要|是不是|有没有|好不好|行不行)$"
)
# 句末语气词（不改变陈述/疑问性质），判疑问前先剥掉
MODAL_TAIL = re.compile(r"[呢吧啊呀哦噢喔嘛啦]+$")
# 「你呢」「他们呢」这种光杆代词 + 呢 才算问句
BARE_PRONOUN = re.compile(r"(你|您|我|他|她|它|你们|我们|他们|她们|它们|大家)$")
# 句级切分：真正的句末
SENTENCE_END = re.compile(r"[。！？!?]")
# 分句切分：逗号、顿号、分号、换行
CLAUSE_SEP = re.compile(r"[，,、；;\n]")
# 聊天里的占位符（图片、表情等），不参与字数
PLACEHOLDER = re.compile(r"\[(图片|表情|语音|视频|文件|动画表情)[^\]]*\]")
# 图片走 vision provider 时 AstrBot 会追加 `[Image 1: original path <本机路径>]` 这类描述。
# 这是**本地文件路径**，不是对方说的话：既不该计字数（实测一条 161 字里 130+ 是路径），
# 也不该出现在任何输出里。整段剔除。
IMAGE_PATH_NOTE = re.compile(r"\[Image\s*\d+[^\]]*\]", re.I)
# 系统注入的时间提醒，不属于任何一方的话
SYSTEM_REMINDER = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)

EXEMPT_KINDS = ("emotion", "crisis")

# 插件注入的假轮次，不是真实对话，必须剔除。
#   `astrbot_plugin_emotionai` 每轮在 on_llm_request 末尾追加：
#   user「（系统自检：请报告当前情感状态）」+ assistant 的 <thought> 样本 + 一条 system FORCE_MSG。
#   这些消息会被 AstrBot 一起落库，若按 user→assistant 成对切轮，会把它们算成真实对话，
#   从而把「她中位长度」拉低（假样本很短）。实测：若不剔除，最后 6 轮里混进 1 轮假样本。
INJECTED_PEER = "（系统自检"
INJECTED_PROTOCOL = "[PROTOCOL_ENFORCEMENT]"


class UsageError(Exception):
    """用法错误（退出码 2）。与「判据未通过」（退出码 1）区分开。"""


@dataclass
class Case:
    id: str
    peer: str
    bot: str
    exempt: str | None = None
    note: str = ""
    # 逐轮版本与收件端证据。只有两项都齐，这一轮才有资格计入新版本验收。
    #   bot_time    : 该条回复的实际发送时间（ISO，带时区）。必须 ≥ 版本基线。
    #   delivered   : 收件端是否确认收到（"confirmed" / 其他视为未确认）。
    bot_time: str | None = None
    delivered: str | None = None
    version_verified: bool = False
    # 该轮是否通过了版本/收件端核验；由 verify_cases() 写，measure() 只读
    evidence_ok: bool = False


@dataclass
class Result:
    case_id: str
    peer_len: int
    bot_len: int
    ratio: float
    question: bool
    sentences: int
    clauses: int
    exempt: str | None
    # 版本与收件端是否已逐轮核验（由 apply_version_gate 写）
    version_verified: bool = False
    # 原始文本只留在内部，绝不进输出
    _peer: str = field(default="", repr=False)
    _bot: str = field(default="", repr=False)


# ---------------------------------------------------------------- 基础计算


def clean(text: str) -> str:
    """去掉系统注入、占位符与本地图片路径，返回判据用的文本。"""
    text = SYSTEM_REMINDER.sub("", text or "")
    text = IMAGE_PATH_NOTE.sub("", text)
    text = PLACEHOLDER.sub("", text)
    # assistant 的 think 段不算正文
    if "</thought>" in text:
        text = text.split("</thought>")[-1]
    return text.strip()


def is_question(text: str) -> bool:
    """句末带疑问词或问号即视为问句收尾。

    「呢」单独出现时既可能是疑问（你呢）也可能是陈述收语气词（我在这呢），
    所以先剥语气词：剥完是光杆代词才算问，剥完还有其他内容就算陈述。
    """
    body = text.strip()
    if not body:
        return False
    if body[-1] in "？?":
        return True
    tail = re.sub(r"[\s~…。！？!?、，,]+$", "", body)
    if QUESTION_TAIL.search(tail):
        return True
    if tail.endswith("呢"):
        # 「你呢」「他们呢」→ 问；「我在这呢」「在这呢」→ 陈述
        return bool(BARE_PRONOUN.search(MODAL_TAIL.sub("", tail)))
    return False


def sentence_count(text: str) -> int:
    """按真正的句末标点计数，最少 1。"""
    body = text.strip()
    if not body:
        return 0
    return max(1, len(SENTENCE_END.findall(body)) + (0 if SENTENCE_END.search(body[-1:]) else 1))


def clause_count(text: str) -> int:
    """按逗号/顿号/换行切出来的片段数，最少 1。"""
    body = text.strip()
    if not body:
        return 0
    return max(1, len([p for p in CLAUSE_SEP.split(body) if p.strip()]))


def measure(case: Case) -> Result:
    peer = clean(case.peer)
    bot = clean(case.bot)
    peer_len = len(peer)
    bot_len = len(bot)
    ratio = (bot_len / peer_len) if peer_len else float("inf")
    return Result(
        case_id=case.id,
        peer_len=peer_len,
        bot_len=bot_len,
        ratio=ratio,
        question=is_question(bot),
        sentences=sentence_count(bot),
        clauses=clause_count(bot),
        exempt=case.exempt,
        _peer=peer,
        _bot=bot,
        version_verified=False,
    )


def percentile(values: list[int], q: float) -> float:
    """最近秩法求分位数（与统计口径一致，便于人工复核）。"""
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * q))
    return float(ordered[idx])


def median(values: list[int]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


# ---------------------------------------------------------------- 版本闸


def verify_cases(cases: list[Case], baseline: str | None) -> tuple[bool, list[str]]:
    """逐轮核验版本与收件端证据。

    给 PASS 的前提是**每一轮**都同时满足：
      1. ``bot_time`` 可解析且 ≥ ``baseline``（版本基线时间）；
      2. ``delivered == "confirmed"``（收件端确认收到气泡）。

    缺任意一项 → 该轮 ``evidence_ok=False``，整批 ``version_verified=False``。
    设计意图：**宁可判 NOT_ENOUGH_DATA / UNVERIFIED_VERSION，也不给假 PASS**。
    只信任手填标签（例如「这些都是改版后的」）是不够的——那正是上一版的漏洞。
    """
    from datetime import datetime

    problems: list[str] = []
    if not baseline:
        return False, ["未提供 --baseline（版本基线时间），无法核验任何一轮的版本归属。"]

    try:
        base_dt = datetime.fromisoformat(baseline)
    except ValueError:
        return False, [f"--baseline 无法解析为时间：{baseline!r}"]

    ok_count = 0
    for c in cases:
        c.evidence_ok = False
        if not c.bot_time:
            problems.append(f"{c.id}：缺 bot_time（该条回复的实际发送时间）")
            continue
        try:
            t = datetime.fromisoformat(c.bot_time)
        except ValueError:
            problems.append(f"{c.id}：bot_time 无法解析（{c.bot_time!r}）")
            continue
        if t.tzinfo is None or base_dt.tzinfo is None:
            problems.append(f"{c.id}：时间必须带时区（bot_time={c.bot_time!r}）")
            continue
        if t < base_dt:
            problems.append(
                f"{c.id}：bot_time {c.bot_time} 早于基线 {baseline} —— 属于旧版本，不得计入"
            )
            continue
        if c.delivered != "confirmed":
            problems.append(f"{c.id}：收件端未确认（delivered={c.delivered!r}，需 \"confirmed\"）")
            continue
        c.evidence_ok = True
        ok_count += 1

    all_ok = ok_count == len(cases) and len(cases) > 0
    return all_ok, problems


def apply_version_gate(results: list[Result], cases: list[Case]) -> bool:
    """把 evidence_ok 同步到 Result，返回整批是否全部通过版本闸。"""
    by_id = {c.id: c for c in cases}
    for r in results:
        c = by_id.get(r.case_id)
        r.version_verified = bool(c and c.evidence_ok)
    return bool(results) and all(r.version_verified for r in results)


# ---------------------------------------------------------------- 报告


def build_report(
    results: list[Result], label: str, gate_ok: bool | None = None, *, _internal: bool = False
) -> dict:
    """只含聚合与编号，不含任何正文。

    ``gate_ok``：
      - ``True``  ：逐轮证据齐备，允许按数字判 PASS/FAIL
      - ``False`` ：证据不全 → ``UNVERIFIED_VERSION``，**永不给 PASS**
      - ``None``  ：**仅限自检内部**（``_internal=True``）做纯算法验证。
                    CLI 路径若传 None 且未声明 internal，按 ``False`` 处理，
                    防止「没核验」被当成「核验通过」——这正是上一版的绕过。
    """
    if gate_ok is None and not _internal:
        gate_ok = False
    n = len(results)
    bot_lens = [r.bot_len for r in results]
    peer_lens = [r.peer_len for r in results]
    counted = [r for r in results if r.exempt not in EXEMPT_KINDS]
    ratios = [r.ratio for r in counted if r.peer_len > 0]

    report = {
        "label": label,
        "n": n,
        "exempt_n": n - len(counted),
        "median_bot": median(bot_lens),
        "mean_bot": round(sum(bot_lens) / n, 2) if n else float("nan"),
        "p90_bot": percentile(bot_lens, 0.9),
        "max_bot": max(bot_lens) if n else 0,
        "median_peer": median(peer_lens),
        "median_ratio": median([round(r.ratio, 3) for r in counted if r.peer_len]) if counted else float("nan"),
        "max_ratio": max(ratios) if ratios else float("nan"),
        "question_rate": sum(1 for r in results if r.question) / n if n else 0.0,
        "multi_sentence_rate": sum(1 for r in results if r.sentences > 1) / n if n else 0.0,
        "multi_clause_rate": sum(1 for r in results if r.clauses > 2) / n if n else 0.0,
        "ratio_pass_ids": [r.case_id for r in counted if r.peer_len and r.ratio <= MAX_RATIO],
        "ratio_fail_ids": [r.case_id for r in counted if r.peer_len and r.ratio > MAX_RATIO],
        "question_ids": [r.case_id for r in results if r.question],
        "exempt_ids": [r.case_id for r in results if r.exempt in EXEMPT_KINDS],
    }

    verdicts = []
    if n < MIN_SAMPLES:
        verdicts.append(("SAMPLES", False, f"{n} < {MIN_SAMPLES}（NOT_ENOUGH_DATA）"))
    else:
        verdicts.append(("SAMPLES", True, f"{n} ≥ {MIN_SAMPLES}"))
        verdicts.append(("MEDIAN", report["median_bot"] <= MAX_MEDIAN,
                         f"{report['median_bot']} ≤ {MAX_MEDIAN}"))
        verdicts.append(("P90", report["p90_bot"] <= MAX_P90,
                         f"{report['p90_bot']:.0f} ≤ {MAX_P90}"))
        verdicts.append(("QUESTION_RATE", report["question_rate"] <= MAX_QUESTION_RATE,
                         f"{report['question_rate']:.0%} ≤ {MAX_QUESTION_RATE:.0%}"))
        report["ratio_ok"] = not report["ratio_fail_ids"]
        verdicts.append(("RATIO", report["ratio_ok"],
                         f"超限 {len(report['ratio_fail_ids'])} 例：{report['ratio_fail_ids'] or '无'}"))
    report["verdicts"] = [{"criterion": c, "pass": ok, "detail": d} for c, ok, d in verdicts]

    # 版本/收件端闸：优先级高于一切判据。gate_ok=False 时**无论数字多漂亮都不给 PASS**。
    report["version_verified"] = all(r.version_verified for r in results) if results else False
    if n < MIN_SAMPLES:
        report["verdict"] = "NOT_ENOUGH_DATA"
    elif gate_ok is None:
        # 只有 _internal=True 的自检才可能走到这里（其余已在函数开头被降为 False）
        report["verdict"] = "PASS" if all(ok for _, ok, _ in verdicts) else "FAIL"
    elif gate_ok is False or not report["version_verified"]:
        report["verdict"] = "UNVERIFIED_VERSION"
    else:
        report["verdict"] = "PASS" if all(ok for _, ok, _ in verdicts) else "FAIL"
    return report


def print_report(report: dict, results: list[Result]) -> None:
    print(f"== 样本集：{report['label']} ==")
    print(f"   轮数 {report['n']}（其中长度比豁免 {report['exempt_n']} 例：{report['exempt_ids'] or '无'}）")
    print()
    print("   用例  她(字)  对方(字)  长度比  问句  句数  分句  豁免  版本核验")
    for r in results:
        ratio = "—" if r.peer_len == 0 else f"{r.ratio:>6.2f}"
        mark = "问" if r.question else "  "
        flag = " *" if r.exempt in EXEMPT_KINDS else ""
        ver = "已核验" if r.version_verified else "**未核验**"
        print(
            f"   {r.case_id:<6}{r.bot_len:>7}{r.peer_len:>9}{ratio:>8}   {mark}"
            f"{r.sentences:>5}{r.clauses:>6}   {r.exempt or '—':<8}{ver}"
        )
    print()
    print(f"   她：中位 {report['median_bot']}  均值 {report['mean_bot']}  P90 {report['p90_bot']:.0f}  最长 {report['max_bot']}")
    print(f"   对方：中位 {report['median_peer']}")
    print(f"   长度比：中位 {report['median_ratio']}  最大 {report['max_ratio']}")
    print(f"   问句收尾 {report['question_rate']:.0%}   多句 {report['multi_sentence_rate']:.0%}   超过两个分句 {report['multi_clause_rate']:.0%}")
    print()
    print("   判定：")
    for v in report["verdicts"]:
        print(f"     [{'通过' if v['pass'] else '未过'}] {v['criterion']:<12} {v['detail']}")
    print()
    tail = {
        "NOT_ENOUGH_DATA": "（样本不足，本结果不能作为 C-19 验收结论）",
        "UNVERIFIED_VERSION": "（版本/收件端证据不全，本结果不能作为新版本验收结论）",
        "PASS": "（仅表示本样本集通过统计判据，不等于 C-19 已修好）",
    }.get(report["verdict"], "")
    print(f"   结论：{report['verdict']}{tail}")
    if report["ratio_fail_ids"]:
        print(f"   超长度比的用例：{report['ratio_fail_ids']}（需逐条看是否属于情绪/危机例外）")


# ---------------------------------------------------------------- 输入


def load_input(path: str) -> tuple[str, list[Case], list[str]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    cases = []
    for i, item in enumerate(data.get("cases", []), start=1):
        cases.append(
            Case(
                id=str(item.get("id") or f"R{i}"),
                peer=str(item.get("peer", "")),
                bot=str(item.get("bot", "")),
                exempt=item.get("exempt"),
                note=str(item.get("note", "")),
                bot_time=item.get("bot_time"),
                delivered=item.get("delivered"),
            )
        )
    return str(data.get("label") or "input"), cases, []


def load_db(
    db_path: str, conversation: str, since: str, last: int | None = None
) -> tuple[str, list[Case], list[str]]:
    """从只读库读指定会话的 user→assistant 成对轮次。

    **诚实边界**：``conversations.content`` 里的消息**没有逐条时间戳**，
    所以「--since 版本边界」在库这一层**无法真正过滤**。本函数只做两件事：
    ① 用会话级 ``updated_at`` 证明这条会话在该时间点**之后被写过**；
    ② 取**最后 ``last`` 轮**，由调用方负责确认这些轮次确实是改版后产生的。

    返回 ``(label, cases, warnings)``；warnings 必须原样打进报告，
    否则使用者会以为边界被强制了。

    **版本闸的真实结论**：``conversations.content`` 的每条消息**没有时间戳**，
    所以「--since」在库这一层**无法逐轮验证版本**。因此本模式产出的样本一律带
    ``version_verified=False``，最终判定只能给 ``UNVERIFIED_VERSION``——
    **永远不可能给 PASS**。要拿 PASS，必须走 ``--input`` 并附可核验的逐轮时间证据。
    """
    from datetime import datetime, timezone

    if not last:
        raise UsageError(
            "--db 模式必须给 --last（取最后 N 轮）。\n"
            "理由：消息没有逐条时间戳，无法按 --since 过滤；只能由调用方确认「最后 N 轮都是改版后的」，"
            "而调用方的口头确认不足以构成版本闸。"
        )
    since_dt = datetime.fromisoformat(since)
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select content, updated_at from conversations where conversation_id=?", (conversation,)
        ).fetchone()
    finally:
        con.close()
    if not row:
        raise UsageError(f"找不到会话（uuid 哈希 {hash8(conversation)}）")

    warnings: list[str] = [
        f"库内消息没有逐条时间戳，--since 无法逐轮过滤；本次只取最后 {last} 轮，"
        "**版本归属未经逐轮验证**，因此本次结果不可能判 PASS。"
    ]
    # 会话级 updated_at 是 UTC 裸时间，只能证明「被写过」，不能证明每条消息的归属
    try:
        upd = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
        if upd < since_dt:
            warnings.append(
                f"会话最后更新时间 {upd.isoformat()} 早于 --since {since_dt.isoformat()}，"
                "这些回复属于**旧版本**，不得计入新版本验收。"
            )
    except Exception:
        warnings.append("无法解析会话 updated_at，版本归属完全依赖调用方。")

    msgs = json.loads(row[0])
    rounds: list[Case] = []
    pending_peer: str | None = None
    skipped_injected = 0
    for m in msgs:
        role = m.get("role")
        text = content_text(m.get("content"))
        if role == "user":
            # 注入的假 user（系统自检）不开新一轮，并把它后面那条假 assistant 一起吃掉
            if text.strip().startswith(INJECTED_PEER):
                pending_peer = None
                skipped_injected += 1
                continue
            pending_peer = text
        elif role == "system" and INJECTED_PROTOCOL in text:
            skipped_injected += 1
            continue
        elif role == "assistant" and pending_peer is not None:
            rounds.append(Case(id=f"T{len(rounds) + 1}", peer=pending_peer, bot=text))
            pending_peer = None
        elif role == "assistant":
            # 没有对应 user 的 assistant（紧跟注入样本），直接丢弃
            skipped_injected += 1

    if skipped_injected:
        warnings.append(f"已剔除 {skipped_injected} 条插件注入的假消息（系统自检 / PROTOCOL_ENFORCEMENT）。")

    if last and len(rounds) > last:
        rounds = rounds[-last:]
        for i, c in enumerate(rounds, start=1):
            c.id = f"L{i}"  # 标注是「最后 N 轮」口径

    # 版本闸：库模式**无法**逐轮证明版本，故整批标 False
    for c in rounds:
        c.version_verified = False

    label = f"db:{hash8(conversation)}:last{last}"
    return label, rounds, warnings


def content_text(content) -> str:
    """把分片列表或 repr 字符串还原成纯文本。

    AstrBot 的 ``conversations.content`` 有两种历史形态：正常的 list[dict] 分片，
    以及被旧版插件 ``str()`` 成的 **Python repr 字符串**。后者必须解析，但**绝不能 eval**：
    数据库内容属于外部输入，``eval`` 会执行里面的任意表达式。

    这里用 ``ast.literal_eval``——只接受字面量，遇到调用、下标、属性访问等一律抛错；
    解析失败就把整段当纯文本（最坏结果是字数略偏大，绝不会执行代码）。
    """
    import ast

    def parsed_parts(c):
        """返回 (parts, ok)。ok=False 表示不能按结构解析，应按纯文本处理。"""
        if isinstance(c, list):
            return c, True
        if not isinstance(c, str):
            return None, False
        s = c.strip()
        if not (s.startswith("[") and s.endswith("]")):
            return None, False
        try:
            value = ast.literal_eval(s)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return None, False
        if isinstance(value, list):
            return value, True
        return None, False

    parts, ok = parsed_parts(content)
    if not ok:
        return str(content)

    out = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            out.append(p.get("text") or "")
    return "".join(out)


def hash8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------- 自检


def selftest() -> int:
    """固定合成样例，逐个断言算法正确。全部通过退 0。"""
    failures: list[str] = []
    seen: list[str] = []

    def expect(name: str, got, want) -> None:
        seen.append(name)
        ok = got == want
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")
        if not ok:
            failures.append(name)

    print("== 合成样例自检 ==")

    # 1. 长度：占位符、系统提醒、图片路径都不计入
    c = Case(id="S1", peer="abc", bot="[图片:abc.jpg]你好<system_reminder>x</system_reminder>")
    r = measure(c)
    expect("占位符不计字", r.bot_len, 2)
    expect("reminder 不计字", r.peer_len, 3)
    c2 = Case(id="S2", peer="[图片][Image 1: original path EXAMPLE.png]", bot="盯")
    r2 = measure(c2)
    expect("图片路径不计字", r2.peer_len, 0)
    expect("图片轮长度比不炸", r2.ratio, float("inf"))

    # 2. 问句判定（问号被剥掉时靠疑问词）
    expect("句末「吗」=问句", is_question("你吃了吗"), True)
    expect("光杆「你呢」=问句", is_question("你呢"), True)
    expect("「你们呢」=问句", is_question("你们呢"), True)
    expect("「我在这呢」不是问句", is_question("不是麻烦，Miruku 在这呢"), False)
    expect("「在这呢」不是问句", is_question("在这呢"), False)
    expect("问号=问句", is_question("在吗？"), True)
    expect("陈述句=非问句", is_question("吃了"), False)
    expect("问句在中间不算收尾", is_question("吃什么了 我吃了"), False)

    # 3. 句数 / 分句
    expect("单句", sentence_count("好的"), 1)
    expect("无标点单句", sentence_count("好的走吧明天见"), 1)
    expect("逗号不算句末", sentence_count("好的，明天见"), 1)
    expect("一个句号=两句", sentence_count("好的，走吧。明天见"), 2)
    expect("句号结尾不重复计", sentence_count("好的。明天见。"), 2)
    expect("分句数", clause_count("行啊，那你先打过再说"), 2)

    # 4. 中位 / P90
    expect("中位-偶数", median([4, 8, 4, 12]), 6.0)
    expect("中位-奇数", median([1, 2, 3]), 2.0)
    expect("P90", percentile([4, 4, 8, 12], 0.9), 12.0)
    expect("P90-单点", percentile([7], 0.9), 7.0)

    # 5. 长度比与豁免
    cases = [
        Case(id="A", peer="12345678", bot="12345678"),          # 1.00
        Case(id="B", peer="1234", bot="12345678"),              # 2.00
        Case(id="C", peer="1234", bot="12345678"),              # 2.00
        Case(id="D", peer="1234", bot="123412"),                # 1.50
        Case(id="E", peer="12", bot="12345678", exempt="emotion"),  # 4.00 但豁免
    ]
    results = [measure(c) for c in cases]
    report = build_report(results, "selftest")
    expect("比值-豁免不进 max", report["max_ratio"], 2.0)
    expect("比值-豁免不进 fail 列表", report["ratio_fail_ids"], [])
    expect("豁免计数", report["exempt_n"], 1)
    expect("样本不足", report["verdict"], "NOT_ENOUGH_DATA")

    # 6. 样本足够时的判据
    many = [Case(id=f"M{i}", peer="1234567890", bot="12345") for i in range(MIN_SAMPLES)]
    rep2 = build_report([measure(c) for c in many], "selftest2", _internal=True)
    expect("样本充足", rep2["verdict"], "PASS")
    expect("中位", rep2["median_bot"], 5.0)
    expect("问句率", rep2["question_rate"], 0.0)

    # 7. 故意超限 → FAIL
    bad = [Case(id=f"X{i}", peer="1234", bot="123456789012") for i in range(MIN_SAMPLES)]
    rep3 = build_report([measure(c) for c in bad], "selftest3", _internal=True)
    expect("超限判 FAIL", rep3["verdict"], "FAIL")

    # 8. 安全解析：repr 分片能还原，恶意表达式不执行
    repr_case = (
        "[{'type': 'text', 'text': '你好'}, {'type': 'text', 'text': '世界'}]"
    )
    expect("repr 分片还原", content_text(repr_case), "你好世界")
    evil = "[__import__('os').system('echo PWNED')]"
    got = content_text(evil)
    expect("恶意表达式不执行（退化为原文）", got, evil)
    evil2 = "[open('x','w')]"
    expect("函数调用不执行", content_text(evil2), evil2)
    evil3 = "[*range(3)]"
    expect("星号解包不执行", content_text(evil3), evil3)
    expect("非列表字符串原样", content_text("普通文本"), "普通文本")
    expect("空列表", content_text("[]"), "")

    # 9. 版本闸：缺证据一律不给 PASS
    many_ok = [Case(id=f"V{i}", peer="1234567890", bot="12345") for i in range(MIN_SAMPLES)]
    gate_ok, problems = verify_cases(many_ok, "2026-10-25T17:00:00+08:00")
    expect("缺 bot_time 时闸不过", gate_ok, False)
    expect("缺证据给出问题条目", len(problems) >= MIN_SAMPLES, True)

    good = [
        Case(
            id=f"G{i}",
            peer="1234567890",
            bot="12345",
            bot_time="2026-10-25T18:00:00+08:00",
            delivered="confirmed",
        )
        for i in range(MIN_SAMPLES)
    ]
    gate_ok2, problems2 = verify_cases(good, "2026-10-25T17:00:00+08:00")
    expect("证据齐备时闸通过", gate_ok2, True)
    expect("证据齐备无问题", problems2, [])

    # 10. 混版反例：一半旧版一半新版 → 必须判 UNVERIFIED_VERSION，绝不能 PASS
    mixed = []
    for i in range(MIN_SAMPLES):
        ts = "2026-10-25T10:00:00+08:00" if i % 2 == 0 else "2026-10-25T18:00:00+08:00"
        mixed.append(
            Case(
                id=f"MX{i}",
                peer="1234567890",
                bot="12345",
                bot_time=ts,
                delivered="confirmed",
            )
        )
    gate_ok3, problems3 = verify_cases(mixed, "2026-10-25T17:00:00+08:00")
    expect("混版闸不过", gate_ok3, False)
    expect("混版报出旧版条目数", len(problems3), MIN_SAMPLES // 2)
    res_mixed = [measure(c) for c in mixed]
    apply_version_gate(res_mixed, mixed)
    rep4 = build_report(res_mixed, "mixed", gate_ok=gate_ok3)
    expect("混版判 UNVERIFIED_VERSION", rep4["verdict"], "UNVERIFIED_VERSION")

    # 11. 20 轮全部旧版 → 也必须是 UNVERIFIED_VERSION（数字再漂亮也不给 PASS）
    old = [
        Case(
            id=f"O{i}",
            peer="1234567890",
            bot="12345",
            bot_time="2026-10-25T10:00:00+08:00",
            delivered="confirmed",
        )
        for i in range(MIN_SAMPLES)
    ]
    gate_ok4, _ = verify_cases(old, "2026-10-25T17:00:00+08:00")
    res_old = [measure(c) for c in old]
    apply_version_gate(res_old, old)
    rep5 = build_report(res_old, "all-old", gate_ok=gate_ok4)
    expect("全旧版判 UNVERIFIED_VERSION", rep5["verdict"], "UNVERIFIED_VERSION")

    # 12. 未确认送达 → 闸不过
    undelivered = [
        Case(
            id=f"U{i}",
            peer="1234567890",
            bot="12345",
            bot_time="2026-10-25T18:00:00+08:00",
            delivered="sent",
        )
        for i in range(MIN_SAMPLES)
    ]
    gate_ok5, _ = verify_cases(undelivered, "2026-10-25T17:00:00+08:00")
    expect("未确认送达闸不过", gate_ok5, False)

    # 13. 证据齐备 + 数字合格 → 才可能 PASS
    res6 = [measure(c) for c in good]
    apply_version_gate(res6, good)
    rep6 = build_report(res6, "verified-good", gate_ok=gate_ok2)
    expect("证据齐备且合格 = PASS", rep6["verdict"], "PASS")

    # 14. 闸关闭（None）**只允许自检内部**使用；对外传 None 会被降级为 False
    rep7 = build_report([measure(c) for c in many], "gate-none", gate_ok=None, _internal=True)
    expect("gate=None + internal 时只看数字", rep7["verdict"], "PASS")

    # 15. 防绕过：对外传 gate_ok=None（未声明 internal）必须降级，绝不能 PASS
    rep8 = build_report([measure(c) for c in many], "gate-none-public", gate_ok=None)
    expect("对外 gate=None 降级为 UNVERIFIED_VERSION", rep8["verdict"], "UNVERIFIED_VERSION")

    print()
    if failures:
        print(f"自检失败 {len(failures)} 项：{failures}")
        return 1
    print(f"自检全部通过（{len(seen)} 项）")
    return 0


# ---------------------------------------------------------------- 入口


def main() -> int:
    ap = argparse.ArgumentParser(description="C-19 回复体量指标探针（只读）")
    ap.add_argument("--selftest", action="store_true", help="用固定合成样例验证算法与版本闸")
    ap.add_argument("--input", help="样本 JSON 文件（须含逐轮 bot_time / delivered）")
    ap.add_argument("--db", help="data_v4.db 路径（只读）。此模式无法逐轮验证版本，最高只能给 UNVERIFIED_VERSION")
    ap.add_argument("--conversation", help="会话 uuid（与 --db 同用）")
    ap.add_argument("--since", help="会话级参考时间（与 --db 同用，必填；仅能核验会话最后更新时间）")
    ap.add_argument(
        "--last",
        type=int,
        default=None,
        help="与 --db 同用，必填：取最后 N 轮。消息无逐条时间戳，--since 无法逐轮过滤",
    )
    ap.add_argument(
        "--baseline",
        default=None,
        help="版本基线 ISO 时间（带时区）。每轮 bot_time 必须 ≥ 它才可能给 PASS",
    )
    ap.add_argument("--label", default=None, help="样本集名称（写进报告标题）")
    ap.add_argument(
        "--require-evidence",
        action="store_true",
        help="强制要求逐轮 bot_time + delivered=confirmed（给了 --baseline 时自动开启）",
    )
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    try:
        if args.input:
            label, cases, warnings = load_input(args.input)
        elif args.db:
            if not (args.conversation and args.since):
                raise UsageError("--db 必须同时给 --conversation 和 --since")
            label, cases, warnings = load_db(args.db, args.conversation, args.since, args.last)
        else:
            ap.print_help()
            return 2
    except UsageError as exc:
        print(f"用法错误：{exc}", file=sys.stderr)
        return 2

    if not cases:
        print("用法错误：样本为空", file=sys.stderr)
        return 2

    results = [measure(c) for c in cases]

    # 版本/收件端闸。**CLI 路径永不允许 gate_ok=None**：那会把「没核验」当成「核验通过」。
    # 缺 --baseline 或缺逐轮证据 → 一律 UNVERIFIED_VERSION。
    # gate_ok=None 只保留给自检内部调用（见 selftest），不对外暴露。
    gate_ok, gate_problems = verify_cases(cases, args.baseline)
    apply_version_gate(results, cases)
    if args.db and not args.baseline:
        gate_problems = ["库模式无法逐轮验证版本与收件端证据；且未提供 --baseline。"] + gate_problems
        gate_ok = False

    report = build_report(results, args.label or label, gate_ok=gate_ok)
    print_report(report, results)

    if gate_problems:
        print()
        print("   [证据问题] 版本/收件端证据问题：")
        for p in gate_problems[:20]:
            print(f"     · {p}")
        if len(gate_problems) > 20:
            print(f"     · …另有 {len(gate_problems) - 20} 条同类问题")

    if warnings:
        print()
        print("   [注意] 数据可信边界（必读）：")
        for w in warnings:
            print(f"     · {w}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
