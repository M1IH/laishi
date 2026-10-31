"""时间工具函数模块。"""

from __future__ import annotations

import zoneinfo
from datetime import datetime

# 中文星期名称，索引与 datetime.weekday() 对齐（0=周一）
_WEEKDAY_NAMES_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 一天的分钟数；结束端写 24 时用它表示“当天最后一分钟之后”
_DAY_MINUTES = 1440


def _parse_hhmm(value: str) -> int:
    """把 "8" / "08" / "8:30" / "24" 解析成当日分钟数（0..1440）。"""
    text = str(value).strip()
    if not text:
        raise ValueError("empty time")
    if ":" in text:
        hour_text, minute_text = text.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    else:
        hour, minute = int(text), 0
    if hour == 24:
        if minute != 0:
            raise ValueError(f"invalid time: {value!r}")
        return _DAY_MINUTES
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"invalid time: {value!r}")
    return hour * 60 + minute


def parse_quiet_spans(quiet_hours_str: str) -> list[tuple[int, int]]:
    """把免打扰配置解析成若干 (开始分钟, 结束分钟) 区间。

    兼容旧的单段整点写法（"1-7"、"23-6"），也支持多段与半小时粒度，
    段之间用逗号分隔，端点写成 "H" 或 "H:MM"，结束端允许写 24 表示当天末尾：

        0-8:30,12-13:30,18-24

    单段非法时跳过该段，不影响其余段。
    """
    spans: list[tuple[int, int]] = []
    for chunk in str(quiet_hours_str or "").split(","):
        chunk = chunk.strip()
        if not chunk or "-" not in chunk:
            continue
        start_text, end_text = chunk.split("-", 1)
        try:
            start = _parse_hhmm(start_text)
            end = _parse_hhmm(end_text)
        except (ValueError, TypeError):
            continue
        if start == end:
            continue
        if start >= _DAY_MINUTES or end > _DAY_MINUTES:
            continue
        spans.append((start, end))
    return spans


def _in_spans(minute_of_day: int, spans: list[tuple[int, int]]) -> bool:
    """判断某分钟的偏移是否落在任一免打扰区间内。"""
    minute_of_day %= _DAY_MINUTES
    for start, end in spans:
        if start <= end:
            # 同日区间，例如 1-7
            if start <= minute_of_day < end:
                return True
        else:
            # 跨天区间，例如 23-6
            if minute_of_day >= start or minute_of_day < end:
                return True
    return False


def is_quiet_minute(minute_of_day: int, quiet_hours_str: str) -> bool:
    """判断 day 内某分钟是否处于免打扰时段（与 is_quiet_time 同一套规则）。"""
    spans = parse_quiet_spans(quiet_hours_str)
    if not spans:
        return False
    return _in_spans(minute_of_day, spans)


def is_quiet_time(quiet_hours_str: str, tz: zoneinfo.ZoneInfo | None) -> bool:
    """检查当前时间是否处于免打扰时段。

    支持多段与半小时粒度，例如 "0-8:30,12-13:30,18-24"。
    配置整体非法时按“非免打扰”处理，避免误阻断主动消息。
    """
    try:
        now = datetime.now(tz) if tz else datetime.now()
    except (ValueError, TypeError):
        return False
    return is_quiet_minute(now.hour * 60 + now.minute, quiet_hours_str)


def next_active_offset(
    quiet_hours_str: str,
    now_minute: int,
    max_lookahead: int = _DAY_MINUTES,
) -> int | None:
    """返回从 now_minute 起，多少分钟后进入下一个可发送时刻。

    按分钟粒度向前找，最多看 max_lookahead 分钟（默认一整天）。
    没有任何可发送时刻（例如全天免打扰）时返回 None。
    """
    spans = parse_quiet_spans(quiet_hours_str)
    if not spans:
        return 0
    for offset in range(0, max_lookahead + 1):
        if not _in_spans(now_minute + offset, spans):
            return offset
    return None


def format_current_time(tz: zoneinfo.ZoneInfo | None = None) -> str:
    """返回带中文星期的时间字符串，例如 2026年05月12日 周二 09:53。

    星期信息直接由 datetime 计算得出，避免模型自行由日期反推星期几而算错。
    """
    now = datetime.now(tz) if tz else datetime.now()
    weekday = _WEEKDAY_NAMES_ZH[now.weekday()]
    return f"{now.strftime('%Y年%m月%d日')} {weekday} {now.strftime('%H:%M')}"
