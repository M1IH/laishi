# -*- coding: utf-8 -*-
"""Miruku 语言评分细则 v1.0 的实现。

规范正文：docs/tone-rubric-spec.md（冲突时以该文件为准）
设计说明：docs/tone-rubric.md

用法：
    # 批次评分（默认模式，样本 <50 输出 INSUFFICIENT_SAMPLE）
    python data/tone_score.py --turns .tmp-tone/turns_export.json
    python data/tone_score.py --turns .tmp-tone/turns_export.json --limit 100
    python data/tone_score.py --turns .tmp-tone/turns_export.json --recent 100 --json

    # 单条评分（抽检）
    python data/tone_score.py --single "好，记住了，以后先问称呼"

    # 自检
    python data/tone_score.py --selftest

turns JSON 结构（由服务器侧导出的对话轮次）：
    [{"conversation_id": "...", "user_id": "miruku:FriendMessage:...",
      "turns": [{"role": "user"|"assistant", "texts": ["..."], "proactive_prompt": bool}]}]

只输出分数与命中片段（≤12 字），不含回复全文、不含 QQ 号。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE_DIR = os.path.dirname(os.path.abspath(__file__))

VERSION = "1.2"

# ── 权重（v1.0 定稿：20 / 15 / 35 / 20 / 10）──────────────────────────────
W = {"D1": 20, "D2": 15, "D3": 35, "D4": 20, "D5": 10}
D5_BASE = 7

MIN_SAMPLE = 50

# D3/D4 的饱和点：每 100 条命中扣分累计到这个数，该维就算扣满。
# 取 100 = 「每百条一次 C3（−7 分）相当于扣掉 7% 的 D3」的直读刻度，
# 同时真实语料最坏的一天（2026-10-20，11 次 C3 + 1 次 C5，118.4 分/百条）
# 正好封顶，不会因为个别极端措辞把整维压到 0 而掩盖其他维度。
D3_SATURATION = 100.0
D4_SATURATION = 100.0

PLACEHOLDER = re.compile(r"\[(?:图片|表情|语音|视频|文件|动画表情|回复|引用|@|CQ)[^\]]*\]")
REMINDER = re.compile(r"<system_reminder>.*?</system_reminder>", re.S)
DATA_URI = re.compile(r"data:[a-zA-Z]+/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+")

# ── 第 0 层：红线 ────────────────────────────────────────────────────────
R1_PAT = re.compile(r"<system_reminder>|DSML|```")
R2_WORD = re.compile(r"提示词|prompt|模型|部署|接口|系统", re.I)
R2_VERB = re.compile(r"是|采用|使用|基于|运行|由|配置|调用|负责|通过|依赖")
R3_CUE = re.compile(r"666|草(?!莓)|何意味|笑死|哈哈哈")
R4_PAT = re.compile(
    r"存到本地|帮你记着|记住这个|下次直接用|跨对话|保存下来|事后补一句|我已经存了|这次记下来"
)
R5_PAT = re.compile(r"<thought>|</thought>|思考：|（内心|（心想")

# ── 场景档 ──────────────────────────────────────────────────────────────
CRISIS_WORDS = [
    "自杀", "自残", "不想活", "活着没意思", "想死", "结束生命", "割腕", "跳楼",
    "安眠药", "遗书", "撑不下去", "没有意义了",
]
EMOTION_WORDS = [
    "难受", "想哭", "好累", "撑不住", "没力气", "委屈", "烦", "空", "堵",
    "不开心", "低落", "崩溃",
]

# ── D3 内容 ─────────────────────────────────────────────────────────────
C1_PAT = re.compile(r"记住了|记下了|以后就|下次就|我改|明白了，以后|懂了，以后|这个记下")
# C2「猜对方动机」。`是在` 是最容易误伤的一个词：
# 「你这是在教我念咒语吗」只是在问对方在做什么，不是替他总结意图。
# 所以 `是在` 后面紧跟具体动作动词时排除；其余四个词保持原样。
_C2_ACT = r"(?:教|做|干|玩|唱|念|写|画|比划|说|发|整)"
C2_PAT = re.compile(
    r"(?:是想|是要|大概想|是不是想).{0,16}(?:吗|吧|么|？)"
    r"|是在(?!" + _C2_ACT + r").{0,16}(?:吗|吧|么|？)"
)
C3_PAT = re.compile(r"这个表情|这张|连发|表情是")
C3_ADJ = re.compile(r"可爱|凶|笑哭")
C4_PAT = re.compile(r"你大概是|说明你|这意味着|你其实是|你内心深处|你之所以")
C5_PAT = re.compile(r"存到本地|记住这个|下次直接用|跨对话|保存下来|我已经存了")

# ── D4 词汇 ─────────────────────────────────────────────────────────────
V1_PAT = re.compile(
    r"值得注意的是|总的来说|综上所述|综上|由此可见|换言之|简而言之|"
    r"需要注意的是|不难看出|总而言之"
)
V2_WORDS = ["首先", "其次", "再次", "最后", "第一", "第二", "其一", "其二", "一方面", "另一方面"]
V3_PAT = re.compile(
    r"我理解你的感受|希望这些建议对你有帮助|希望对你有所帮助|请问还有什么可以帮您|"
    r"还有什么可以帮到您|祝你生活愉快|祝你有美好的一天|很高兴为你服务|"
    r"如果你还有其他问题|请随时联系我"
)
V4_PAT = re.compile(r"不是.{1,20}而是|并非.{1,20}而是")
V5_PAT = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]|(\^_\^|orz|233)")
V6_PAT = re.compile(r"Miruku(觉得|认为|想说|感觉|刚刚|现在|来|去|给)", re.I)
V7_IDIOMS = (
    "心如刀割 无以言表 五味杂陈 百感交集 感同身受 不约而同 莫名其妙 一如既往 "
    "迫不及待 如释重负 豁然开朗 油然而生 难以言喻 深思熟虑 举足轻重 潜移默化 "
    "相辅相成 事半功倍 持之以恒 循序渐进 心领神会 不言而喻 若有所思 若无其事 "
    "轻描淡写 顺其自然 水到渠成 恰到好处 无可厚非 情有可原"
).split()

TIC_WORDS = ["~", "～", "……", "啧", "にゃ"]

STOP_CHARS = set("的了是在我你他她它们这那有不也就都和跟把被给让对从到以及吧吗呢啊哦嗯呀么个一")

CN_RUN = re.compile(r"[\u4e00-\u9fa5]+")


def clean(text: str) -> str:
    """去掉系统注入与占位符，得到可读文本。"""
    text = REMINDER.sub("", str(text or ""))
    text = DATA_URI.sub("[图片]", text)
    text = PLACEHOLDER.sub("", text)
    return text.strip()


def readable_len(text: str) -> int:
    return len(re.sub(r"\s+", "", clean(text)))


def keywords(text: str, min_len: int = 2) -> set:
    """粗粒度实词：中文连续串的不同 2-3 字片段，全为停用字的丢掉。"""
    out = set()
    for run in CN_RUN.findall(clean(text)):
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if all(c in STOP_CHARS for c in g):
                    continue
                out.add(g)
    return out


# ── 场景档判定 ───────────────────────────────────────────────────────────
def scene_of(turns: list, idx: int) -> str:
    """按当前轮及其前 2/3 轮的对方消息判定场景档。"""
    window_crisis = [j for j in range(max(0, idx - 3), idx + 1) if turns[j]["role"] == "user"]
    window_emotion = [j for j in range(max(0, idx - 2), idx + 1) if turns[j]["role"] == "user"]
    for j in window_crisis:
        t = clean(" ".join(turns[j].get("texts") or []))
        if any(w in t for w in CRISIS_WORDS):
            return "crisis"
    for j in window_emotion:
        t = clean(" ".join(turns[j].get("texts") or []))
        if any(w in t for w in EMOTION_WORDS):
            return "emotion"
    return "daily"


# ── 红线 ────────────────────────────────────────────────────────────────
def redlines(text: str, scene: str) -> list:
    hits = []
    if R1_PAT.search(text):
        hits.append("R1")
    if R2_WORD.search(text) and R2_VERB.search(text):
        hits.append("R2")
    if scene == "crisis" and R3_CUE.search(text):
        hits.append("R3")
    if R4_PAT.search(text):
        hits.append("R4")
    if R5_PAT.search(text):
        hits.append("R5")
    return hits


# ── D3 / D4 逐条命中 ────────────────────────────────────────────────────
def hit_d3(text: str, scene: str) -> list:
    out = []
    for code, pat, delta in (
        ("C1", C1_PAT, -7),
        ("C2", C2_PAT, -7),
        ("C4", C4_PAT, -7),
        ("C5", C5_PAT, -12),
    ):
        m = pat.search(text)
        if m:
            out.append((code, m.group(0)[:12], delta))
    m = C3_PAT.search(text)
    if m or (C3_ADJ.search(text) and "[图片]" in text):
        seg = (m.group(0) if m else C3_ADJ.search(text).group(0))[:12]
        out.append(("C3", seg, -7))
    return out


def hit_d4(text: str) -> list:
    out = []
    m = V1_PAT.search(text)
    if m:
        out.append(("V1", m.group(0)[:12], -4))
    seq = [w for w in V2_WORDS if w in text]
    if len(seq) >= 2:
        out.append(("V2", "、".join(seq[:2]), -6))
    m = V3_PAT.search(text)
    if m:
        out.append(("V3", m.group(0)[:12], -8))
    m = V4_PAT.search(text)
    if m:
        out.append(("V4", m.group(0)[:12], -4))
    m = V5_PAT.search(text)
    if m:
        out.append(("V5", m.group(0)[:8], -4))
    m = V6_PAT.search(text)
    if m:
        out.append(("V6", m.group(0)[:12], -5))
    idioms = [w for w in V7_IDIOMS if w in text]
    if len(idioms) >= 2:
        out.append(("V7", "、".join(idioms[:2]), -3))
    return out


# ── D5 关系感（加分制）──────────────────────────────────────────────────
GENERIC_ME = re.compile(r"我觉得|我感觉|我知道|我想说|我说|我是说|我以为")


def score_d5(turn: dict, ctx_turns: list) -> tuple:
    segs = [s for s in turn["texts"] if s.strip()]
    if not segs:
        return D5_BASE, []
    joined = "\n".join(segs)
    notes, score = [], D5_BASE

    peer_prev = ""
    for t in reversed(ctx_turns):
        if t["role"] == "user":
            peer_prev = " ".join(t.get("texts") or [])
            break
    if peer_prev:
        kw = keywords(peer_prev)
        if any(g in joined for g in kw):
            score += 3
            notes.append("G1")

    m = re.search(r"我(?:也|还|就|不太|很|挺|刚|不|没|最|超)?[\u4e00-\u9fa5]{1,6}", joined)
    if m and not GENERIC_ME.search(joined) and len(m.group(0)) >= 3:
        score += 3
        notes.append("G2")

    prior = "\n".join(" ".join(t.get("texts") or []) for t in ctx_turns[-20:])
    if prior:
        kw = keywords(prior)
        if sum(1 for g in kw if g in joined) >= 2:
            score += 2
            notes.append("G3")

    if 2 <= len(segs) <= 3 and len(set(len(s) for s in segs)) > 1:
        score += 2
        notes.append("G4")

    return min(10, score), notes


# ── 单条评分 ────────────────────────────────────────────────────────────
SINGLE_D1 = [(10, 20), (15, 14), (25, 10), (40, 5)]


def single_d1(length: int) -> int:
    for limit, pts in SINGLE_D1:
        if length <= limit:
            return pts
    return 0


RESPONSE_WORDS = set("好 嗯 行 可以 在 盯 哦 啊 对 是 呀 嘿 哈".split())


# ── 线性归一辅助 ────────────────────────────────────────────────────────
def _span(value: float, zero: float, floor: float) -> float:
    """把指标偏离目标的程度换算成 0~1 的扣分比例。

    zero  = 目标值（偏离量为 0，不扣分）
    floor = 崩点（偏离到这个程度，该项扣满）
    偏离量超过崩点时仍钳在 1.0，避免单项吃掉整维分数。
    """
    if floor <= zero:
        return 0.0
    return max(0.0, min(1.0, (value - zero) / (floor - zero)))


def score_single(raw_text: str, scene: str = "daily") -> dict:
    text = clean(raw_text)
    # 红线必须在**未清洗**的原文上判：clean() 会先剥掉 <system_reminder>，
    # 而 R1 要抓的正是这个标记本身。用 text 判等于 R1 永远抓不到。
    hits = redlines(str(raw_text or ""), scene)
    if hits:
        return {
            "mode": "single", "version": VERSION, "scene": scene,
            "grade": "R", "score": 0, "redlines": hits,
            "dims": {k: 0 for k in W}, "deductions": [], "notes": [],
        }

    n = readable_len(text)
    d1 = W["D1"] if scene in ("emotion", "crisis") else single_d1(n)

    d2 = W["D2"]
    if "。" in text and scene != "crisis":
        d2 -= 2
    tic = sum(text.count(w) for w in TIC_WORDS)
    d2 -= 5 * tic
    if "\n\n" in raw_text:
        d2 -= 5
    d2 = max(0, d2)

    d3, d4 = W["D3"], W["D4"]
    hits3, hits4 = hit_d3(text, scene), hit_d4(text)
    for _, _, d in hits3:
        d3 += d
    for _, _, d in hits4:
        d4 += d

    # 单条 D5：纯应答词固定基准，极短给基准 -2，G1/G3 不可判
    if text in RESPONSE_WORDS:
        d5, notes = D5_BASE, ["纯应答词"]
    elif n < 2:
        d5, notes = D5_BASE - 2, ["过短"]
    else:
        d5, notes = D5_BASE, []

    dims = {"D1": max(0, d1), "D2": d2, "D3": max(0, d3), "D4": max(0, d4), "D5": d5}
    score = max(0, sum(dims.values()))
    return {
        "mode": "single", "version": VERSION, "scene": scene,
        "grade": grade_of(score), "score": score, "redlines": [],
        "dims": dims,
        "deductions": [{"code": c, "hit": h, "delta": d} for c, h, d in hits3 + hits4],
        "notes": notes,
    }


def grade_of(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


# ── 批次评分 ────────────────────────────────────────────────────────────
def collect(sessions: list, recent: int | None = None) -> list:
    """把会话拆成「回合」：每个 assistant turn 记一条，带上它的上下文。"""
    rows = []
    for s in sessions:
        turns = s.get("turns") or []
        for i, t in enumerate(turns):
            if t.get("role") != "assistant":
                continue
            segs = [x for x in (t.get("texts") or []) if x and x.strip()]
            if not segs:
                continue
            # 一个回复回合被发送层拆成多条消息后，只有第一段前一条是提示词，
            # 后续段落会被误判成普通回复。所以显式的 _pro 标记优先。
            if "_pro" in t:
                proactive = bool(t["_pro"])
            else:
                proactive = bool(i > 0 and turns[i - 1].get("proactive_prompt"))
            rows.append({
                "turn": {"role": "assistant", "texts": segs},
                "ctx": turns[max(0, i - 20):i],
                "scene": scene_of(turns, i),
                "proactive": proactive,
            })
    if recent:
        rows = rows[-recent:]
    return rows


def score_batch(rows: list) -> dict:
    """批次评分入口：样本不足时不出分，否则交给 score_batch_raw。"""
    if len(rows) < MIN_SAMPLE:
        return {"mode": "batch", "version": VERSION,
                "status": "INSUFFICIENT_SAMPLE", "sample": len(rows)}
    return score_batch_raw(rows)


def score_batch_raw(rows: list) -> dict:
    """批次评分本体（不做样本量门槛，供自检与小样本诊断直接调用）。

    v1.2 起在这里接上第 0 层红线。此前 `redlines()` 只在 `score_single()`
    里被调用，批次模式从不检查 R1–R5，等于细则里的 5 条红线在主要使用
    场景下是死代码。
    """
    n = len(rows)
    if n == 0:
        return {"mode": "batch", "version": VERSION, "status": "INSUFFICIENT_SAMPLE", "sample": 0}

    # ── 第 0 层：红线（逐条扫，统计每条红线的命中次数）
    # 注意用未清洗的原文：R1 要抓的 <system_reminder> 会被 clean() 剥掉。
    redline_hits = []          # [{"code": "R1", "hit": 片段}]
    redline_tally = {}
    for r in rows:
        for seg in r["turn"]["texts"]:
            raw = str(seg or "")
            for code in redlines(raw, r["scene"]):
                redline_hits.append({"code": code, "hit": clean(raw)[:40] or raw[:40]})
                redline_tally[code] = redline_tally.get(code, 0) + 1
    daily = [r for r in rows if r["scene"] == "daily"]
    lengths = sorted(readable_len(x) for r in daily for x in r["turn"]["texts"])
    segs = [x for r in rows for x in r["turn"]["texts"]]
    detail = []      # 逐条命中明细（D3/D4 每次一行）
    reasons = []     # 各维扣分理由（原始值，未截断）

    # ── D1 体量：四项线性归一（v1.1 起，取代逐档扣分）
    d1_why = []
    med = statistics.median(lengths) if lengths else 0
    ratio10 = 100 * sum(1 for x in lengths if x <= 10) / len(lengths) if lengths else 0
    p90 = lengths[min(len(lengths) - 1, int(len(lengths) * 0.9))] if lengths else 0
    over40 = 100 * sum(1 for x in lengths if x > 40) / len(lengths) if lengths else 0
    d1_parts = [
        ("中位 %.0f 字" % med, 8, _span(med, 6, 20)),
        ("≤10 字占比 %.0f%%" % ratio10, 6, _span(85 - ratio10, 0, 65)),
        ("p90 %d 字" % p90, 4, _span(p90, 12, 35)),
        ("超长条 %.1f%%" % over40, 2, _span(over40, 5, 25)),
    ]
    d1_raw = W["D1"] - sum(share * frac for _label, share, frac in d1_parts)
    for label, share, frac in d1_parts:
        if frac > 0:
            d1_why.append("%s 偏离目标，扣 %.1f 分（该项满额 %d）" % (label, share * frac, share))

    # ── D2 形式：三项线性归一
    d2_why = []
    period = 100 * sum(1 for x in segs if "。" in x) / len(segs)
    tic_n = sum(x.count(w) for x in segs for w in TIC_WORDS)
    multi = 100 * sum(1 for r in rows if len(r["turn"]["texts"]) >= 4) / n
    d2_parts = [
        ("句号率 %.1f%%" % period, 8, _span(period, 1, 15)),
        ("口癖 %d 次" % tic_n, 4, _span(tic_n, 0, 10)),
        ("连发 ≥4 条占 %.0f%%" % multi, 3, _span(multi, 10, 40)),
    ]
    d2_raw = W["D2"] - sum(share * frac for _label, share, frac in d2_parts)
    for label, share, frac in d2_parts:
        if frac > 0:
            d2_why.append("%s 偏离目标，扣 %.1f 分（该项满额 %d）" % (label, share * frac, share))

    # ── D3 内容
    # v1.2 起改为「命中率饱和曲线」。原先是 d3_scale = 100/n 的线性折算，
    # 同一条命中在 87 条里扣 8.0 分、552 条里只扣 1.3 分 —— 分数随样本量
    # 漂移，换个窗口就换一个结论，这才是真正的问题（不是系数大小）。
    # 现在只看「每 100 条扣多少分」这个比率，再用饱和曲线映射到 0~35：
    # 比率到 D3_SATURATION 就扣满，超过也不再多扣，剩下的交给绝对次数读数。
    d3_hits = []
    for r in rows:
        for seg in r["turn"]["texts"]:
            for code, hit, delta in hit_d3(seg, r["scene"]):
                d3_hits.append({"code": code, "hit": hit, "delta": delta})
    detail.extend(d3_hits)
    d3_points = -sum(d["delta"] for d in d3_hits)
    d3_per100 = d3_points * 100.0 / n
    d3_frac = min(1.0, d3_per100 / D3_SATURATION)
    d3_raw = W["D3"] * (1.0 - d3_frac)
    q_end = 100 * sum(
        1 for r in rows
        if clean(r["turn"]["texts"][-1]).endswith(("？", "?"))
    ) / n
    d3_why = []
    if d3_hits:
        d3_why.append(
            "D3 命中 %d 次（每百条 %.1f 分，饱和点 %d → 扣 %.1f 分）"
            % (len(d3_hits), d3_per100, D3_SATURATION, W["D3"] * d3_frac))
    if q_end > 20:
        c = 4 * max(1, int((q_end - 20) // 5))
        d3_raw -= c
        d3_why.append("问句收尾 %.0f%%（阈值 20%%）−%d" % (q_end, c))

    # ── D4 词汇（同样用饱和度映射，与 D3 一致）
    d4_hits = []
    for r in rows:
        for seg in r["turn"]["texts"]:
            for code, hit, delta in hit_d4(seg):
                d4_hits.append({"code": code, "hit": hit, "delta": delta})
    detail.extend(d4_hits)
    d4_points = -sum(d["delta"] for d in d4_hits)
    d4_per100 = d4_points * 100.0 / n
    d4_raw = W["D4"] * (1.0 - min(1.0, d4_per100 / D4_SATURATION))

    # ── D5 关系感（加分制，取均值）
    d5_each = [score_d5(r["turn"], r["ctx"])[0] for r in rows]
    d5 = round(sum(d5_each) / len(d5_each))

    raw_dims = {"D1": round(d1_raw, 1), "D2": round(d2_raw, 1),
                "D3": d3_raw, "D4": d4_raw, "D5": d5}
    dims = {k: max(0, min(W[k], v)) for k, v in raw_dims.items()}
    score = round(max(0, sum(dims.values())))

    # 各维「扣分力度」= 满分 - 实际得分；同时保留原始值以便看出是否扣穿
    overflow = {k: (W[k] - raw_dims[k]) for k in ("D1", "D2", "D3", "D4") if raw_dims[k] < 0}

    reasons.extend(d1_why + d2_why + d3_why)
    if redline_hits:
        reasons.insert(0, "红线命中 %d 次（%s）——红线是逐条判定，此处只统计频次，"
                          "不折算成分数；单条命中即整条作废，见 --single"
                       % (len(redline_hits),
                          "、".join("%s×%d" % (k, v) for k, v in sorted(redline_tally.items()))))
    tally = {}
    for d in detail:
        tally[d["code"]] = tally.get(d["code"], 0) + 1

    return {
        "mode": "batch", "version": VERSION, "status": "OK",
        "sample": n,
        "scenes": {k: sum(1 for r in rows if r["scene"] == k) for k in ("daily", "emotion", "crisis")},
        "proactive": sum(1 for r in rows if r["proactive"]),
        "grade": grade_of(score), "score": score,
        "dims": dims,
        "raw_dims": raw_dims,
        "overflow": overflow,
        "redlines": redline_tally,
        "redline_samples": redline_hits[:10],
        "d3_absolute": {"hits": len(d3_hits), "points_per_100": round(d3_per100, 1)},
        "d4_absolute": {"hits": len(d4_hits), "points_per_100": round(d4_per100, 1)},
        "stats": {
            "median_len": statistics.median(lengths) if lengths else 0,
            "p90_len": lengths[min(len(lengths) - 1, int(len(lengths) * 0.9))] if lengths else 0,
            "period_rate": round(period, 1),
            "question_end": round(q_end, 1),
        },
        "reasons": reasons,
        "hit_tally": tally,
        "deductions": detail[:30],
    }


# ── 自检 ────────────────────────────────────────────────────────────────
SELFTEST = [
    ("好", "daily", "A", []),
    ("在呢，来世是在试 Miruku 有没有反应吗", "daily", "B", ["C2"]),
    ("好，记住了，以后先问称呼", "daily", "B", ["C1"]),
    ("好，记住了，以后先问称呼。你其实是怕我忘了。", "daily", "C", ["C1", "C4"]),
    ("总的来说，希望你好好休息", "daily", "B", ["V1"]),
    ("我在这。", "crisis", "A", []),
    ("666 何意味", "crisis", "R", []),
    # v1.2 新增：C2 的负向用例。「是在教/做/玩…」是问对方在干什么，不是猜动机。
    ("你这是在教我念咒语吗", "daily", "A", []),
]


def selftest() -> int:
    bad = 0
    for text, scene, want_grade, want_codes in SELFTEST:
        r = score_single(text, scene)
        codes = [d["code"] for d in r["deductions"]] + r["redlines"]
        ok = r["grade"] == want_grade and all(c in codes for c in want_codes)
        # 反向断言：want_codes 没列出的 C1~C3 不得命中，防止误报
        extra = [c for c in codes if c.startswith("C") and c not in want_codes]
        if extra:
            ok = False
        if not ok:
            bad += 1
        print("%s  %-22s scene=%-7s -> %s(%d) %s%s" % (
            "OK  " if ok else "FAIL", text[:22], scene, r["grade"], r["score"], codes,
            "   多余命中: %s" % extra if extra else ""))
    # 红线层：批量模式必须也能命中红线（v1.2 修复，此前是死代码）
    leaky = collect([{"conversation_id": "t", "user_id": "t", "turns": [
        {"role": "user", "ts": "2026-11-11 10:00", "texts": ["在吗"]},
        {"role": "assistant", "ts": "2026-11-11 10:00",
         "texts": ["<system_reminder>x</system_reminder>在的"]},
    ]}])
    rb = score_batch_raw(leaky)
    r_ok = rb.get("redlines", {}).get("R1", 0) == 1
    if not r_ok:
        bad += 1
    print("%s  批量红线 R1 命中 -> %s" % ("OK  " if r_ok else "FAIL",
                                      rb.get("redlines")))
    total = len(SELFTEST) + 1
    print("\n%d/%d passed" % (total - bad, total))
    return 1 if bad else 0


GOLDEN_PATH = os.path.join(HERE_DIR, "tone_golden.json")
GRADE_ORDER = "RDCBA"


def golden(path: str = GOLDEN_PATH) -> int:
    """跑基准用例。规范 §9：通过率 <95% 不得上线。

    断言规则（见 docs/tone-rubric-spec.md §8）：
      must_hit     必须命中的编号
      must_not_hit 不得命中的编号
      expected_grade 允许 ±1 级（R 不参与浮动，红线是硬判定）
    """
    if not os.path.exists(path):
        print("找不到基准用例：%s" % path)
        return 2
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    cases = doc.get("cases") or []
    bad = []
    for c in cases:
        text = "".join(c.get("bot") or [])
        scene = c.get("scene", "daily")
        r = score_single(text, scene)
        codes = [d["code"] for d in r["deductions"]] + r["redlines"]
        got, want = r["grade"], c.get("expected_grade")
        errs = []
        for code in (c.get("must_hit") or []):
            if code not in codes:
                errs.append("缺 %s" % code)
        for code in (c.get("must_not_hit") or []):
            if code in codes:
                errs.append("多 %s" % code)
        if want == "R":
            if got != "R":
                errs.append("应为 R，实为 %s" % got)
        elif got == "R":
            errs.append("误判红线")
        elif abs(GRADE_ORDER.index(got) - GRADE_ORDER.index(want)) > 1:
            errs.append("等级 %s 偏离 %s 超过一级" % (got, want))
        mark = "OK  " if not errs else "FAIL"
        if errs:
            bad.append((c["id"], errs))
        print("%s %-6s %-7s %s(%3d) %-16s %s" % (
            mark, c["id"], scene, got, r["score"],
            "/".join(codes) or "-", "; ".join(errs)))
    total = len(cases)
    passed = total - len(bad)
    rate = 100.0 * passed / total if total else 0.0
    print("\n基准用例 %d/%d 通过（%.1f%%），门槛 95%%" % (passed, total, rate))
    if rate < 95.0:
        print("未达门槛，按规范 §9 不得上线。")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", help="导出的轮次 JSON")
    ap.add_argument("--recent", type=int, help="只取最近 N 个回合")
    ap.add_argument("--limit", type=int, help="同 --recent（兼容写法）")
    ap.add_argument("--single", help="单条评分")
    ap.add_argument("--scene", default="daily", choices=["daily", "emotion", "crisis"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--golden", nargs="?", const=GOLDEN_PATH, default=None,
                    help="跑基准用例（默认 data/tone_golden.json），通过率 <95%% 返回 1")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    if a.golden:
        return golden(a.golden)
    if a.single:
        r = score_single(a.single, a.scene)
    elif a.turns:
        sessions = json.load(open(a.turns, encoding="utf-8"))
        if isinstance(sessions, dict):
            sessions = sessions.get("sessions") or []
        rows = collect(sessions, a.recent or a.limit)
        r = score_batch(rows)
    else:
        ap.print_help()
        return 2

    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_report(r)
    return 0


def print_report(r: dict) -> None:
    if r.get("status") == "INSUFFICIENT_SAMPLE":
        print("样本不足（%d < %d），不输出分数。" % (r["sample"], MIN_SAMPLE))
        return
    print("Miruku 语言评分 v%s · %s 模式" % (r["version"], r["mode"]))
    if r["mode"] == "single":
        # 单条模式没有 sample / scenes / proactive，只有一条文本的判定结果
        print("场景档 %s" % r.get("scene", "-"))
        print("")
        print("总分 %d  grade=%s" % (r["score"], r["grade"]))
        for k in ("D1", "D2", "D3", "D4", "D5"):
            v = r["dims"][k]
            bar = "█" * int(max(0, v) / W[k] * 20)
            print("  %s %2d/%-2d %s" % (k, v, W[k], bar))
        if r.get("redlines"):
            print("")
            print("  ⚠ 命中红线：" + "  ".join(r["redlines"]) + "（整条作废）")
        if r.get("deductions"):
            print("")
            print("  命中项：")
            for d in r["deductions"]:
                print("    %-6s %-30s %+d" % (d["code"], d["hit"], d["delta"]))
        if r.get("notes"):
            print("  备注：" + "、".join(r["notes"]))
        return
    print("样本 %d 回合（场景 %s）" % (r["sample"], r.get("scenes", "")))
    if r.get("proactive") is not None:
        print("其中主动消息 %d 条" % r["proactive"])
    print("")
    print("总分 %d  grade=%s" % (r["score"], r["grade"]))
    raw = r.get("raw_dims") or {}
    for k in ("D1", "D2", "D3", "D4", "D5"):
        v = r["dims"][k]
        bar = "█" * int(max(0, v) / W[k] * 20)
        extra = ""
        if r.get("overflow") and k in r["overflow"]:
            extra = "   ← 扣穿 %d 分" % r["overflow"][k]
        print("  %s %2d/%-2d %s%s" % (k, v, W[k], bar, extra))
    if r.get("stats"):
        s = r["stats"]
        print("")
        print("  中位长度 %.0f 字 / p90 %d 字 / 句号率 %.1f%% / 问句收尾 %.1f%%"
              % (s["median_len"], s["p90_len"], s["period_rate"], s["question_end"]))
    if r.get("reasons"):
        print("")
        print("  分布类扣分：")
        for x in r["reasons"]:
            print("    · " + x)
    if r.get("hit_tally"):
        print("")
        print("  逐条命中：" + "  ".join("%s×%d" % (k, v) for k, v in sorted(r["hit_tally"].items())))
    if r.get("d3_absolute") and r["d3_absolute"].get("hits"):
        d3a = r["d3_absolute"]
        print("  D3 绝对命中：%d 次（每百条 %.1f 分，饱和点 %d）"
              % (d3a["hits"], d3a["points_per_100"], int(D3_SATURATION)))
    if r.get("redlines"):
        print("")
        print("  ⚠ 红线命中：" + "  ".join("%s×%d" % (k, v) for k, v in sorted(r["redlines"].items())))
        for d in (r.get("redline_samples") or [])[:5]:
            print("    %-4s %s" % (d["code"], d["hit"]))
    if r.get("deductions"):
        print("")
        print("  命中样例：")
        for d in r["deductions"][:10]:
            print("    %-6s %-30s %+d" % (d["code"], d["hit"], d["delta"]))


if __name__ == "__main__":
    raise SystemExit(main())
