# proactive_chat「每日重置未回复计数」补丁（2026-11-06）

> 这些文件是**线上实际运行版本 + 本次改造**，基线从容器
> `/AstrBot/data/plugins/astrbot_plugin_proactive_chat/` 用 `docker exec tar` 导出。
> **不是可直接覆盖的仓库源码**——插件本体在上游，本目录只保存我们改过的文件。

## 背景与问题

### 现象

主动消息的「最大未回复次数」原本是**永久累计**的：

```
发 1 条没人理 → unanswered_count=1
发 2 条没人理 → unanswered_count=2
发 3 条没人理 → unanswered_count=3  ← 达到 max_unanswered_times
第 4 次触发   → GATE 拦住 → 永久不再发送
```

一旦撞上限，**只有对方主动发消息才会解冻**（`event_handlers.py` 在收到用户消息时把计数清零）。
对方一直不说话，机器人就一直不主动开口——这正是「她不发了」的实际观感。

线上 `session_data.json` 在升级前两个会话都是 `unanswered_count=3`：
来世那条自 2026-11-04 起再没排过任何任务。

### 期望语义

「最大未回复次数」应当是**每天**的额度，不是终身额度：

```
今天 08:30 起发 3 条没人理 → 今天不再发
次日 08:30 免打扰结束后     → 额度重置，重新开始
```

`max_unanswered_times=3` 的语义从「累计 3 次就永久停」变成「每天最多打扰 3 次」。

## 改动文件（6 个）

| 文件 | 改动 |
|---|---|
| `utils/time_utils.py` | 新增 `next_day_active_offset()`、`local_day_key()` |
| `core/features/gating_feature.py` | GATE 里跨天清零；达上限的日志改为「今天不再发送」 |
| `core/pipeline/flow_orchestrator.py` | `_on_gate_stop` 真正的空实现 → 达上限时排到次日；`finalize_and_reschedule` 写 `unanswered_date` |
| `core/services/scheduler_service.py` | 新增 `reset_daily_unanswered()`、`compute_next_day_trigger()`、`schedule_next_day_and_save()`；启动恢复路径也做跨天清零 |
| `core/adapters/event_handlers.py` | 用户回复清零计数时同步刷新 `unanswered_date` |
| `_conf_schema.json` | 新增 `unanswered_reset_daily`（bool，默认 `true`）开关 + 文案 |

## 关键改动锚点

### utils/time_utils.py

```python
def next_day_active_offset(quiet_hours_str: str, now_minute: int) -> int | None:
    """从 now_minute 起多少分钟后到「次日第一个可发送时刻」。

    先跨过当天剩余分钟，再叠加次日 0 点起的 first-active 偏移。
    全天免打扰返回 None。
    """
```

`local_day_key(tz)` 返回 `YYYY-MM-DD`，作为「计数属于哪一天」的键。

### core/features/gating_feature.py（`GatingStage.handle`）

在 `data_lock` 内、比较上限之前插入跨天判定：

```python
reset_daily = bool(schedule_conf.get("unanswered_reset_daily", True))
async with plugin.data_lock:
    session_info = plugin.session_data.setdefault(session_id, {})
    changed = False
    if reset_daily:
        if plugin.scheduler_service.reset_daily_unanswered(session_id, session_config):
            changed = True
        today_key = local_day_key(plugin.timezone)
        if str(session_info.get("unanswered_date", "") or "") != today_key:
            session_info["unanswered_date"] = today_key
            changed = True
    if changed:
        await plugin.storage_service.save_data()
    ...
```

`save_data()` 只在真有变更时调用一次，避免锁内重复落盘。

### core/services/scheduler_service.py

三个新方法（插在 `purge_related_jobs` 之前）：

- `reset_daily_unanswered(session_id, session_config=None) -> bool`
  跨天则把 `unanswered_count` 归零并写 `unanswered_date=今天`，返回是否变更（调用方负责 `save_data`）。
  **`if not counted_date: return False`**——旧数据（只有计数没有日期）当作「今天已经发过」，
  升级当天不补发超额消息，次日自然按新语义走。
- `compute_next_day_trigger(schedule_conf) -> float | None`
  `now + next_day_active_offset(...) * 60`；免打扰覆盖全天时返回 `None`。
- `schedule_next_day_and_save(session_id, session_config=None) -> bool`
  锁内写 `next_trigger_time` / `last_scheduled_at` 并落盘，出锁后 `add_chat_job()`。

两处调用点补跨天清零（否则重启后仍被昨天的旧上限挡住）：

- `setup_auto_trigger_for_session_config()`：读 `unanswered_count` 前先 `reset_daily_unanswered()`
- `init_jobs_from_data()`：`没有 next_trigger_time` 的早退分支里也执行一次

### core/pipeline/flow_orchestrator.py

`_on_gate_stop` 原为 `return None`（**这就是永久停发的根源**）：

```python
if getattr(ctx, "abort_reason", None) != "max_unanswered":
    return None
...
if not bool(schedule_conf.get("unanswered_reset_daily", True)):
    return None          # 关掉开关 → 保持旧行为（永久停发）
scheduled = await plugin.scheduler_service.schedule_next_day_and_save(ctx.session_id, session_config)
if not scheduled:
    logger.warning("... 无法算出次日可发送时刻（免打扰覆盖全天？），未排期喵。")
```

`finalize_and_reschedule()` 计数写回处新增：

```python
session_payload_for_count["unanswered_date"] = local_day_key(plugin.timezone)
```

### core/adapters/event_handlers.py

用户回消息时（L332 附近）除了 `["unanswered_count"] = 0`，同时写
`["unanswered_date"] = local_day_key(self.plugin.timezone)`——
否则跨天逻辑会把今天的发送记录当成昨天的，当天又清零一次。

### _conf_schema.json

`friend_settings` 与 `group_settings` 的 `schedule_settings.items` 各加一项：

```json
"unanswered_reset_daily": {
  "description": "每日重置未回复计数",
  "type": "bool",
  "default": true,
  "hint": "开启后「最大未回复次数」按天计算：当天发满 N 次仍未获回复就停到第二天，次日免打扰结束后重新开始，而不是一直停到对方回复"
}
```

同时改写 `max_unanswered_times.hint`，把「累计 N 次暂停」说清楚是「同一天内」。

## 验证

`python -m py_compile` 5 个 py 全过。

本地仿真 `来世-github-publish/sim_daily_reset.py`（构造最小插件替身，跑真实改造代码）：

| 场景 | 结果 |
|---|---|
| 昨天发满 3 次，今天 GATE 放行 | PASS（计数清零、日期更新） |
| 今天发满 3 次，GATE 停发 | PASS（`STOP` + `abort_reason=max_unanswered`，计数保持 3 不误清） |
| 停发后 `_on_gate_stop` 排期 | PASS（排到次日 08:30，落在免打扰之外，任务已注册） |
| 关掉 `unanswered_reset_daily` | PASS（不写 `next_trigger_time`，保持永久停发） |
| 旧数据只有计数无日期 | PASS（当天仍 STOP，日期补为今天，明天恢复） |
| 当天计数 1 | PASS（放行，不清零） |
| `next_day_active_offset` 边界 | PASS（02:00 / 09:00 / 20:00 都到次日 08:30；无免打扰到次日 0 点；`0-24` 返回 None） |

## 部署

```bash
# 备份
docker exec -i astrbot tar -cf /tmp/pc-bk.tar -C /AstrBot/data/plugins astrbot_plugin_proactive_chat
docker cp astrbot:/tmp/pc-bk.tar /opt/miruku/backups/pc-$(date +%Y%m%d-%H%M%S).tar

# 覆盖（相对路径拼到 /AstrBot/data/plugins/astrbot_plugin_proactive_chat/）
docker cp utils/time_utils.py astrbot:/AstrBot/data/plugins/astrbot_plugin_proactive_chat/utils/time_utils.py
docker cp core/features/gating_feature.py astrbot:/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/features/gating_feature.py
docker cp core/pipeline/flow_orchestrator.py astrbot:/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/pipeline/flow_orchestrator.py
docker cp core/services/scheduler_service.py astrbot:/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/services/scheduler_service.py
docker cp core/adapters/event_handlers.py astrbot:/AstrBot/data/plugins/astrbot_plugin_proactive_chat/core/adapters/event_handlers.py
docker cp _conf_schema.json astrbot:/AstrBot/data/plugins/astrbot_plugin_proactive_chat/_conf_schema.json

# 语法校验 + 重启
docker exec -i astrbot sh -c 'cd /AstrBot/data/plugins/astrbot_plugin_proactive_chat && python3 -m py_compile utils/time_utils.py core/features/gating_feature.py core/pipeline/flow_orchestrator.py core/services/scheduler_service.py core/adapters/event_handlers.py'
docker restart astrbot
```

## 升级后要做的数据修正

线上 `session_data.json` 里两个会话都停在 `unanswered_count=3` 且**没有 `unanswered_date`**。
按上面的设计，这类旧数据在升级当天会被当作「今天已发过」（不清零、不排期），
要到次日才自然恢复。若希望**升级当天就恢复**，部署后手动把两个会话的计数清零：

```bash
docker exec -i astrbot python3 - <<'PY'
import json, pathlib
p = pathlib.Path('/AstrBot/data/plugin_data/astrbot_plugin_proactive_chat/session_data.json')
data = json.loads(p.read_text(encoding='utf-8'))
for sid, info in data.items():
    if isinstance(info, dict) and info.get('unanswered_count'):
        info['unanswered_count'] = 0
        info.pop('next_trigger_time', None)
        info.pop('last_scheduled_at', None)
        print('reset', sid)
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
PY
docker restart astrbot
```

重启后日志里应出现 `已成功从文件恢复任务喵` 或 `满足条件，自动触发任务已创建喵`。

## 坑

- `docker exec` 必须带 `-i`，否则 heredoc 被静默丢弃
- `save_data()` 必须显式 await：插件用的是自定义 `SessionStore`，不是 aiofiles 自动刷盘
- `_on_gate_stop` 里不能再 `return None` 就完事——它是**唯一**的 STOP 回调，
  任何「达上限后还想有后续动作」的逻辑都必须写在这里
- 时间全部用插件时区 `plugin.timezone`，不要用服务器本地时区
- 仿真脚本里 `next_day_active_offset` 的语义是「先跨过当天、再到次日首个可发送分钟」，
  所以从 02:00 出发是 1830 分钟（到次日 08:30），不是 390 分钟

## 与原版行为对照

| 场景 | 改造前 | 改造后 |
|---|---|---|
| 当天发满 3 次无人回复 | 永久停发，直到对方主动说话 | 停到次日 08:30 自动恢复 |
| 昨天发满、今天重启 | 仍被旧计数挡住，不排期 | 跨天清零，正常排期 |
| 对方一直不回 | 越攒越多，最后彻底死掉 | 每天最多 3 次，永不静默 |
| `unanswered_reset_daily=false` | — | 退回原版永久停发语义 |
