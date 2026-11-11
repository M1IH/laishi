# -*- coding: utf-8 -*-
"""把主动消息从「随机间隔」改成「固定时段 ± 抖动」，并放开极短问候。

三处改动全部幂等：
1. utils/time_utils.py —— 新增 parse_slot_list / next_slot_trigger / next_day_slot_trigger
2. core/services/scheduler_service.py —— 新增 _slot_target / _next_day_slot_target，
   compute_next_trigger 与 compute_next_day_trigger 优先走时段
3. _conf_schema.json + 线上配置 —— schedule_settings 新增 slots_enable / slots / slot_jitter_minutes

用法：
    python3 patch_slots.py <插件根目录> <配置文件路径> [--dry]
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time
import zoneinfo
from datetime import datetime

TU_REL = os.path.join("utils", "time_utils.py")
SCHED_REL = os.path.join("core", "services", "scheduler_service.py")
SCHEMA_REL = "_conf_schema.json"

# ---------------------------------------------------------------- 新增代码

TU_IMPORT_OLD = "import zoneinfo\nfrom datetime import datetime\n"
TU_IMPORT_NEW = "import random\nimport zoneinfo\nfrom datetime import datetime, timedelta\n"

TU_APPEND = '''

def parse_slot_list(slots_str: str) -> list[int]:
    """把 "9,11,14,17" 解析成当日分钟列表（升序、去重）。

    非法片段直接跳过，不影响其余时段；空配置返回空列表。
    """
    result: list[int] = []
    for chunk in str(slots_str or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = _parse_hhmm(chunk)
        except (ValueError, TypeError):
            continue
        if value >= _DAY_MINUTES:
            continue
        if value not in result:
            result.append(value)
    return sorted(result)


def _window_bounds(slot: int, jitter: int) -> tuple[int, int]:
    """给出某个时段的抖动窗口（当日分钟），自动夹到 0..1440。"""
    start = max(0, slot - jitter)
    end = min(_DAY_MINUTES, slot + jitter)
    return start, end


def next_slot_trigger(
    slots_str: str,
    jitter_minutes: int,
    now_ts: float,
    tz: zoneinfo.ZoneInfo | None,
    quiet_hours_str: str = "",
) -> float | None:
    """按「固定时段 ± 抖动」返回下一次可发送的时间戳。

    每个时段 slot 生成窗口 [slot-jitter, slot+jitter]，在窗口内取一个随机秒；
    已经整段过去的窗口跳过。窗口内随机出来的时刻若落进免打扰区间，
    推到该区间之后（与 compute_next_trigger 的旧行为一致）。

    全部时段都不再可发送时（例如配置为空）返回 None。
    """
    slots = parse_slot_list(slots_str)
    if not slots:
        return None
    try:
        jitter = max(0, int(jitter_minutes or 0))
    except (TypeError, ValueError):
        jitter = 0

    now_dt = datetime.fromtimestamp(now_ts, tz=tz)
    floor = int(now_ts) + 30
    # 三天足够覆盖「今天剩余窗口 + 明天 + 抖动推后」的情况。
    for day_offset in range(0, 3):
        day = (now_dt + timedelta(days=day_offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        for slot in slots:
            start_min, end_min = _window_bounds(slot, jitter)
            win_start = day + timedelta(minutes=start_min)
            win_end = day + timedelta(minutes=end_min)
            # 已经开始的窗口整体跳过。否则「09:20 发完再算下一次」还会落回
            # 09:00 那个窗口里，同一时段发两条。宁可漏一个时段，不重复发。
            if int(win_start.timestamp()) <= int(now_ts):
                continue
            low = max(int(win_start.timestamp()), floor)
            high = int(win_end.timestamp())
            if high < low:
                continue
            candidate = random.randint(low, high)
            if quiet_hours_str:
                minute_of_day = (
                    datetime.fromtimestamp(candidate, tz=tz).hour * 60
                    + datetime.fromtimestamp(candidate, tz=tz).minute
                )
                offset = next_active_offset(quiet_hours_str, minute_of_day)
                if offset is None:
                    continue
                candidate += offset * 60
            return float(candidate)
    return None


def next_day_slot_trigger(
    slots_str: str,
    jitter_minutes: int,
    now_ts: float,
    tz: zoneinfo.ZoneInfo | None,
    quiet_hours_str: str = "",
) -> float | None:
    """返回「次日第一个时段窗口」内的随机时刻，用于当天额度用尽后复活。"""
    if not parse_slot_list(slots_str):
        return None
    tomorrow = (
        datetime.fromtimestamp(now_ts, tz=tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        + timedelta(days=1)
    )
    return next_slot_trigger(
        slots_str,
        jitter_minutes,
        tomorrow.timestamp(),
        tz,
        quiet_hours_str,
    )
'''

SCHED_IMPORT_OLD = (
    "from ..domain.session_key import is_friend_type\n"
    "from ...utils.time_utils import local_day_key, next_active_offset, next_day_active_offset\n"
)
SCHED_IMPORT_NEW = (
    "from ..domain.session_key import is_friend_type\n"
    "from ...utils.time_utils import (\n"
    "    local_day_key,\n"
    "    next_active_offset,\n"
    "    next_day_active_offset,\n"
    "    next_day_slot_trigger,\n"
    "    next_slot_trigger,\n"
    ")\n"
)

SCHED_HELPERS = '''
    # ------------------------------------------------------------------
    # 固定时段（slots）支持
    # ------------------------------------------------------------------
    def _slot_common(self, schedule_conf: dict) -> tuple[str, int] | None:
        """抽出 slots 配置；未启用或非法时返回 None。"""
        if not bool(schedule_conf.get("slots_enable", False)):
            return None
        slots_str = str(schedule_conf.get("slots", "") or "").strip()
        if not slots_str:
            return None
        try:
            jitter = int(schedule_conf.get("slot_jitter_minutes", 30) or 0)
        except (TypeError, ValueError):
            jitter = 30
        return slots_str, jitter

    def _slot_target(
        self, schedule_conf: dict, from_ts: float | None = None
    ) -> float | None:
        """按时段规则算下一次触发时间戳；未启用时返回 None。"""
        common = self._slot_common(schedule_conf)
        if common is None:
            return None
        slots_str, jitter = common
        return next_slot_trigger(
            slots_str,
            jitter,
            time.time() if from_ts is None else from_ts,
            self.plugin.timezone,
            schedule_conf.get("quiet_hours", "") or "",
        )

    def _next_day_slot_target(self, schedule_conf: dict) -> float | None:
        """当天额度用尽后，次日第一个时段窗口内的随机时刻。"""
        common = self._slot_common(schedule_conf)
        if common is None:
            return None
        slots_str, jitter = common
        return next_day_slot_trigger(
            slots_str,
            jitter,
            time.time(),
            self.plugin.timezone,
            schedule_conf.get("quiet_hours", "") or "",
        )

'''

SCHED_TRIGGER_OLD = (
    "        plugin = self.plugin\n"
    "        min_interval = int(schedule_conf.get(\"min_interval_minutes\", 30)) * 60\n"
)
SCHED_TRIGGER_NEW = (
    "        plugin = self.plugin\n"
    "        slot_target = self._slot_target(schedule_conf)\n"
    "        if slot_target is not None:\n"
    "            # 固定时段模式：间隔配置不再参与计算，只保留返回值形状。\n"
    "            now_ts = time.time()\n"
    "            run_date = datetime.fromtimestamp(slot_target, tz=plugin.timezone)\n"
    "            gap = int(max(0, slot_target - now_ts))\n"
    "            return (run_date, now_ts, gap, gap, gap, slot_target)\n"
    "        min_interval = int(schedule_conf.get(\"min_interval_minutes\", 30)) * 60\n"
)

SCHED_NEXTDAY_OLD = (
    "        plugin = self.plugin\n"
    "        now = time.time()\n"
    "        current = datetime.fromtimestamp(now, tz=plugin.timezone)\n"
)
SCHED_NEXTDAY_NEW = (
    "        plugin = self.plugin\n"
    "        slot_target = self._next_day_slot_target(schedule_conf)\n"
    "        if slot_target is not None:\n"
    "            return slot_target\n"
    "        now = time.time()\n"
    "        current = datetime.fromtimestamp(now, tz=plugin.timezone)\n"
)

SLOT_SCHEMA = {
    "slots_enable": {
        "description": "启用固定时段发送",
        "type": "bool",
        "default": False,
        "hint": "开启后忽略「最小/最大触发间隔」，改为在下面列出的时段前后随机发送",
    },
    "slots": {
        "description": "固定时段（24 小时制，逗号分隔）",
        "type": "string",
        "default": "9,11,14,17",
        "hint": "例如 9,11,14,17 表示上午九点、十一点，下午两点、五点各发一条",
    },
    "slot_jitter_minutes": {
        "description": "时段前后随机范围 (分钟)",
        "type": "int",
        "default": 30,
        "hint": "每个时段前、后各随机这么多分钟，30 表示九点那条会在 8:30–9:30 之间发出",
        "slider": {"min": 0, "max": 120, "step": 5},
    },
}

# ---------------------------------------------------------------- 工具函数


def read_text(path: str) -> str:
    with io.open(path, "r", encoding="utf-8", newline="") as fp:
        return fp.read()


def write_text(path: str, text: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as fp:
        fp.write(text)


def backup(path: str, tag: str) -> str:
    dst = path + f".bak.{tag}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, dst)
    return dst


def read_json(path: str):
    raw = io.open(path, "rb").read()
    has_bom = raw[:3] == b"\xef\xbb\xbf"
    return json.loads(raw.decode("utf-8-sig")), has_bom


def write_json(path: str, data, has_bom: bool) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    encoding = "utf-8-sig" if has_bom else "utf-8"
    with io.open(path, "w", encoding=encoding, newline="\n") as fp:
        fp.write(text)


# ---------------------------------------------------------------- 三个补丁


def patch_time_utils(root: str, dry: bool) -> list[str]:
    path = os.path.join(root, TU_REL)
    src = read_text(path)
    changed = []
    if "def next_slot_trigger(" in src:
        changed.append("time_utils:already")
    else:
        if TU_IMPORT_OLD not in src:
            raise SystemExit("time_utils 导入段锚点缺失")
        if src.count("def format_current_time(") != 1:
            raise SystemExit("time_utils 尾部锚点缺失")
        if not dry:
            backup(path, "slots")
        src = src.replace(TU_IMPORT_OLD, TU_IMPORT_NEW, 1)
        src = src.rstrip("\n") + "\n" + TU_APPEND
        if not dry:
            write_text(path, src)
        changed.append("time_utils")
    return changed


def patch_scheduler(root: str, dry: bool) -> list[str]:
    path = os.path.join(root, SCHED_REL)
    src = read_text(path)
    changed = []
    if "_slot_target" in src:
        changed.append("scheduler:already")
        return changed
    for needle in (SCHED_IMPORT_OLD, SCHED_TRIGGER_OLD, SCHED_NEXTDAY_OLD):
        if src.count(needle) != 1:
            raise SystemExit(f"scheduler 锚点缺失或重复: {needle[:60]!r}")
    if src.count("    def compute_next_trigger(") != 1:
        raise SystemExit("compute_next_trigger 锚点缺失")
    if not dry:
        backup(path, "slots")
    src = src.replace(SCHED_IMPORT_OLD, SCHED_IMPORT_NEW, 1)
    src = src.replace(
        "    def compute_next_trigger(",
        SCHED_HELPERS + "    def compute_next_trigger(",
        1,
    )
    src = src.replace(SCHED_TRIGGER_OLD, SCHED_TRIGGER_NEW, 1)
    src = src.replace(SCHED_NEXTDAY_OLD, SCHED_NEXTDAY_NEW, 1)
    if not dry:
        write_text(path, src)
    changed.append("scheduler")
    return changed


def patch_schema(root: str, dry: bool) -> list[str]:
    path = os.path.join(root, SCHEMA_REL)
    data, has_bom = read_json(path)
    items = data["friend_settings"]["items"]["schedule_settings"]["items"]
    changed = []
    added = [k for k in SLOT_SCHEMA if k not in items]
    if not added:
        changed.append("schema:already")
        return changed
    for key, spec in SLOT_SCHEMA.items():
        if key not in items:
            items[key] = spec
    if not dry:
        backup(path, "slots")
        write_json(path, data, has_bom)
    changed.append("schema:" + ",".join(added))
    return changed


def patch_config(cfg_path: str, dry: bool) -> list[str]:
    data, has_bom = read_json(cfg_path)
    sch = data["friend_settings"]["schedule_settings"]
    target = {"slots_enable": True, "slots": "9,11,14,17", "slot_jitter_minutes": 30}
    changed = []
    for key, value in target.items():
        if sch.get(key) != value:
            sch[key] = value
            changed.append(key)
    if not changed:
        return ["config:already"]
    if not dry:
        backup(cfg_path, "slots")
        write_json(cfg_path, data, has_bom)
    return ["config:" + ",".join(changed)]


PROMPT_LEN_OLD = (
    "只发一条短消息，通常十个字上下，最多二十来字；能一句话说完就不要再补。"
)
PROMPT_LEN_NEW = (
    "只发一条短消息，最多二十来字；多数时候四到八个字就够，"
    "像「在干嘛呢」这样只问一句也可以，不必每次都展开；能一句话说完就不要再补。"
)


def patch_prompt(cfg_path: str, dry: bool) -> list[str]:
    """放开极短问候：把「通常十个字上下」改成允许四到八个字的直接问句。"""
    data, has_bom = read_json(cfg_path)
    fs = data["friend_settings"]
    text = str(fs.get("proactive_prompt", "") or "")
    if PROMPT_LEN_NEW in text:
        return ["prompt:already"]
    if PROMPT_LEN_OLD not in text:
        raise SystemExit("proactive_prompt 长度段锚点缺失")
    fs["proactive_prompt"] = text.replace(PROMPT_LEN_OLD, PROMPT_LEN_NEW, 1)
    if not dry:
        backup(cfg_path, "slots")
        write_json(cfg_path, data, has_bom)
    return ["prompt:len"]


# ---------------------------------------------------------------- 验证


def verify(root: str) -> None:
    """不 import 插件，直接从源码切出函数跑单测。"""
    from datetime import datetime as _dt
    src = read_text(os.path.join(root, TU_REL))
    # 追加段在文件末尾，所以从 parse_slot_list 一刀切到文件尾，
    # 不能拿 local_day_key 当结束锚点（它在追加段之前）。
    start = src.index("def parse_slot_list(")
    fragment = src[start:]
    ns: dict = {}
    header = (
        "import random\n"
        "import zoneinfo\n"
        "from datetime import datetime, timedelta\n"
        "_DAY_MINUTES = 1440\n"
    )
    body = src[src.index("def _parse_hhmm(") : src.index("def local_day_key(")]
    exec(header + body + fragment, ns)

    parse_slot_list = ns["parse_slot_list"]
    next_slot_trigger = ns["next_slot_trigger"]
    next_day_slot_trigger = ns["next_day_slot_trigger"]
    tz = zoneinfo.ZoneInfo("Asia/Shanghai")

    assert parse_slot_list("9,11,14,17") == [540, 660, 840, 1020], parse_slot_list("9,11,14,17")
    assert parse_slot_list(" 17 , 9 , 9 ,x ") == [540, 1020]
    assert parse_slot_list("") == []

    # 1. 从凌晨 07:00 起，四次触发必须依次落在四个窗口里
    now = datetime(2026, 11, 12, 7, 0, tzinfo=tz).timestamp()
    windows = [(510, 570), (630, 690), (810, 870), (990, 1050)]
    got = []
    for _ in range(4):
        ts = next_slot_trigger("9,11,14,17", 30, now, tz, "0-8:30,12-13:30,18-24")
        assert ts is not None
        got.append(datetime.fromtimestamp(ts, tz=tz))
        now = ts + 1
    for (lo, hi), dt in zip(windows, got):
        minute = dt.hour * 60 + dt.minute
        assert lo <= minute <= hi, f"落在窗口外: {dt} 窗口 {lo}-{hi}"
    print("用例1 四次触发落在四个窗口:", [d.strftime("%H:%M:%S") for d in got])

    # 2. 同一天内窗口单调递增，且不重复
    for prev, cur in zip(got, got[1:]):
        assert cur > prev
    print("用例2 窗口单调递增: OK")

    # 3. 窗口已开始的整个跳过：09:25 再算下一次，不能又排回 09:00 那个窗口，
    #    否则同一时段会发两条。
    inside = datetime(2026, 11, 12, 9, 25, tzinfo=tz).timestamp()
    ts = next_slot_trigger("9,11,14,17", 30, inside, tz, "0-8:30,12-13:30,18-24")
    dt = datetime.fromtimestamp(ts, tz=tz)
    assert 630 <= dt.hour * 60 + dt.minute <= 690, dt
    print("用例3 已开始的窗口跳过，顺延到下一窗口:", dt.strftime("%H:%M:%S"))

    # 4. 全部时段都过去后，自动顺延到次日
    late = datetime(2026, 11, 12, 20, 0, tzinfo=tz).timestamp()
    ts = next_slot_trigger("9,11,14,17", 30, late, tz, "0-8:30,12-13:30,18-24")
    dt = datetime.fromtimestamp(ts, tz=tz)
    assert dt.day == 13, dt
    assert 510 <= dt.hour * 60 + dt.minute <= 570, dt
    print("用例4 顺延次日:", dt.strftime("%Y-%m-%d %H:%M:%S"))

    # 5. 次日复活只取次日第一个窗口
    ts = next_day_slot_trigger("9,11,14,17", 30, late, tz, "0-8:30,12-13:30,18-24")
    dt = datetime.fromtimestamp(ts, tz=tz)
    assert dt.day == 13 and 510 <= dt.hour * 60 + dt.minute <= 570, dt
    print("用例5 次日复活:", dt.strftime("%Y-%m-%d %H:%M:%S"))

    # 6. 空配置与全非法配置都返回 None，不会崩
    assert next_slot_trigger("", 30, late, tz) is None
    assert next_slot_trigger("x,y", 30, late, tz) is None
    print("用例6 空配置返回 None: OK")

    # 7. 抖动为 0 时就是整点（允许 ±60 秒内）
    ts = next_slot_trigger("9,11,14,17", 0, datetime(2026, 11, 12, 7, 0, tzinfo=tz).timestamp(), tz)
    dt = datetime.fromtimestamp(ts, tz=tz)
    assert dt.hour == 9 and dt.minute == 0, dt
    print("用例7 抖动0即整点:", dt.strftime("%H:%M:%S"))
    print("全部用例通过")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    if len(args) < 2:
        raise SystemExit(__doc__)
    root, cfg_path = args[0], args[1]

    changes: list[str] = []
    changes += patch_time_utils(root, dry)
    changes += patch_scheduler(root, dry)
    changes += patch_schema(root, dry)
    changes += patch_config(cfg_path, dry)
    changes += patch_prompt(cfg_path, dry)
    print(("dry-run " if dry else "applied ") + " | ".join(changes))
    if not dry:
        verify(root)
        data, _ = read_json(cfg_path)
        fs = data["friend_settings"]
        assert PROMPT_LEN_NEW in fs["proactive_prompt"]
        assert fs["schedule_settings"]["slots"] == "9,11,14,17"
        print("配置回读 OK，prompt 长度", len(fs["proactive_prompt"]))


if __name__ == "__main__":
    main()
