# -*- coding: utf-8 -*-
"""`data/probe_uptime.py` 的固定样例自测（隔离单测，不读也不改运行实例）。

写这个文件的原因：两轮复核各指出一处读日志时看不出来的错——
① v2 → v3：跨午夜会把同一进程切成两段；段内只要连过一次就敢输出"已达成"。
② v3 → v4：把每一条「适配器已连接」当在线证据，于是**密集重连**被当成了密集心跳，
   造出一个假的 PROVEN；而"二维码已被扫描"也不是登录成功。
   旧样例 6 本身就是错的证据（每 5 分钟重连一次 → 判 PROVEN）。

做法：用**真实**的 load_stream / segment / annotate / verdict，只把日志文本换成内存里的假串。
不读 logs/、不碰配置、不发消息。

样例 9–12 用手工注入的 `HBT` 心跳标记，是为了证明**判据不是死锁**（有心跳就能到 PROVEN）；
真实运行里 `HEARTBEAT_MARKS = ()`，所以实例上永远是 UNPROVEN 或更低。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_uptime as P  # noqa: E402

PASS = 0
FAIL = 0

HBT = ("HBT",)   # 假想心跳标记，只在本自测里用


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"   <-- {detail}" if detail else ""))


def L(ts: str, tag: str = "core.lifecycle:1", msg: str = "x", color: bool = False) -> str:
    """造一行日志。ts 形如 '22:00:00'。"""
    body = f"[{ts}.000] [Core] [INFO] [{tag}]: {msg}"
    return f"\x1b[32m{body}\x1b[0m" if color else body


ONLINE_MSG = "aiocqhttp(OneBot v11) 适配器已连接。"


def boot(ts: str, color: bool = False) -> str:
    return L(ts, "core.main:144", "", color=color)


def online(ts: str, color: bool = False) -> str:
    return L(ts, "aiocqhttp.aiocqhttp_platform_adapter:107", ONLINE_MSG, color=color)


def beat(ts: str) -> str:
    return L(ts, "miruku_observer.heartbeat:1", "HBT alive, adapter=up")


def noisy(ts: str) -> str:
    return L(ts, "astrbot_plugin_proactive_chat.services.scheduler_service:466", "[主动消息] x")


def mk(day: str, rows: list[str]) -> tuple[str, str]:
    return (f"astrbot-{day}.log", "\n".join(rows))


def run(sources, nap_offline=(), hb=()):
    rows = P.load_stream(sources)
    segs = P.segment(rows, hb)
    P.annotate(segs, list(nap_offline))
    return segs


def main() -> int:
    print("=" * 84)
    print("probe_uptime v4 自测 —— 跨午夜 / 重连 / 掉线 / 心跳（隔离单测，不碰实例）")
    print("=" * 84)

    # ── 样例 1：跨午夜、同一进程，没有新的 core.main:144 ──────────────
    print("\n[1] 跨午夜同一进程：22:00 启动 → 次日 00:05 末行，次日无 banner")
    s1 = run([
        mk("20261022", [boot("22:00:00"), online("22:00:30"), noisy("23:59:30")]),
        mk("20261023", [noisy("00:00:30"), noisy("00:05:00")]),
    ])
    check("只有 1 段（旧版会切成 2 段）", len(s1) == 1, f"实际 {len(s1)} 段")
    if s1:
        dur = s1[0]["duration"]
        check("时长 = 2h05m（跨日连续计算）", dur == timedelta(hours=2, minutes=5),
              f"实际 {P.fmt(dur)}")
        check("段起点仍是 10-22 22:00", s1[0]["start"] == datetime(2026, 10, 22, 22, 0, 0))

    # ── 样例 2：跨午夜之后真的重启了 ────────────────────────────────
    print("\n[2] 跨午夜 + 次日 00:05 有 core.main:144 → 必须切成 2 段")
    s2 = run([
        mk("20261022", [boot("22:00:00"), online("22:00:30")]),
        mk("20261023", [boot("00:05:00"), online("00:05:30")]),
    ])
    check("2 段", len(s2) == 2, f"实际 {len(s2)} 段")
    if len(s2) == 2:
        check("第 1 段在 22:00:30 结束", s2[0]["end"] == datetime(2026, 10, 22, 22, 0, 30))
        check("第 2 段从 00:05:00 开始", s2[1]["start"] == datetime(2026, 10, 23, 0, 5, 0))

    # ── 样例 3：段长满足 24h，但只连过一次 → 不许判达成 ──────────────
    print("\n[3] 段长 24h，但只在开头连过一次，之后 23h59m 无任何心跳")
    s3 = run([
        mk("20261022", [boot("22:00:00"), online("22:01:00")]),
        mk("20261023", [noisy("22:00:00")]),
    ])
    check("1 段", len(s3) == 1)
    if s3:
        v, why = P.verdict(s3[0])
        check("判定 = UNPROVEN（连接过 ≠ 一直在）", v == "UNPROVEN", f"实际 {v}：{why}")
        check("最长无心跳空档 = 整段 24h（没有心跳时，整段都是『未证明』）",
              s3[0]["max_gap"] == timedelta(hours=24),
              f"实际 {P.fmt(s3[0]['max_gap'])}")
        check("无心跳时 PROVEN 不可达", v != "PROVEN")

    # ── 样例 4：24h 段内发生过掉线 ──────────────────────────────────
    print("\n[4] 段长够、只连一次，但段内发生过 1 次掉线")
    s4 = run(
        [mk("20261022", [boot("22:00:00"), online("22:01:00")]),
         mk("20261023", [noisy("22:00:00")])],
        nap_offline=[datetime(2026, 10, 23, 10, 0, 0)],
    )
    check("1 段", len(s4) == 1)
    if s4:
        v, why = P.verdict(s4[0])
        check("判定 = BROKEN（掉线一票否决）", v == "BROKEN", f"实际 {v}：{why}")
        check("掉线事件被记到该段", len(s4[0]["offline"]) == 1)

    # ── 样例 5：23h59m，差一分钟 ────────────────────────────────────
    print("\n[5] 段长 23h59m —— 差一分钟也不算")
    s5 = run([
        mk("20261022", [boot("22:00:00"), online("22:01:00")]),
        mk("20261023", [noisy("21:59:00")]),
    ])
    if s5:
        v, _ = P.verdict(s5[0])
        check("判定 = NOT_REACHED", v == "NOT_REACHED", f"实际 {v}，段长 {P.fmt(s5[0]['duration'])}")

    # ── 样例 6（旧版错在这里）：每 5 分钟"重连"一次，不是心跳 ─────────
    print("\n[6] 每 5 分钟一条『适配器已连接』、满 24h → 那是重连 288 次，必须 BROKEN")
    d1, d2 = [], []
    t = datetime(2026, 10, 22, 22, 0, 0)
    end = datetime(2026, 10, 23, 22, 0, 0)
    while t <= end:
        row = online(t.strftime("%H:%M:%S"))
        (d2 if t.date().day == 23 else d1).append(row)
        t += timedelta(minutes=5)
    s6 = run([mk("20261022", [boot("22:00:00")] + d1), mk("20261023", d2)])
    check("1 段", len(s6) == 1, f"实际 {len(s6)} 段")
    if s6:
        v, why = P.verdict(s6[0])
        check("判定 = BROKEN（旧版误判为 PROVEN）", v == "BROKEN", f"实际 {v}：{why}")
        check("连接次数被完整计数（289 个点，旧版只取首尾）", len(s6[0]["links"]) == 289,
              f"实际 {len(s6[0]['links'])}")
        check("重连不得产生 PROVEN", v != "PROVEN")

    # ── 样例 7：ANSI 颜色码 ─────────────────────────────────────────
    print("\n[7] 日志带 ANSI 颜色码（真实日志就是这样）")
    s7 = run([mk("20261022", [boot("22:00:00", color=True), online("22:00:30", color=True)])])
    check("能解析出 1 段", len(s7) == 1, f"实际 {len(s7)} 段")
    if s7:
        check("链路事件被识别", len(s7[0]["links"]) == 1, f"实际 {len(s7[0]['links'])}")

    # ── 样例 8：新日志文件里没有 banner（只是日志滚动） ──────────────
    print("\n[8] 次日文件里没有任何 core.main:144（仅日志滚动）→ 不许凭空多一段")
    s8 = run([
        mk("20261022", [boot("23:00:00"), online("23:00:30")]),
        mk("20261023", [noisy("00:00:10"), noisy("01:00:00")]),
    ])
    check("1 段", len(s8) == 1, f"实际 {len(s8)} 段")

    # ── 样例 9：注入真心跳 → PROVEN 必须可达（证明判据不是死锁）──────
    print("\n[9] 只连一次 ＋ 每 5 分钟一拍心跳、满 24h → 应能到 PROVEN")
    d1, d2 = [], []
    t = datetime(2026, 10, 22, 22, 0, 0)
    while t <= end:
        row = beat(t.strftime("%H:%M:%S"))
        (d2 if t.date().day == 23 else d1).append(row)
        t += timedelta(minutes=5)
    s9 = run([mk("20261022", [boot("22:00:00"), online("22:00:10")] + d1), mk("20261023", d2)], hb=HBT)
    check("1 段（跨午夜合并）", len(s9) == 1, f"实际 {len(s9)} 段")
    if s9:
        v, why = P.verdict(s9[0])
        check("判定 = PROVEN（判据不是死锁）", v == "PROVEN", f"实际 {v}：{why}")
        check("心跳被识别为心跳（不是连接）", len(s9[0]["beats"]) == 289 and len(s9[0]["links"]) == 1,
              f"beats={len(s9[0]['beats'])} links={len(s9[0]['links'])}")

    # ── 样例 10：有心跳但段内重连过 → 重连优先，仍 BROKEN ────────────
    print("\n[10] 心跳很密，但段内出现过 2 次『已连接』→ 中间断过，24h 归零")
    s10 = run([
        mk("20261022", [boot("22:00:00"), online("22:00:10")] + d1),
        mk("20261023", [online("12:00:00")] + d2),
    ], hb=HBT)
    check("1 段", len(s10) == 1, f"实际 {len(s10)} 段")
    if s10:
        v, why = P.verdict(s10[0])
        check("判定 = BROKEN（心跳盖不住重连）", v == "BROKEN", f"实际 {v}：{why}")

    # ── 样例 11：心跳空档 11 分钟 → 超容许上限 ──────────────────────
    print("\n[11] 心跳中间空了 11 分钟（上限 10 分钟）")
    s11 = run([
        mk("20261022", [boot("22:00:00"), online("22:00:10"),
                        beat("22:10:00"), beat("22:21:00"), beat("22:31:00")]),
        mk("20261023", [beat("22:00:00")]),
    ], hb=HBT)
    check("1 段", len(s11) == 1, f"实际 {len(s11)} 段")
    if s11:
        v, why = P.verdict(s11[0])
        check("判定 = UNPROVEN（空档 11 分钟 > 10）", v == "UNPROVEN", f"实际 {v}：{why}")

    # ── 样例 12：段内一次都没连上 ──────────────────────────────────
    print("\n[12] 段长 24h、有心跳，但一次都没连上 QQ")
    s12 = run([
        mk("20261022", [boot("22:00:00"), beat("22:10:00"), beat("22:20:00")]),
        mk("20261023", [beat("22:00:00")]),
    ], hb=HBT)
    if s12:
        v, why = P.verdict(s12[0])
        check("判定 = NOT_REACHED（从未连上）", v == "NOT_REACHED", f"实际 {v}：{why}")

    # ── 样例 13：真实运行时 HEARTBEAT_MARKS 必须为空 ────────────────
    print("\n[13] 真实配置：HEARTBEAT_MARKS 当前必须为空（否则就是拿别的行假装心跳）")
    check("P.HEARTBEAT_MARKS == ()", P.HEARTBEAT_MARKS == (), f"实际 {P.HEARTBEAT_MARKS}")

    print("\n" + "=" * 84)
    print(f"合计：PASS {PASS} / FAIL {FAIL}")
    print("=" * 84)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
