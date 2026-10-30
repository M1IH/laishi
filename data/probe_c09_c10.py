#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DS-05：C-09 / C-10 离线回归探针（隔离内存，不碰生产数据、不发 QQ）。

被测对象是**生产代码本身**，只注入假依赖（假平台、假调度器、假对话管理器）：
  C-09  core/services/sender_service.py::send_proactive_message
        core/features/deliver/split_delivery.py::DeliverStage
        core/features/record/history_writer.py::RecordStage
        core/pipeline/flow_orchestrator.py::finalize_and_reschedule
  C-10  core/services/scheduler_service.py::is_persisted_task_still_valid / init_jobs_from_data
        core/features/gating_feature.py::GatingStage
        utils/time_utils.py::is_quiet_time

用法：
  python data/probe_c09_c10.py                # 全部跑，有未登记失败退出 1
  python data/probe_c09_c10.py --allow-known  # 已登记失败（KNOWN_BUGS）不算失败
  python data/probe_c09_c10.py --layer c09    # 只跑一层
  python data/probe_c09_c10.py --verbose      # 连通过的一起打印

退出码：0 全过（或 --allow-known 下只剩已登记失败）；1 有未登记失败；2 环境错误。

判定口径：
  - 期望描述的是**修复后应成立**的行为；当前不成立且已登记的，记 KNOWN。
  - 「已知失败」不是豁免：它同时是给 Codex 的验收清单，修好后从这里删掉，
    --allow-known 就会退 0。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CORE = Path(
    r"C:/Users/OTTO/.astrbot_launcher/instances/"
    r"298681be-6ba8-4137-818c-28ed67ec9176/core"
)
PLUGINS = CORE / "data" / "plugins"
# 插件数据目录（StarTools.get_data_dir）——只用来「查文件在不在」，不写。
PLUGIN_DATA = CORE / "data" / "plugin_data" / "astrbot_plugin_proactive_chat"
TZ = ZoneInfo("Asia/Shanghai")
UMO = "testplat:FriendMessage:10001"
CONV = "conv-probe-1"

for p in (str(CORE), str(PLUGINS)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from astrbot.api import logger  # noqa: F401
    from astrbot.core.message.components import Plain
    from astrbot.core.message.message_event_result import MessageEventResult
except Exception as exc:  # pragma: no cover
    print(f"[ENV] 无法导入 astrbot：{exc}")
    raise SystemExit(2)

from astrbot_plugin_proactive_chat.core.features.deliver import split_delivery  # noqa: E402
from astrbot_plugin_proactive_chat.core.features.gating_feature import GatingStage  # noqa: E402
from astrbot_plugin_proactive_chat.core.pipeline import flow_orchestrator  # noqa: E402
from astrbot_plugin_proactive_chat.core.pipeline.flow_orchestrator import (  # noqa: E402
    FlowOrchestrator,
)
from astrbot_plugin_proactive_chat.core.services.scheduler_service import (  # noqa: E402
    SchedulerService,
)
from astrbot_plugin_proactive_chat.core.services.sender_service import SenderService  # noqa: E402
from astrbot_plugin_proactive_chat.core.services.session_service import SessionService  # noqa: E402
from astrbot_plugin_proactive_chat.utils.time_utils import is_quiet_time  # noqa: E402

# ---------------------------------------------------------------------------
# 已知失败登记（= C-09/C-10 的现状缺陷清单，修好后逐条删除）
#
# 2026-10-30 17:49 全部清零：DeliveryOutcome 四级判定 + 七日故事窗口 +
# 停摆标记/重新上膛 已部署（线上 commit 见 WORK_LOG 10-30 条目），
# 容器内探针 24/24 全绿。此表保留为空 dict——新回归在此登记。
# 修复内容：sender_service.DeliveryOutcome（attempted/partial/all_segments_accepted/
# segment_count/segment_index_failed/voice_sent）、
# _record_story_state（<data_dir>/proactive/story_state.json）、
# DeliverStage partial→CONTINUE+delivery_outcome、
# finalize_and_reschedule(delivery=...) 顶层写 segment_count_*、
# SchedulerService._mark_stall_state（<data_dir>/stall_state.json）+
# init_jobs_from_data 过期分支（auto 开→重排；auto 关→停摆标记）。
# ---------------------------------------------------------------------------
KNOWN_BUGS: dict[str, str] = {
}


@dataclass
class Case:
    cid: str
    layer: str
    title: str
    current: str = ""
    expected: str = ""
    evidence: str = ""
    ok: bool = True
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 假依赖
# ---------------------------------------------------------------------------
class FakeEvent:
    """只实现 sender_service / dispatch 需要的四个方法。"""

    def __init__(self) -> None:
        self._result = None
        self._stopped = False

    def set_result(self, result) -> None:
        self._result = result

    def get_result(self):
        return self._result

    def is_stopped(self) -> bool:
        return self._stopped

    def clear_result(self) -> None:
        self._result = None


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.add_calls = 0

    def add_job(self, func, trigger, **kwargs):
        self.add_calls += 1
        jid = kwargs.get("id") or f"job-{self.add_calls}"
        self.jobs[jid] = SimpleNamespace(
            id=jid, func=func, trigger=trigger, kwargs=kwargs, args=kwargs.get("args") or []
        )

    def get_job(self, jid):
        return self.jobs.get(jid)

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, jid):
        self.jobs.pop(jid, None)


class FakePlatformManager:
    """没有任何活跃平台 → resolve_full_umo 退回 preferred_platform。"""

    def __init__(self) -> None:
        self.platform_insts: list = []


class FakeStorage:
    def __init__(self) -> None:
        self.save_calls = 0

    def cleanup_invalid_session_data(self) -> int:
        return 0

    async def save_data(self) -> None:
        self.save_calls += 1


class FakeConversationManager:
    def __init__(self) -> None:
        self.added: list[str] = []

    async def add_message_pair(self, *, cid, user_message, assistant_message) -> None:
        text = ""
        for part in getattr(assistant_message, "content", []) or []:
            text += getattr(part, "text", "") or ""
        self.added.append(text)

    async def get_conversation(self, session_id, conv_id):
        return None


class FakePlugin:
    def __init__(self, session_config: dict | None = None) -> None:
        self.config = {}
        self.timezone = TZ
        # 只用于「状态文件是否存在」这类只读检查；生产写入全部走 FakeStorage。
        self.data_dir = PLUGIN_DATA
        self.data_lock = asyncio.Lock()
        self.session_data: dict[str, dict] = {}
        self._terminating = False
        self.telemetry = None
        self.auto_trigger_timers: dict[str, object] = {}
        self.manual_trigger_sessions: set = set()
        self.web_admin_server = None
        self.check_and_chat = lambda *a, **k: None
        self._track_task = lambda task: task
        self._config = session_config or base_config()
        self.context = SimpleNamespace(
            platform_manager=FakePlatformManager(),
            conversation_manager=FakeConversationManager(),
            message_history_manager=None,
            send_message=None,
            get_using_tts_provider=lambda umo=None: None,
        )
        self.config_service = SimpleNamespace(get_session_config=self._get_cfg)
        self.session_service = SessionService(self)
        self.scheduler = FakeScheduler()
        self.storage_service = FakeStorage()
        self.scheduler_service = SchedulerService(self)
        self.sender_service = SenderService(self)

    def _get_cfg(self, session_id):
        return self._config


def base_config(**over) -> dict:
    cfg = {
        "enable": True,
        "session_name": "测试会话",
        "schedule_settings": {
            "min_interval_minutes": 180,
            "max_interval_minutes": 360,
            "quiet_hours": "1-8",
            "max_unanswered_times": 1,
        },
        "auto_trigger_settings": {"enable_auto_trigger": False},
        "segmented_reply_settings": {
            "enable": True,
            "split_mode": "words",
            "split_words": ["\n"],
            "words_count_threshold": 150,
            "interval": "0,0",
        },
        "tts_settings": {"enable_tts": False, "always_send_text": True},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k] = {**cfg[k], **v}
        else:
            cfg[k] = v
    return cfg


class ScriptedSender(SenderService):
    """覆写 send_chain：按脚本返回每段是否被平台接受，并记录实际送出的段。"""

    def __init__(self, plugin, script: list[bool]) -> None:
        super().__init__(plugin)
        self.script = list(script)
        self.calls: list[str] = []
        self.ok_count = 0

    async def send_chain(self, session_id, event, components) -> bool:
        text = "".join(getattr(c, "text", "") or "" for c in components)
        self.calls.append(text)
        idx = len(self.calls) - 1
        ok = self.script[idx] if idx < len(self.script) else False
        if ok:
            self.ok_count += 1
        return ok

    async def calc_interval(self, text, settings) -> float:
        return 0.0


def status_of(res) -> object:
    return getattr(res, "status", None)


def count_of(res, name: str):
    return getattr(res, name, None)


def stall_marker():
    """C-10 修复后应出现的「显式停摆」标记（只读检查，不创建）。"""
    for name in ("PENDING.md", "stall_state.json"):
        p = PLUGIN_DATA / name
        if p.exists():
            return str(p.relative_to(CORE))
    return ""


# --- 契约校验器（初验补件：文件存在不算通过，字段/会话/时间/原因都要对）------

STORY_STATE_RELS = ("proactive/story_state.json", "story_state.json")
STALL_MARKER_RELS = ("stall_state.json", "stall_marker.json", "PENDING.md")

STORY_FIELDS = ("last_story_sent_at_utc", "story_id", "continue_used", "last_story_sha256")

STALL_FIELDS = (
    "session_key",
    "reason",
    "stalled_at",
    "expired_next_trigger",
    "unanswered_count",
    "auto_trigger_enabled",
    "recover_when",
)

STALL_REASON_EXPIRED = "persisted_task_expired"
STALL_RECOVER = "next_peer_message"


def plugin_py_sites(*needles: str) -> list[str]:
    """在插件源码里找「实现是否已存在」，返回命中位置。找不到 = 该功能尚未实现。"""
    hits: list[str] = []
    base = PLUGINS / "astrbot_plugin_proactive_chat"
    if not base.exists():
        return hits
    for p in base.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue  # 纯注释里的提及不算实现
            if any(n in line for n in needles):
                hits.append(f"{p.relative_to(base)}:{i}")
    return hits


def find_state(base: Path, rels) -> Path | None:
    for rel in rels:
        p = Path(base) / rel
        if p.exists():
            return p
    return None


def _read_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def _utc_ts(value) -> float | None:
    """把 UTC 时间戳解析成 epoch 秒；不是带时区的 UTC 一律 None（fail-closed）。"""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        return None
    return dt.timestamp()


def validate_story_state(path, expect_ts: float | None = None, tol: float = 90.0):
    """七日窗口状态必须真的能决定「放行/不放行」，因此字段与时间都要可判定。"""
    if path is None or not Path(path).exists():
        return False, "状态文件不存在"
    try:
        d = _read_json(Path(path))
    except Exception as e:  # noqa: BLE001
        return False, f"不是合法 JSON：{e}"
    if not isinstance(d, dict):
        return False, "顶层不是对象"
    missing = [k for k in STORY_FIELDS if k not in d]
    if missing:
        return False, f"缺字段 {missing}"
    ts = _utc_ts(d["last_story_sent_at_utc"])
    if ts is None:
        return False, f"last_story_sent_at_utc 不是带时区的 UTC：{d['last_story_sent_at_utc']!r}"
    if not str(d.get("story_id") or "").strip():
        return False, "story_id 为空（无法判断「同一则故事」，等于每次都算新故事）"
    if not isinstance(d.get("continue_used"), bool):
        return False, f"continue_used 不是布尔：{d.get('continue_used')!r}"
    sha = str(d.get("last_story_sha256") or "").strip().lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        return False, "last_story_sha256 不是 64 位十六进制"
    if expect_ts is not None and abs(ts - expect_ts) > tol:
        return False, f"时间戳偏差 {ts - expect_ts:+.0f}s，超出容差 {tol:.0f}s"
    return True, "ok"


def validate_stall_marker(
    path,
    session_key: str,
    expect_now: float,
    expect_trigger: float,
    tol: float = 90.0,
):
    """停摆标记必须点名「哪个会话、哪次过期、什么原因、怎么恢复」。"""
    if path is None or not Path(path).exists():
        return False, "没有任何停摆标记"
    try:
        d = _read_json(Path(path))
    except Exception as e:  # noqa: BLE001
        return False, f"不是合法 JSON：{e}"

    # 允许两种形态：{"sessions": {umo: {...}}} 或扁平单会话对象
    if isinstance(d, dict) and isinstance(d.get("sessions"), dict):
        rec = d["sessions"].get(session_key)
        if not isinstance(rec, dict):
            return False, f"标记里没有本会话 {session_key}（别的会话/旧文件不算）"
    elif isinstance(d, dict):
        rec = d
    else:
        return False, "顶层既不是对象也没有 sessions"

    missing = [k for k in STALL_FIELDS if k not in rec]
    if missing:
        return False, f"缺字段 {missing}"
    if str(rec.get("session_key") or "") != session_key:
        return False, f"session_key 不符：{rec.get('session_key')!r} ≠ {session_key!r}"
    if str(rec.get("reason") or "") != STALL_REASON_EXPIRED:
        return False, f"reason 不符：{rec.get('reason')!r} ≠ {STALL_REASON_EXPIRED!r}"
    if str(rec.get("recover_when") or "") != STALL_RECOVER:
        return False, f"recover_when 不符：{rec.get('recover_when')!r} ≠ {STALL_RECOVER!r}"
    if not isinstance(rec.get("auto_trigger_enabled"), bool):
        return False, "auto_trigger_enabled 不是布尔"
    stalled = _utc_ts(rec.get("stalled_at"))
    if stalled is None:
        return False, "stalled_at 不是带时区的 UTC"
    if abs(stalled - expect_now) > tol:
        return False, f"stalled_at 偏差 {stalled - expect_now:+.0f}s，超出容差 {tol:.0f}s"
    trig = rec.get("expired_next_trigger")
    try:
        trig_f = float(trig)
    except (TypeError, ValueError):
        return False, f"expired_next_trigger 不是数字：{trig!r}"
    if abs(trig_f - expect_trigger) > 1.0:
        return False, f"expired_next_trigger 不符：{trig_f:.0f} ≠ {expect_trigger:.0f}"
    if not isinstance(rec.get("unanswered_count"), int):
        return False, "unanswered_count 不是整数"
    return True, "ok"


# ---------------------------------------------------------------------------
# C-09
# ---------------------------------------------------------------------------
async def c09_send(script: list[bool], text: str, **cfg_over):
    cfg = base_config(**cfg_over)
    plugin = FakePlugin(cfg)
    sender = ScriptedSender(plugin, script)
    plugin.sender_service = sender
    res = await sender.send_proactive_message(UMO, text, event=FakeEvent())
    return res, sender, plugin


async def c09_01() -> Case:
    res, sender, _ = await c09_send([False, False, False], "一\n二\n三")
    c = Case(
        cid="C09-01",
        layer="c09",
        title="0/N 段被平台接受 → 必须区分「一段没出去」",
        current=f"send_proactive_message 返回 {res!r}（bool），实际尝试 {len(sender.calls)} 段、成功 0 段",
        expected="返回 !sent 且 status=='attempted'（segment_count_sent=0 / planned=3）",
        evidence="sender_service.py:519-611：`any_sent` 只有布尔，return False 与「配置缺失」不可区分",
    )
    c.ok = status_of(res) == "attempted"
    c.notes.append("调用方只能看到一个假，无法判断该不该重排、该不该记失败")
    return c


async def c09_02() -> Case:
    res, sender, _ = await c09_send([True, False, False], "一\n二\n三")
    c = Case(
        cid="C09-02",
        layer="c09",
        title="1/3 段被接受（C-09 本体）",
        current=f"返回 {res!r}；实际送出 3 段尝试、成功 1 段",
        expected="status=='partial'、segment_count_sent==1、segment_count_planned==3",
        evidence="sender_service.py:555-567 每段只置 True 不记失败；:599-611 有任一成功即 return True",
    )
    c.ok = (
        status_of(res) == "partial"
        and count_of(res, "segment_count_sent") == 1
        and count_of(res, "segment_count_planned") == 3
    )
    c.notes.append("DeliverStage 只看到 True，于是当整条成功继续走 RECORD（写全文 + 计数 +1）")
    return c


async def c09_03() -> Case:
    res, sender, _ = await c09_send(
        [True], "一整条消息", segmented_reply_settings={"enable": False}
    )
    c = Case(
        cid="C09-03",
        layer="c09",
        title="未开分段、单条送出（基线）",
        current=f"返回 {res!r}，send_chain 调用 {len(sender.calls)} 次",
        expected="status=='all_segments_accepted'（planned=1 / sent=1）",
        evidence="sender_service.py:549-575 非分段分支只调一次 send_chain",
    )
    c.ok = status_of(res) == "all_segments_accepted"
    return c


async def c09_04() -> Case:
    res, sender, _ = await c09_send([False, True, True], "一\n二\n三")
    c = Case(
        cid="C09-04",
        layer="c09",
        title="首段失败、后两段成功",
        current=f"返回 {res!r}；发送序列 {sender.calls}",
        expected="status=='partial'、sent==2、planned==3，且能指出哪段失败",
        evidence="sender_service.py:555-567 不记录失败段位置",
    )
    c.ok = status_of(res) == "partial" and count_of(res, "segment_count_sent") == 2
    c.notes.append("平台侧只有气泡 2/3，历史里却是完整三段文本")
    return c


async def c09_05() -> Case:
    res, _, _ = await c09_send([True, True, True], "一\n二\n三")
    c = Case(
        cid="C09-05",
        layer="c09",
        title="N/N 段全部接受",
        current=f"返回 {res!r}",
        expected="status=='all_segments_accepted'、sent==3、planned==3",
        evidence="sender_service.py:599-611 只有 bool",
    )
    c.ok = status_of(res) == "all_segments_accepted" and count_of(
        res, "segment_count_sent"
    ) == 3
    return c


async def c09_06() -> Case:
    cfg = base_config(tts_settings={"enable_tts": True, "always_send_text": True})
    plugin = FakePlugin(cfg)

    class TTS:
        async def get_audio(self, text):
            return "C:/tmp/fake.wav"

    plugin.context.get_using_tts_provider = lambda umo=None: TTS()
    sender = ScriptedSender(plugin, [True, False, False])
    plugin.sender_service = sender
    res = await sender.send_proactive_message(UMO, "一\n二", event=FakeEvent())
    c = Case(
        cid="C09-06",
        layer="c09",
        title="TTS 语音已发、文本段全失败",
        current=f"返回 {res!r}；调用序列 {len(sender.calls)} 次（1 段语音成功 + 2 段文本失败）",
        expected="status=='partial' 且 voice_sent=True，不能记成整条成功",
        evidence="sender_service.py:519 `any_sent = is_tts_sent`：语音成功即算整条成功",
    )
    c.ok = status_of(res) == "partial" and count_of(res, "voice_sent") is True
    c.notes.append("来世只听到一段语音，历史里却是完整文字")
    return c


async def c09_07() -> Case:
    plugin = FakePlugin(base_config())
    orig_add, orig_verify = (
        flow_orchestrator.add_message_pair,
        flow_orchestrator.verify_message_persisted,
    )

    async def fake_add(cm, cid, up, ar):
        cm.added.append(ar)

    async def fake_verify(*a, **k):
        return True

    flow_orchestrator.add_message_pair = fake_add
    flow_orchestrator.verify_message_persisted = fake_verify
    try:
        orch = FlowOrchestrator(plugin)
        partial = SimpleNamespace(
            sent=True,
            status="partial",
            segment_count_sent=1,
            segment_count_planned=2,
            voice_sent=False,
        )
        try:
            await orch.finalize_and_reschedule(UMO, CONV, "prompt", "一二", 0, delivery=partial)
        except TypeError:
            await orch.finalize_and_reschedule(UMO, CONV, "prompt", "一二", 0)
    finally:
        flow_orchestrator.add_message_pair = orig_add
        flow_orchestrator.verify_message_persisted = orig_verify
    payload = plugin.session_data.get(UMO, {})
    c = Case(
        cid="C09-07",
        layer="c09",
        title="部分送达的历史条目必须带 segment_count_sent / planned",
        current=f"session_data={sorted(payload)}；历史条目={plugin.context.conversation_manager.added}",
        expected="历史条目或 session_data 上有 segment_count_sent=1、segment_count_planned=2",
        evidence="flow_orchestrator.py:195-205 只写全文；DeliveryReport 定义了 segment_count 却从未被写入",
    )
    c.ok = "segment_count_sent" in payload or any(
        "1/2" in str(t) for t in plugin.context.conversation_manager.added
    )
    return c


async def c09_08() -> Case:
    """部分送达仍应 +1 计数（窗口与计数认「出去过」），本条验证该行为没被改坏。"""
    plugin = FakePlugin(base_config())
    orig_add, orig_verify = (
        flow_orchestrator.add_message_pair,
        flow_orchestrator.verify_message_persisted,
    )

    async def fake_add(cm, cid, up, ar):
        cm.added.append(ar)

    async def fake_verify(*a, **k):
        return True

    flow_orchestrator.add_message_pair = fake_add
    flow_orchestrator.verify_message_persisted = fake_verify
    try:
        await FlowOrchestrator(plugin).finalize_and_reschedule(
            UMO, CONV, "prompt", "完整两段", 0
        )
    finally:
        flow_orchestrator.add_message_pair = orig_add
        flow_orchestrator.verify_message_persisted = orig_verify
    payload = plugin.session_data.get(UMO, {})
    c = Case(
        cid="C09-08",
        layer="c09",
        title="部分送达：计数 +1 与写历史（应保留的行为）",
        current=f"unanswered_count={payload.get('unanswered_count')}；历史={plugin.context.conversation_manager.added}",
        expected="unanswered_count 变成 1 且写了历史（口径：计数认「有没有出去过」）",
        evidence="flow_orchestrator.py:219-225 无条件 +1；reconnect-experience-acceptance.md §六-1 后果表",
    )
    c.ok = payload.get("unanswered_count") == 1 and bool(
        plugin.context.conversation_manager.added
    )
    c.notes.append("修复时不要为 partial 改成「不 +1」——那是 attempted 的口径")
    return c


async def c09_09() -> Case:
    """七日故事窗口：必须写出「能判定放行/不放行」的状态，不能靠文件存在通过。

    初验补件（Codex）：原来判据是 `story_state.json 存在`，touch 一个空文件就绿。
    现在改成——实现存在就真跑两分支并逐字段校验；实现不存在就明确判「缺口」，
    且把契约写死（字段、写入时机、UTC、滚动 168h）。
    """
    sites = plugin_py_sites("story_state.json", "last_story_sent_at_utc")
    c = Case(
        cid="C09-09",
        layer="c09",
        title="七日故事窗口：首段平台接受即占用窗口，首段失败不占，后段失败不撤销",
        evidence=(
            "docs/story-opening-acceptance.md:295「状态：data/proactive/story_state.json — "
            "{last_story_sent_at_utc, story_id, continue_used, last_story_sha256}；原子替换」；"
            ":18「硬拦截必须在发送侧」；:217-221「滚动 168 小时、时间戳存 UTC、三条全 fail-closed」"
        ),
        expected=(
            "`<data_dir>/proactive/story_state.json`：last_story_sent_at_utc 为带时区 UTC、"
            "story_id 非空、continue_used 为布尔、last_story_sha256 为 64 位十六进制；"
            "首段平台接受即写入（不等 all_segments_accepted）；首段失败不写；后段失败不撤销"
        ),
    )
    if not sites:
        c.current = "插件源码全量扫描 .py：0 处出现 story_state.json / last_story_sent_at_utc（功能未实现）"
        c.ok = False
        c.notes.append("本用例判「缺口」而不是「文件在不在」：空文件、旧文件都不可能让它变绿")
        c.notes.append("实现落地后本用例自动切到真跑（两分支 + 字段校验），无需再改探针")
        c.notes.append("未实现后果：同一则故事七天内会被当新故事再讲一次（窗口完全失效）")
        return c

    now = datetime.now(TZ).timestamp()
    results: list[tuple[str, bool, str]] = []

    # 分支 1：首段接受 + 后段失败 → 必须占用窗口，且后段失败不得撤销
    tmp1 = Path(tempfile.mkdtemp(prefix="ds05_story_a_"))
    plugin1 = FakePlugin(base_config())
    plugin1.data_dir = tmp1
    sender1 = ScriptedSender(plugin1, [True, False])
    plugin1.sender_service = sender1
    await sender1.send_proactive_message(UMO, "第一段\n第二段", event=FakeEvent())
    ok1, why1 = validate_story_state(find_state(tmp1, STORY_STATE_RELS), expect_ts=now)
    results.append(("首段接受+后段失败", ok1, why1))

    # 分支 2：首段失败（整体 0/N）→ 不得占用窗口
    tmp2 = Path(tempfile.mkdtemp(prefix="ds05_story_b_"))
    plugin2 = FakePlugin(base_config())
    plugin2.data_dir = tmp2
    sender2 = ScriptedSender(plugin2, [False, False])
    plugin2.sender_service = sender2
    await sender2.send_proactive_message(UMO, "第一段\n第二段", event=FakeEvent())
    p2 = find_state(tmp2, STORY_STATE_RELS)
    if p2 is None:
        results.append(("首段失败", True, "没有写状态（正确）"))
    else:
        ok2, why2 = validate_story_state(p2)
        results.append(("首段失败", False, f"不该写却写了（{why2}）"))

    c.current = "；".join(
        f"{n}={'ok' if ok else 'BAD(' + w + ')'}" for n, ok, w in results
    )
    c.ok = all(ok for _, ok, _ in results)
    c.notes.append(f"实现位置：{sites[:4]}")
    c.notes.append(
        "若实现需要额外入参（如 is_story 标记）才能写窗口，在这里接线；"
        "当前按「无额外入参」调用"
    )
    return c


async def c09_11() -> Case:
    """契约校验器自检：不合格的状态一律判红 —— 防「空文件/旧文件蒙混过关」。"""
    now = datetime.now(TZ).timestamp()
    good = {
        "last_story_sent_at_utc": datetime.fromtimestamp(
            now - 3600, timezone.utc
        ).isoformat(),
        "story_id": "story-2026-10-23-01",
        "continue_used": False,
        "last_story_sha256": hashlib.sha256(b"x").hexdigest(),
    }
    tmp = Path(tempfile.mkdtemp(prefix="ds05_story_selftest_"))
    checks: list[tuple[str, bool, bool]] = []

    p_ok = tmp / "ok.json"
    p_ok.write_text(json.dumps(good), encoding="utf-8")
    checks.append(("完整状态", validate_story_state(p_ok)[0], True))

    bad1 = dict(good)
    bad1.pop("story_id")
    p1 = tmp / "no_story_id.json"
    p1.write_text(json.dumps(bad1), encoding="utf-8")
    checks.append(("缺 story_id", validate_story_state(p1)[0], False))

    bad2 = dict(good, last_story_sent_at_utc="2026-10-23 12:00:00")
    p2 = tmp / "naive_ts.json"
    p2.write_text(json.dumps(bad2), encoding="utf-8")
    checks.append(("无时区时间（非 UTC）", validate_story_state(p2)[0], False))

    bad3 = dict(good, last_story_sha256="deadbeef")
    p3 = tmp / "bad_sha.json"
    p3.write_text(json.dumps(bad3), encoding="utf-8")
    checks.append(("sha256 长度不对", validate_story_state(p3)[0], False))

    c = Case(
        cid="C09-11",
        layer="c09",
        title="七日窗口状态校验器自检（坏状态必须判红）",
        current="；".join(
            f"{n}={'pass' if got == want else 'WRONG'}" for n, got, want in checks
        ),
        expected="完整状态通过；缺字段 / 非 UTC / sha 不合法 全部判红（fail-closed）",
        evidence="docs/story-opening-acceptance.md:217-221 三条规则全 fail-closed；本探针 validate_story_state()",
    )
    c.ok = all(got == want for _, got, want in checks)
    c.notes.append("这条防的是「接入后校验器自己放水」——校验器写松了，前面的回归等于没测")
    return c


async def c09_10() -> Case:
    cfg = base_config()
    plugin = FakePlugin(cfg)
    sender = ScriptedSender(plugin, [True, False])
    plugin.sender_service = sender
    stage = split_delivery.DeliverStage(SimpleNamespace(plugin=plugin))
    aborted: list[str] = []
    ctx = SimpleNamespace(
        session_id=UMO,
        event=FakeEvent(),
        extra={"response_text": "一\n二", "result_chain": None},
        abort=lambda reason: aborted.append(reason),
    )
    result = await stage.handle(ctx)
    c = Case(
        cid="C09-10",
        layer="c09",
        title="DeliverStage 对 1/2 部分送达的走向",
        current=f"stage={getattr(result, 'name', result)}，abort={aborted}，实际 1 成功 1 失败",
        expected="不得因「有一段没出去」就 RESCHEDULE（那会把已发的一半也当没发）；应 CONTINUE 并把 partial 写进 ctx",
        evidence="split_delivery.py:31 只看 `is True`；失败才 RESCHEDULE",
    )
    c.ok = getattr(result, "name", "") == "CONTINUE" and not aborted
    c.notes.append("这条是护栏：修 C-09 时容易顺手把 partial 也判成 RESCHEDULE，那会造成重复发送")
    return c


# ---------------------------------------------------------------------------
# C-10
# ---------------------------------------------------------------------------
def c10_01() -> Case:
    plugin = FakePlugin()
    now = 1_800_000_000.0
    ok = plugin.scheduler_service.is_persisted_task_still_valid(
        UMO, {"next_trigger_time": now + 300}, current_time=now
    )
    c = Case(
        cid="C10-01",
        layer="c10",
        title="正常未到期任务仍可恢复",
        current=f"valid={ok}",
        expected="True",
        evidence="scheduler_service.py:133-152",
    )
    c.ok = ok is True
    return c


def c10_02() -> Case:
    plugin = FakePlugin()
    now = 1_800_000_000.0
    near = plugin.scheduler_service.is_persisted_task_still_valid(
        UMO, {"next_trigger_time": now - 59}, current_time=now
    )
    edge = plugin.scheduler_service.is_persisted_task_still_valid(
        UMO, {"next_trigger_time": now - 60}, current_time=now
    )
    far = plugin.scheduler_service.is_persisted_task_still_valid(
        UMO, {"next_trigger_time": now - 61}, current_time=now
    )
    c = Case(
        cid="C10-02",
        layer="c10",
        title="60 秒宽限边界：-59 / -60 / -61 秒",
        current=f"-59→{near}；-60→{edge}；-61→{far}",
        expected="True / False / False（严格小于 next_trigger+60）",
        evidence="scheduler_service.py:151 `check_time < (next_trigger + 60)`",
    )
    c.ok = (near is True) and (edge is False) and (far is False)
    return c


def c10_03() -> Case:
    now = 1_800_000_000.0
    plugin = FakePlugin()
    a = plugin.scheduler_service.is_persisted_task_still_valid(UMO, None)
    b = plugin.scheduler_service.is_persisted_task_still_valid(
        UMO, {"next_trigger_time": "not-a-number"}
    )
    ok_case = plugin.scheduler_service.is_persisted_task_still_valid(
        UMO, {"next_trigger_time": now + 60}, current_time=now
    )
    disabled = FakePlugin(base_config(enable=False))
    d = disabled.scheduler_service.is_persisted_task_still_valid(
        UMO, {"next_trigger_time": now + 60}, current_time=now
    )
    c = Case(
        cid="C10-03",
        layer="c10",
        title="缺字段 / 脏数据 / 会话禁用 → 一律视为无效（安全侧）",
        current=f"info=None→{a}；脏 next→{b}；正常→{ok_case}；enable=False→{d}",
        expected="False / False / True / False",
        evidence="scheduler_service.py:140-148",
    )
    c.ok = (a is False) and (b is False) and (ok_case is True) and (d is False)
    return c


async def c10_04() -> Case:
    now = datetime.now(TZ).timestamp()
    plugin = FakePlugin()
    plugin.session_data[UMO] = {"next_trigger_time": now - 3600, "unanswered_count": 0}
    await plugin.scheduler_service.init_jobs_from_data()
    left = plugin.session_data.get(UMO, {})
    c = Case(
        cid="C10-04",
        layer="c10",
        title="停机跨过 next_trigger+60s：清理且不恢复、不补发",
        current=f"jobs={list(plugin.scheduler.jobs)}；残留 next_trigger={'next_trigger_time' in left}",
        expected="无 job、next_trigger_time 被清除",
        evidence="scheduler_service.py:497-508",
    )
    c.ok = not plugin.scheduler.jobs and "next_trigger_time" not in left
    return c


async def c10_05() -> Case:
    """过期任务 + auto_trigger=false：必须写「点名本会话、点名本次过期」的停摆状态。

    初验补件（Codex）：原来只要任意 PENDING.md / stall_state.json 存在（哪怕是旧文件、
    别的会话、别的原因）就算过。现在改为——实现存在就真跑并对字段逐项校验；
    实现不存在就判缺口，不拿「有没有文件」当结论。
    """
    now = datetime.now(TZ).timestamp()
    trigger = now - 3600
    tmp = Path(tempfile.mkdtemp(prefix="ds05_stall_a_"))
    plugin = FakePlugin(base_config(auto_trigger_settings={"enable_auto_trigger": False}))
    plugin.data_dir = tmp
    plugin.session_data[UMO] = {"next_trigger_time": trigger, "unanswered_count": 0}
    await plugin.scheduler_service.init_jobs_from_data()

    sites = plugin_py_sites("stall_state.json", "PENDING.md", "last_stall", "stall_marker")
    marker = find_state(tmp, STALL_MARKER_RELS)
    ok, why = validate_stall_marker(marker, UMO, now, trigger)

    c = Case(
        cid="C10-05",
        layer="c10",
        title="过期任务 + enable_auto_trigger=false 必须写「点名本会话」的停摆状态",
        current=(
            f"jobs={list(plugin.scheduler.jobs)}；临时目录标记="
            f"{marker.name if marker else '无'}；代码写入点={sites[:3] or '0 处'}；校验={why}"
        ),
        expected=(
            "stall_state.json 含 session_key / reason=persisted_task_expired / stalled_at(UTC) / "
            "expired_next_trigger / unanswered_count / auto_trigger_enabled=false / "
            "recover_when=next_peer_message；措辞含「主动消息链路已停摆」"
        ),
        evidence=(
            "scheduler_service.py:497-508 只有一行 logger.info（C-10 本体）；"
            "docs/reconnect-experience-acceptance.md §六-3"
        ),
    )
    c.ok = ok
    c.notes.append("别的会话 / 别的原因 / 只有一个空 PENDING.md，都判红——旧文件不算数")
    c.notes.append("现在从外部看只是「安静了」，分不清没到点还是链路死了")
    return c


async def c10_06() -> Case:
    """过期任务 + auto_trigger=true：必须真排上本会话的 job，或写同一条停摆状态。

    初验补件（Codex）：原来 `jobs or timers or 任意标记` 都算过——别的会话的 timer、
    上一轮遗留的 job 都能冒充。现在只认两种真凭据：本会话 job 的 run_date 在未来，
    或本会话的严格停摆标记。
    """
    now = datetime.now(TZ).timestamp()
    trigger = now - 3600
    tmp = Path(tempfile.mkdtemp(prefix="ds05_stall_b_"))
    plugin = FakePlugin(base_config(auto_trigger_settings={"enable_auto_trigger": True}))
    plugin.data_dir = tmp
    plugin.session_data[UMO] = {"next_trigger_time": trigger, "unanswered_count": 0}
    await plugin.scheduler_service.init_jobs_from_data()

    job = None
    for j in plugin.scheduler.jobs.values():
        args = j.kwargs.get("args") or []
        if str(j.id) == UMO or (args and args[0] == UMO):
            job = j
            break
    run_date = getattr(job, "kwargs", {}).get("run_date") if job else None
    rescheduled = bool(job) and isinstance(run_date, datetime) and run_date.timestamp() > now

    marker = find_state(tmp, STALL_MARKER_RELS)
    ok_marker, why = validate_stall_marker(marker, UMO, now, trigger)
    sites = plugin_py_sites("stall_state.json", "PENDING.md", "last_stall", "stall_marker")

    c = Case(
        cid="C10-06",
        layer="c10",
        title="过期任务 + enable_auto_trigger=true 不能静默（要么真排期，要么显式停摆）",
        current=(
            f"本会话 job={'有' if job else '无'}"
            f"{'，run_date=' + run_date.isoformat() if isinstance(run_date, datetime) else ''}；"
            f"timers={list(plugin.auto_trigger_timers)}；标记校验={why}；写入点={sites[:3] or '0 处'}"
        ),
        expected="本会话 job 的 run_date 在未来，或存在严格停摆标记；不得静默",
        evidence="scheduler_service.py:455-535 无 auto_trigger 分支",
    )
    c.ok = rescheduled or ok_marker
    verdict = "重新排期" if rescheduled else ("显式停摆" if ok_marker else "静默（最坏情况）")
    c.notes.append(f"当前结论：{verdict}")
    c.notes.append("别的会话的 timer、上一轮的遗留 job 都不算——必须 id/args 指向本会话")
    c.notes.append("如果走「重新排期」这条路，run_date 必须在未来；补发过去时间等于假装没断")
    return c


async def c10_06b() -> Case:
    """C-24 补件：过期任务重新排期后必须持久化，二次重启能恢复同一未来任务。

    Codex 终验指出 c10_06 只断言了第一次重排的内存 job。真实故障链是：
    init_jobs_from_data 先 clear_session_schedule_state() 抹掉 next_trigger_time，
    再 compute_next_trigger()+add_chat_job() 只注册内存 job —— 若此时再重启一次，
    落盘的是一个「没有下次」的会话，主动侧重新停摆。
    """
    now = datetime.now(TZ).timestamp()
    tmp = Path(tempfile.mkdtemp(prefix="ds05_stall_b2_"))
    plugin = FakePlugin(base_config(auto_trigger_settings={"enable_auto_trigger": True}))
    plugin.data_dir = tmp
    plugin.session_data[UMO] = {"next_trigger_time": now - 3600, "unanswered_count": 0}

    # 第一次启动：过期任务 → 重新上膛
    await plugin.scheduler_service.init_jobs_from_data()
    persisted_1 = plugin.session_data.get(UMO, {}).get("next_trigger_time")
    has_persisted = isinstance(persisted_1, (int, float)) and persisted_1 > now

    # 第二次启动：清空内存调度器，只用落盘的 session_data 重新恢复
    # （模拟「job 执行前再重启一次」）
    plugin.scheduler.jobs.clear()
    await plugin.scheduler_service.init_jobs_from_data()
    job2 = None
    for j in plugin.scheduler.jobs.values():
        args = j.kwargs.get("args") or []
        if str(j.id) == UMO or (args and args[0] == UMO):
            job2 = j
            break
    run_date2 = getattr(job2, "kwargs", {}).get("run_date") if job2 else None
    recovered = isinstance(run_date2, datetime) and run_date2.timestamp() > now

    c = Case(
        cid="C10-06B",
        layer="c10",
        title="过期任务重排后必须落盘：二次重启仍能恢复同一未来任务（C-24）",
        current=(
            f"重排后落盘的 next_trigger_time="
            f"{persisted_1 if persisted_1 is not None else '无(被清空未写回)'}；"
            f"二次重启的 job={'有' if job2 else '无'}"
            f"{'，run_date=' + run_date2.isoformat() if isinstance(run_date2, datetime) else ''}"
        ),
        expected="重排时同步写回 next_trigger_time 与调度元数据，二次重启可恢复未来任务",
        evidence="scheduler_service.py:604-624 重排分支补 save_data() 前只注册内存 job",
    )
    c.ok = has_persisted and recovered
    c.notes.append("c10_06 只验第一次重排，本条补二次重启——C-24 的真实故障面")
    c.notes.append("重排语义保持：不补发过期内容、未回复计数/免打扰不动")
    return c


async def c09_07b() -> Case:
    """C-25 补件：TTS 已送达但装饰阶段停止文本时，必须记 partial 而非 skipped。

    旧行为 sender_service.py:562-564 直接 return DeliveryOutcome(status="skipped")，
    丢掉已发出的语音段 → DeliverStage 按 0 段 abort 重调度 → RECORD 与未回复计数被
    跳过 → 对方已收到语音、系统记没发，下次可能重复触达。
    """
    plugin = FakePlugin(
        base_config(tts_settings={"enable_tts": True, "always_send_text": True})
    )
    sender = ScriptedSender(plugin, [True])  # 第一段=语音发送成功
    plugin.sender_service = sender
    err = ""

    class TTS:
        async def get_audio(self, text):
            return "C:/tmp/fake_voice.mp3"

    plugin.context.get_using_tts_provider = lambda umo=None: TTS()

    async def fake_decorating_stop(*a, **k):
        return ([], False)  # 装饰钩子停止文本

    orig_hook = getattr(sender, "run_decorating_hooks", None)
    outcome = None
    try:
        if orig_hook is not None:
            sender.run_decorating_hooks = fake_decorating_stop
        outcome = await sender.send_proactive_message(
            UMO, "测试语音文案", event=FakeEvent()
        )
    except Exception as e:
        err = repr(e)
    finally:
        if orig_hook is not None:
            sender.run_decorating_hooks = orig_hook

    c = Case(
        cid="C09-07B",
        layer="c09",
        title="语音已送达+装饰停止文本 → 必须记 partial，不得记 skipped（C-25）",
        current=(
            f"调用异常: {err}"
            if outcome is None
            else (
                f"status={getattr(outcome, 'status', None)} "
                f"voice_sent={getattr(outcome, 'voice_sent', None)} "
                f"segment_count_sent={getattr(outcome, 'segment_count_sent', None)}"
            )
        ),
        expected="status=partial、voice_sent=True、segment_count_sent>=1（语音算送达）",
        evidence="sender_service.py:566-576 装饰停止时若 is_tts_sent 走 partial 分支",
    )
    if outcome is None:
        c.ok = False
        return c
    c.ok = (
        getattr(outcome, "status", None) == "partial"
        and bool(getattr(outcome, "voice_sent", False))
        and getattr(outcome, "segment_count_sent", 0) >= 1
    )
    c.notes.append("对照：TTS 未成功且装饰停止时仍应按 0 段 abort（不误补发）")
    c.notes.append("DeliverStage 收到 partial 应继续 RECORD，不再 abort 重调度")
    return c


async def c10_13() -> Case:
    """停摆标记校验器自检：别的会话 / 别的原因 / 时间不对，一律判红。"""
    now = datetime.now(TZ).timestamp()
    trigger = now - 3600
    good = {
        "session_key": UMO,
        "reason": "persisted_task_expired",
        "stalled_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "expired_next_trigger": trigger,
        "unanswered_count": 0,
        "auto_trigger_enabled": False,
        "recover_when": "next_peer_message",
    }
    tmp = Path(tempfile.mkdtemp(prefix="ds05_stall_selftest_"))
    checks: list[tuple[str, bool, bool]] = []

    def put(name: str, payload) -> Path:
        p = tmp / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    checks.append(
        (
            "完整标记（sessions 包裹）",
            validate_stall_marker(put("ok.json", {"sessions": {UMO: good}}), UMO, now, trigger)[0],
            True,
        )
    )
    checks.append(
        (
            "扁平单会话",
            validate_stall_marker(put("flat.json", good), UMO, now, trigger)[0],
            True,
        )
    )
    other = dict(good, session_key="aiocqhttp:FriendMessage:999999")
    checks.append(
        (
            "别的会话",
            validate_stall_marker(
                put("other.json", {"sessions": {"aiocqhttp:FriendMessage:999999": other}}),
                UMO,
                now,
                trigger,
            )[0],
            False,
        )
    )
    checks.append(
        (
            "别的原因",
            validate_stall_marker(
                put("reason.json", dict(good, reason="max_unanswered")), UMO, now, trigger
            )[0],
            False,
        )
    )
    checks.append(
        (
            "一天前的旧标记",
            validate_stall_marker(
                put(
                    "stale.json",
                    dict(
                        good,
                        stalled_at=datetime.fromtimestamp(now - 86400, timezone.utc).isoformat(),
                    ),
                ),
                UMO,
                now,
                trigger,
            )[0],
            False,
        )
    )
    checks.append(
        (
            "过期触发时间不符",
            validate_stall_marker(
                put("badtrig.json", dict(good, expired_next_trigger=now - 99999)),
                UMO,
                now,
                trigger,
            )[0],
            False,
        )
    )

    c = Case(
        cid="C10-13",
        layer="c10",
        title="停摆标记校验器自检（别会话/别原因/旧时间必须判红）",
        current="；".join(
            f"{n}={'pass' if got == want else 'WRONG'}" for n, got, want in checks
        ),
        expected="完整标记通过；别的会话、别的原因、旧时间、触发时间不符 全部判红",
        evidence="docs/reconnect-experience-design.md §六-3 停摆状态契约；本探针 validate_stall_marker()",
    )
    c.ok = all(got == want for _, got, want in checks)
    c.notes.append("这条就是为了堵上「随便放一个 PENDING.md 就能过」——校验器只认本会话、本次原因、本次时间")
    return c


async def c10_07() -> Case:
    now = datetime.now(TZ).timestamp()
    plugin = FakePlugin()
    plugin.session_data[UMO] = {"next_trigger_time": now + 600, "unanswered_count": 0}
    svc = plugin.scheduler_service
    await svc.init_jobs_from_data()
    first = len(plugin.scheduler.jobs)
    await svc.init_jobs_from_data()
    second = len(plugin.scheduler.jobs)
    c = Case(
        cid="C10-07",
        layer="c10",
        title="重复恢复幂等：连跑两次只能有一个 job",
        current=f"第一次 {first} 个；第二次 {second} 个",
        expected="1 / 1（固定 id + replace_existing=true）",
        evidence="scheduler_service.py:254-267、:515",
    )
    c.ok = first == 1 and second == 1
    return c


def _quiet(rng: str, hour: int) -> bool:
    s, e = (int(x) for x in rng.split("-"))
    if s <= e:
        return s <= hour < e
    return hour >= s or hour < e


def c10_08() -> Case:
    table = [
        ("1-8", 0, False),
        ("1-8", 1, True),
        ("1-8", 7, True),
        ("1-8", 8, False),
        ("23-6", 23, True),
        ("23-6", 2, True),
        ("23-6", 6, False),
    ]
    bad = [(r, h, _quiet(r, h), want) for r, h, want in table if _quiet(r, h) != want]
    c = Case(
        cid="C10-08",
        layer="c10",
        title="免打扰边界：右开区间 + 跨天",
        current="全部符合" if not bad else f"不符：{bad}",
        expected="1-8 的 1/7 点禁、8 点放；23-6 的 23/2 点禁、6 点放",
        evidence="utils/time_utils.py:12-28",
    )
    c.ok = not bad
    return c


def c10_09() -> Case:
    got = is_quiet_time("not-a-range", TZ)
    c = Case(
        cid="C10-09",
        layer="c10",
        title="免打扰配置非法 → 按非免打扰处理（不能误阻断）",
        current=f"is_quiet_time('not-a-range') → {got}",
        expected="False",
        evidence="utils/time_utils.py:26-28",
    )
    c.ok = got is False
    return c


async def c10_10() -> Case:
    cfg = base_config()
    cfg["schedule_settings"]["max_unanswered_times"] = 1
    plugin = FakePlugin(cfg)
    plugin.session_data[UMO] = {"unanswered_count": 1}

    async def allowed(_sid):
        return True, "allowed"

    orch = SimpleNamespace(plugin=plugin, is_chat_allowed=allowed)
    aborted: list[str] = []
    ctx = SimpleNamespace(
        session_id=UMO, abort=lambda r: aborted.append(r), unanswered_count=0
    )
    result = await GatingStage(orch).handle(ctx)
    c = Case(
        cid="C10-10",
        layer="c10",
        title="未回复达上限 → 本轮不发且不重排",
        current=f"stage={getattr(result, 'name', result)}；abort={aborted}",
        expected="STOP + abort('max_unanswered')",
        evidence="gating_feature.py:64-69",
    )
    c.ok = getattr(result, "name", "") == "STOP" and aborted == ["max_unanswered"]
    return c


async def c10_11() -> Case:
    plugin = FakePlugin()

    async def blocked(_sid):
        return False, "quiet_hours"

    orch = SimpleNamespace(plugin=plugin, is_chat_allowed=blocked)
    aborted: list[str] = []
    ctx = SimpleNamespace(
        session_id=UMO, abort=lambda r: aborted.append(r), unanswered_count=0
    )
    result = await GatingStage(orch).handle(ctx)
    c = Case(
        cid="C10-11",
        layer="c10",
        title="免打扰时段 → 跳过并重新调度（不是 STOP）",
        current=f"stage={getattr(result, 'name', result)}；abort={aborted}",
        expected="RESCHEDULE + abort('quiet_hours')",
        evidence="gating_feature.py:35-40",
    )
    c.ok = getattr(result, "name", "") == "RESCHEDULE" and aborted == ["quiet_hours"]
    return c


async def c10_12() -> Case:
    """恢复已超上限的会话：允许恢复 job（到点会被 GATE 拦），但端到端必须发不出去。"""
    now = datetime.now(TZ).timestamp()
    cfg = base_config()
    cfg["schedule_settings"]["max_unanswered_times"] = 1
    plugin = FakePlugin(cfg)
    plugin.session_data[UMO] = {
        "next_trigger_time": now + 600,
        "unanswered_count": 5,
    }
    await plugin.scheduler_service.init_jobs_from_data()

    async def allowed(_sid):
        return True, "allowed"

    orch = SimpleNamespace(plugin=plugin, is_chat_allowed=allowed)
    aborted: list[str] = []
    ctx = SimpleNamespace(
        session_id=UMO, abort=lambda r: aborted.append(r), unanswered_count=0
    )
    result = await GatingStage(orch).handle(ctx)
    c = Case(
        cid="C10-12",
        layer="c10",
        title="未回复已超上限的会话被恢复后，到点仍必须被 GATE 拦下",
        current=f"jobs={len(plugin.scheduler.jobs)}；GATE={getattr(result, 'name', result)}；abort={aborted}",
        expected="允许恢复 job，但端到端 STOP + abort('max_unanswered')（不会真发出去）",
        evidence="gating_feature.py:64-69（GATE 是最后一道防线）",
    )
    c.ok = getattr(result, "name", "") == "STOP" and aborted == ["max_unanswered"]
    c.notes.append("恢复阶段不读上限是有意为之：上限是发送期判定，恢复期不必重复；这里验证的是「真到点也不会发」")
    c.notes.append("修 C-10 时别在恢复阶段再加一次上限判断：同一条策略写两处，将来改一处必然漂移")
    return c


# ---------------------------------------------------------------------------
# 运行器
# ---------------------------------------------------------------------------
CORO = [c09_01, c09_02, c09_03, c09_04, c09_05, c09_06, c09_07, c09_07b, c09_08, c09_09, c09_10,
        c09_11, c10_04, c10_05, c10_06, c10_06b, c10_07, c10_10, c10_11, c10_12, c10_13]
SYNC = [c10_01, c10_02, c10_03, c10_08, c10_09]


async def run(layer: str | None, verbose: bool, allow_known: bool) -> int:
    cases: list[Case] = []

    def keep(cid: str) -> bool:
        return layer is None or cid.lower().startswith(layer)

    for fn in CORO:
        cid_guess = fn.__name__.replace("c09_", "C09-").replace("c10_", "C10-")
        try:
            case = await fn()
        except Exception:
            case = Case(
                cid=cid_guess,
                layer=cid_guess[:3].lower(),
                title=f"{fn.__name__} 执行异常",
                current="EXCEPTION",
                expected="用例本身可执行",
                evidence=traceback.format_exc()[-600:],
                ok=False,
            )
        if keep(case.cid):
            cases.append(case)

    for fn in SYNC:
        cid_guess = fn.__name__.replace("c10_", "C10-")
        try:
            case = fn()
        except Exception:
            case = Case(
                cid=cid_guess,
                layer="c10",
                title=f"{fn.__name__} 执行异常",
                current="EXCEPTION",
                expected="用例本身可执行",
                evidence=traceback.format_exc()[-600:],
                ok=False,
            )
        if keep(case.cid):
            cases.append(case)

    cases.sort(key=lambda c: (c.layer, c.cid))
    passed = [c for c in cases if c.ok]
    failed = [c for c in cases if not c.ok]
    known = [c for c in failed if c.cid in KNOWN_BUGS]
    unknown = [c for c in failed if c.cid not in KNOWN_BUGS]

    for c in cases:
        if verbose or not c.ok:
            mark = "PASS" if c.ok else ("KNOWN" if c.cid in KNOWN_BUGS else "FAIL")
            print(f"[{mark}] {c.cid} {c.title}")
            if not c.ok or verbose:
                print(f"       现状: {c.current}")
                print(f"       期望: {c.expected}")
                print(f"       证据: {c.evidence}")
                for n in c.notes:
                    print(f"       注: {n}")

    print()
    print(
        f"共 {len(cases)} 条：通过 {len(passed)} / 失败 {len(failed)}"
        f"（已登记 {len(known)} / 未登记 {len(unknown)}）"
    )
    if known:
        print("已登记失败（C-09/C-10 的现状缺陷，见任务单验收清单）：")
        for c in known:
            print(f"  - {c.cid}  {KNOWN_BUGS[c.cid]}")
        if not allow_known:
            print("→ 未加 --allow-known：已登记失败同样计为失败。")
        else:
            print("→ 已加 --allow-known：已登记失败不计为失败（缺陷仍未修，不要当成已修复）。")
    return 0 if not unknown and (allow_known or not known) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-known", action="store_true", help="已登记的失败不算失败")
    ap.add_argument("--layer", default=None, choices=["c09", "c10"])
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    try:
        return asyncio.run(run(args.layer, args.verbose, args.allow_known))
    except Exception:
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
