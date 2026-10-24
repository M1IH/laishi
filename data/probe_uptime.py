# -*- coding: utf-8 -*-
"""连续运行取证（只读）。v4 —— 按 Codex `docs/wb10-review-20261023.md` v3 复验第 1 条重写。

用途：OTTO 2026-10-23 定「24 小时不间断部署后才正式给来世用」。
本脚本只回答一件事——**这个 24 小时能不能被判为达成，判据缺哪些证据。**

只读 logs/ 下的文本日志，不读运行配置、不改任何文件、不发消息。

━━ 为什么 v3 → v4（一句话）━━
v3 把每一条「适配器已连接」当成"此刻在线"的证据点。可它其实是**重连事件**：
一条 24 小时的段里出现 288 次"已连接"，说明中间断了 287 次，不是"一直在"。
反过来，只出现 1 次也不能证明后面一直在线。**连接事件与持续在线是两回事。**

━━ 两类证据，不许混（这是本文件的全部要点）━━
【LINK】链路事件 —— 时间点确定"连上过"，**不证明之后还在线**，**重复出现即中断**。
        astrbot: aiocqhttp_platform_adapter:107（aiocqhttp(OneBot v11) 适配器已连接。）
        段内出现 ≥2 次 = 断过再连 = 连续性已破 → 判 `BROKEN`（归零）。
【BEAT】持续在线心跳 —— 周期性出现、能证明"此刻仍在线"的行。
        当前 `HEARTBEAT_MARKS = ()`：**一条都没有**。
        观察插件 main.py:86–93 只在有新消息时写库，空转 sleep(10) 不打日志；
        没新消息时既不写库也不打日志 → 进程死 / QQ 掉 / 插件崩 三种故障同形。
        **所以在本文件里 PROVEN 目前结构上不可达，这与日志内容无关。**

NapCat 的「二维码已被扫描 / 登录成功」**不算在线证据**：扫码不是登录成功，
登录成功也不等于适配器可用。它们只作旁证打印，不参与判定。
NapCat 的掉线事件（离线 / KickedOffLine / 登录已失效）**参与判定，一票否决**。

━━ 判定（顺序即优先级，改判据等于改结论）━━
1. 段长 < 24h                         → NOT_REACHED
2. 段内从未出现 LINK                  → NOT_REACHED（进程在跑，什么都没接到）
3. 段内 LINK ≥2 次（重连）            → BROKEN（重连＝此前已断，24h 归零）
4. 段内有掉线事件                     → BROKEN
5. 无心跳 / 最长心跳空档 > 10min       → UNPROVEN  ← 当前上限
6. 以上全过                           → PROVEN（需要先有心跳）

━━ 输出四档 ━━
  NOT_REACHED  未达成（时长不够 / 从未连上）
  BROKEN       段内断过（重连 ≥2 次，或掉线事件）—— 必须归零重算
  UNPROVEN     日志可证明连续 ≥24h 且连上过，但"一直在线"没有被证明  ← 当前上限
  PROVEN       全部满足（需先有心跳；当前结构不可达）
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"

START_MARK = "core.main:144"                     # 进程启动 banner
LINK_MARK = "aiocqhttp_platform_adapter:107"     # 适配器已连接 = 链路事件（不是心跳）

# ── 持续在线心跳标记。当前为空：本项目还没有任何周期性"活着"日志。 ──
# 接心跳后把那一行的稳定片段填进来（例如 "miruku_heartbeat"），
# 并让心跳每 ≤10 分钟落一行「进程在 + 适配器在线」。空着就是空着，不许拿别的行顶替。
HEARTBEAT_MARKS: tuple[str, ...] = ()

TS_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]")
FILE_RE = re.compile(r"astrbot-(\d{8})\.log$")
NAPCAT_FILE_RE = re.compile(r"napcat-console-(\d{8})\.log$")
NAPCAT_TS_RE = re.compile(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})")
# 日志里有 ANSI 颜色码（\x1b[32m 等），不剥掉则行首正则永不匹配
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# 只作旁证，不进判定：扫码 ≠ 登录成功 ≠ 适配器可用
NAPCAT_HINT = ("账号状态变更为在线", "登录成功", "二维码已被扫描")
NAPCAT_OFFLINE = ("账号状态变更为离线", "KickedOffLine", "登录已失效")

TARGET = timedelta(hours=24)
MAX_BEAT_GAP = timedelta(minutes=10)   # 相邻心跳的最大容许空档


def parse_astrbot_ts(line: str, day: datetime) -> datetime | None:
    m = TS_RE.match(line)
    if not m:
        return None
    h, mi, s, ms = (int(x) for x in m.groups())
    return day.replace(hour=h, minute=mi, second=s, microsecond=ms * 1000)


def parse_napcat_ts(line: str, year: int) -> datetime | None:
    m = NAPCAT_TS_RE.match(line)
    if not m:
        return None
    mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime(year, mo, d, h, mi, s)
    except ValueError:
        return None


def load_stream(sources: list[tuple[str, str]] | None = None) -> list[tuple[datetime, str]]:
    """把全部 astrbot 日志合并成一条按时间排序的流。

    sources: [(文件名, 全文)]，供自测注入；None = 读 logs/。
    无时间戳的续行（ASCII banner 等）沿用上一行时间。
    """
    if sources is None:
        sources = [
            (p.name, p.read_text(encoding="utf-8", errors="replace"))
            for p in sorted(LOGS.glob("astrbot-*.log"))
        ]
    rows: list[tuple[datetime, str]] = []
    for name, text in sources:
        m = FILE_RE.search(name)
        if not m:
            continue
        day = datetime.strptime(m.group(1), "%Y%m%d")
        # 不论来源（读盘还是自测注入）都先剥 ANSI，否则行首正则永不匹配
        for line in ANSI_RE.sub("", text).splitlines():
            ts = parse_astrbot_ts(line, day)
            if ts is None:
                if rows:
                    rows.append((rows[-1][0], line))
                continue
            rows.append((ts, line))
    rows.sort(key=lambda r: r[0])
    return rows


def load_napcat_events(sources: list[tuple[str, str]] | None = None) -> tuple[list[datetime], list[datetime]]:
    """返回 (旁证提示点, 掉线事件点)。旁证不进判定，只为打印。"""
    if sources is None:
        sources = [
            (p.name, p.read_text(encoding="utf-8", errors="replace"))
            for p in sorted(LOGS.glob("napcat-console-*.log"))
        ]
    hints: list[datetime] = []
    offline: list[datetime] = []
    for name, text in sources:
        m = NAPCAT_FILE_RE.search(name)
        if not m:
            continue
        year = int(m.group(1)[:4])
        for line in text.splitlines():
            ts = parse_napcat_ts(line, year)
            if ts is None:
                continue
            if any(k in line for k in NAPCAT_OFFLINE):
                offline.append(ts)
            elif any(k in line for k in NAPCAT_HINT):
                hints.append(ts)
    return sorted(hints), sorted(offline)


def segment(rows: list[tuple[datetime, str]],
            heartbeat_marks: tuple[str, ...] = HEARTBEAT_MARKS) -> list[dict]:
    """按 core.main:144 切段，并把**链路事件**与**心跳**分开记。

    跨文件天然连续——因为流已合并，没有新 banner 就是同一段。
    """
    segs: list[dict] = []
    cur: dict | None = None
    for ts, line in rows:
        if START_MARK in line:
            if cur is not None:
                segs.append(cur)
            cur = {"start": ts, "end": ts, "links": [], "beats": []}
            continue
        if cur is None:
            continue
        cur["end"] = ts
        if LINK_MARK in line:
            cur["links"].append(ts)          # 事件：连上过，不代表之后还在
        if any(mark in line for mark in heartbeat_marks):
            cur["beats"].append(ts)          # 心跳：此刻仍在
    if cur is not None:
        segs.append(cur)
    return segs


def annotate(segs: list[dict], nap_offline: list[datetime]) -> None:
    """给每段补：掉线事件、最长无心跳间隔、时长。"""
    for s in segs:
        start, end = s["start"], s["end"]
        s["offline"] = [p for p in nap_offline if start <= p <= end]
        # 最长无心跳间隔：段首→首拍→…→末拍→段尾。没有心跳时就是整段长度。
        edges = [start] + s["beats"] + [end]
        gap = timedelta(0)
        for a, b in zip(edges, edges[1:]):
            if b - a > gap:
                gap = b - a
        s["max_gap"] = gap
        s["duration"] = end - start


def verdict(s: dict) -> tuple[str, str]:
    """返回 (档位, 理由)。顺序即优先级。"""
    if s["duration"] < TARGET:
        return "NOT_REACHED", f"段长 {fmt(s['duration'])} < 24h"
    if not s["links"]:
        return "NOT_REACHED", "段内一次都没连上"
    if len(s["links"]) >= 2:
        return "BROKEN", (
            f"段内出现 {len(s['links'])} 次『适配器已连接』= 重连 {len(s['links']) - 1} 次——"
            f"每次重连都意味着此前已断，24h 必须归零"
        )
    if s["offline"]:
        return "BROKEN", f"段内有 {len(s['offline'])} 次掉线事件"
    if not s["beats"]:
        return "UNPROVEN", "没有周期心跳，无法证明『一直在线』（连接过 ≠ 一直在）"
    if s["max_gap"] > MAX_BEAT_GAP:
        return "UNPROVEN", (
            f"最长 {fmt(s['max_gap'])} 没有心跳"
            f"（容许上限 {fmt(MAX_BEAT_GAP)}）——这期间是否在线**未被证明**"
        )
    return "PROVEN", "段长够 ＋ 只连一次 ＋ 无掉线 ＋ 心跳空档在容许范围内"


def fmt(d: timedelta) -> str:
    total = int(d.total_seconds())
    if total < 0:
        return "-"
    if total >= 86400:
        return f"{total // 86400}d{(total % 86400) // 3600:02d}h"
    return f"{total // 3600}h{(total % 3600) // 60:02d}m"


def main() -> None:
    rows = load_stream()
    if not rows:
        print("NO_DATA：logs/astrbot-*.log 里没有任何启动段")
        return

    nap_hints, nap_offline = load_napcat_events()
    segs = segment(rows)
    annotate(segs, nap_offline)

    print("=" * 92)
    print("连续运行取证 v4（只读）— 判据见脚本头，口径见 docs/pilot-go-no-go.md §A-2")
    print("=" * 92)
    print("说明：下面是**日志观察值**，不是已验证的真实在线时长。没有证据的地方就是没有证据。")
    print("      『适配器已连接』是链路事件，不是心跳：它只证明连上过，不证明之后还在线。")

    print("\n【一】启动段（跨午夜已合并；一次 core.main:144 = 一次启动）")
    print(f"{'启动':<16}{'最后可见':<11}{'时长':>8}{'连接':>5}{'心跳':>5}{'最长空档':>10}   判定")
    print("-" * 92)
    for s in segs:
        v, _ = verdict(s)
        print(f"{s['start']:%m-%d %H:%M:%S} {s['end']:%m-%d %H:%M:%S} "
              f"{fmt(s['duration']):>8}{len(s['links']):>5}{len(s['beats']):>5}"
              f"{fmt(s['max_gap']):>10}   {v}")

    today = datetime.now().date()
    print("\n【二】今日")
    todays = [s for s in segs if s["start"].date() == today]
    print(f"  今日新启动次数 = {len(todays)}"
          f"（跨午夜继续运行的段，次日这里可以是 0，仍然算连续——别拿这一行判连续）")
    running = [s for s in segs if s["end"].date() == today]
    if running:
        cur = max(running, key=lambda s: s["end"])
        print(f"  当前所在启动段起点 = {cur['start']:%m-%d %H:%M:%S}"
              f"（日志已覆盖 {fmt(cur['duration'])}，最后可见活动 {cur['end']:%H:%M:%S}）")
        print(f"  该段链路事件 = {len(cur['links'])} 次，心跳 = {len(cur['beats'])} 拍"
              f"，最长无心跳空档 {fmt(cur['max_gap'])}")
        if not cur["links"]:
            print("  ← 这一段从未连上 QQ：进程在跑，但什么都没接到")

    print("\n【三】24 小时判定")
    best = max(segs, key=lambda s: s["duration"])
    v, why = verdict(best)
    print(f"  历史最长启动段 = {fmt(best['duration'])}"
          f"（{best['start']:%m-%d %H:%M} → {best['end']:%m-%d %H:%M}）")
    print(f"  该段链路事件 = {len(best['links'])} 次（≥2 即重连＝中断）"
          f" | 掉线事件 = {len(best['offline'])} 次"
          f" | 心跳 = {len(best['beats'])} 拍"
          f" | 最长无心跳空档 = {fmt(best['max_gap'])}")
    print(f"  判定 = **{v}** —— {why}")

    if v == "UNPROVEN":
        print("  ⚠ 这一档**不是可放行状态**：它只说『日志里没看到它断』，不等于『它一直在』。")
    elif v == "BROKEN":
        print("  ⚠ 段内断过：这一段作废，24h 从下次启动重新计，不许累计、不许『这次不算』。")
    elif v == "NOT_REACHED":
        print(f"  段长缺口 = {fmt(TARGET - best['duration'])}")

    print("\n【四】证据的诚实边界")
    print(f"  HEARTBEAT_MARKS = {HEARTBEAT_MARKS}")
    if not HEARTBEAT_MARKS:
        print("  ← **没有任何心跳标记**，所以 PROVEN 当前**结构上不可达**——")
        print("     这与日志内容无关：就算某段跑了 30 天且只连过一次，也只能是 UNPROVEN。")
        print("     要升到 PROVEN，必须先让心跳每 ≤10 分钟落一行『活着＋适配器在线』。")
    print(f"  NapCat 旁证点 = {len(nap_hints)} 个（扫码/登录，**不进判定**）；"
          f"掉线事件 = {len(nap_offline)} 个（进判定）")
    if len(nap_offline) == 0:
        print("  ← **没有任何掉线记录**。不等于没掉过线，等于**没有记录**。")
        print("     日志里没有，就不能拿它当证据，也不能拿它当反证。")
    print("  未覆盖的部分一律记为『未知』，不记为『正常』。")

    print("\n【五】复跑")
    print('  "C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe" data/probe_uptime.py')
    print('  "…/python.exe" data/probe_uptime_selftest.py     # 重连/掉线/心跳/跨午夜的固定样例')
    print()


if __name__ == "__main__":
    main()
