#!/usr/bin/env python3
"""把 miruku_metrics 的 JSONL 汇总成人能看的报告。

用法（服务器上）：
    python3 /opt/miruku/server/metrics-report.py            # 最近 7 天
    python3 /opt/miruku/server/metrics-report.py --days 3
    python3 /opt/miruku/server/metrics-report.py --json     # 机器可读

为什么要有它：JSONL 是每次发言一行的快照，单看没意义；
要的是「和上周比，哪些指标变差/变好」，那得按天聚合再对比。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

METRICS = Path("/AstrBot/data/plugin_data/miruku_metrics/metrics.jsonl")
# 容器内路径；在宿主上跑需要 docker exec，所以另给宿主侧包装脚本
TZ = timezone(timedelta(hours=8))

# 指标含义与人话解释：报告要直接给出判断，不能只丢数字
FIELDS = [
    ("user_turns", "对方说了几句", None),
    ("bot_turns", "她说了几句", None),
    ("turn_ratio", "话轮比（她/对方）", "偏高=她话多；偏低=她冷淡"),
    ("max_bot_streak", "最长自说自话", ">=3 说明连发几句都没人接，是冷场信号"),
    ("proactive_reply_rate", "主动消息被回复率", "越高越好；<0.4 说明主动消息时机或内容不对"),
    ("user_avg_len", "对方平均字数", "突然变短可能是在敷衍"),
    ("bot_avg_len", "她平均字数", "太长像客服，太短像敷衍"),
]


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _day(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(TZ).strftime("%Y-%m-%d")
    except Exception:
        return "unknown"


def summarize(rows: list[dict], days: int) -> dict:
    """按 uid 聚合最近 N 天，给出最近值与区间对比。"""
    cutoff = datetime.now(TZ) - timedelta(days=days)
    kept = [r for r in rows
            if _safe_dt(r.get("at")) and _safe_dt(r["at"]) >= cutoff]
    by_uid: dict[str, list[dict]] = defaultdict(list)
    for r in kept:
        by_uid[str(r.get("uid"))].append(r)

    out = {"window_days": days, "samples": len(kept), "users": {}}
    for uid, rs in by_uid.items():
        rs.sort(key=lambda r: r.get("at") or "")
        latest = rs[-1]
        # 取最近 5 次的中位数，避免单次抖动
        recent = rs[-5:]
        agg = {}
        for key, _label, _hint in FIELDS:
            vals = [r.get(key) for r in recent if isinstance(r.get(key), (int, float))]
            agg[key] = round(sorted(vals)[len(vals) // 2], 2) if vals else None
        # 冷场频次：最近 5 次里有多少次 streak >= 3
        cold = sum(1 for r in recent if (r.get("max_bot_streak") or 0) >= 3)
        out["users"][uid] = {
            "samples": len(rs),
            "latest_at": latest.get("at"),
            "total_turns": latest.get("turns_total"),
            "recent_median": agg,
            "cold_streak_hits": cold,
            "cold_streak_window": len(recent),
        }
    return out


def _safe_dt(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def render(data: dict) -> str:
    lines = []
    lines.append("=" * 62)
    lines.append("Miruku 聊天质量报告（最近 %d 天，%d 个采样）"
                 % (data["window_days"], data["samples"]))
    lines.append("=" * 62)
    if not data["users"]:
        lines.append("")
        lines.append("还没有数据。指标只在收到私聊时采集，等有人说话后再看。")
        return "\n".join(lines)

    for uid, u in data["users"].items():
        lines.append("")
        lines.append("── QQ %s ──" % uid)
        lines.append("  采样 %d 次，最近一次 %s，会话共 %s 轮"
                     % (u["samples"], u["latest_at"], u["total_turns"]))
        lines.append("  最近 5 次中位数：")
        med = u["recent_median"]
        for key, label, hint in FIELDS:
            v = med.get(key)
            if v is None:
                continue
            mark = ""
            if key == "max_bot_streak" and v >= 3:
                mark = "  ← 冷场"
            if key == "proactive_reply_rate" and v < 0.4:
                mark = "  ← 主动消息接不住"
            lines.append("    %-22s %-8s %s%s" % (label, v, hint or "", mark))
        if u["cold_streak_window"]:
            lines.append("  冷场占比：%d/%d 次出现连续 3 句以上无人接"
                         % (u["cold_streak_hits"], u["cold_streak_window"]))
    lines.append("")
    lines.append("提示：这些是观察指标，不是自动调参依据。")
    lines.append("      要改 persona 必须人工确认并走 deploy-persona.py。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--file", default=str(METRICS))
    args = ap.parse_args()

    rows = _load(Path(args.file))
    data = summarize(rows, args.days)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
