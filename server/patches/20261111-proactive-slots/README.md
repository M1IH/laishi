# 主动消息时段化 + 放开极短问候（2026-11-11）

## 为什么

原来的排期是「距上次触发随机 25~55 分钟一条」，一天能发十几条，时间散落在任何非免打扰分钟上。
OTTO 要的是**四个固定时段**：上午两条（9 点、11 点）、下午两条（14 点、17 点），每个时段前后随机半小时。

同时原来提示词写「通常十个字上下，最多二十来字」，压得太死，出不来「在干嘛呢」这种四五个字的直接问候。

## 改了什么

五处，全部幂等（重复执行输出 `already`）。

### 1. `utils/time_utils.py` —— 新增时段计算

在文件末尾追加：

| 函数 | 作用 |
| --- | --- |
| `parse_slot_list(slots_str) -> list[int]` | `"9,11,14,17"` → `[540, 660, 840, 1020]`，升序去重，非法项跳过 |
| `_window_bounds(slot, jitter) -> (start, end)` | 窗口边界，夹到 `0..1440` |
| `next_slot_trigger(slots_str, jitter_minutes, now_ts, tz, quiet_hours_str="") -> float\|None` | 从 `now_ts` 起找下一个时段窗口内的随机时刻 |
| `next_day_slot_trigger(...)` | 从次日 00:00 起算，用于「今天不再发」后重排 |

`next_slot_trigger` 的关键判断：

```python
if int(win_start.timestamp()) <= int(now_ts):
    continue
```

**已经开始的窗口整体跳过。** 不这样写的话：09:02 发完一条，算下一次时 09:00–09:30 窗口起点已经过去，随机结果仍可能落在 09:05，同一个时段发两条。宁可漏时段，不重复发。

落在免打扰段的候选时刻会 `+= next_active_offset(...) * 60` 推后，复用已有的 `quiet_hours`（`"0-8:30,12-13:30,18-24"`）。注意 9 点窗口 8:30 起，正好贴着上午免打扰段的尾巴。

### 2. `core/services/scheduler_service.py` —— 排期入口接上时段

在 `compute_next_trigger` 前插入三个方法：

- `_slot_common(schedule_conf)` → 读 `slots_enable` / `slots` / `slot_jitter_minutes`，未启用返回 `None`
- `_slot_target(schedule_conf, from_ts=None)`
- `_next_day_slot_target(schedule_conf)`

`compute_next_trigger` 开头：

```python
slot_target = self._slot_target(schedule_conf)
if slot_target is not None:
    return (run_date, now_ts, gap, gap, gap, slot_target)
```

**返回的仍是六元组**，所以四个调用点（`schedule_next_chat_and_save` L807、`init_jobs_from_data` L710、`handle_auto_trigger_callback` L961、`flow_orchestrator.finalize_and_reschedule` L277）一行都不用改。`compute_next_day_trigger` 同理。

时段模式和随机间隔模式互斥：`slots_enable=true` 时走时段，否则走原来的 `min/max_interval_minutes`。

### 3. `_conf_schema.json` —— `schedule_settings` 新增三项

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `slots_enable` | bool | `false` | 开了才走固定时段 |
| `slots` | string | `"9,11,14,17"` | 逗号分隔的小时（也接受 `9:30`） |
| `slot_jitter_minutes` | int | `30` | 每个时段前后各随机多少分钟 |

### 4. 线上配置

`friend_settings.schedule_settings` 写入 `slots_enable: true`、`slots: "9,11,14,17"`、`slot_jitter_minutes: 30`。

### 5. `friend_settings.proactive_prompt` —— 放开极短问候

```diff
- 只发一条短消息，通常十个字上下，最多二十来字；能一句话说完就不要再补。
+ 只发一条短消息，最多二十来字；多数时候四到八个字就够，像「在干嘛呢」这样只问一句也可以，
+ 不必每次都展开；能一句话说完就不要再补。
```

432 → **461 字**。原来的「通常十个字上下」是下限式约束，模型会往十个字凑；改成「四到八个字就够」并给了具体例子，才可能出「在干嘛呢」。

## 部署

```bash
scp .tmp-slot/patch_slots.py root@<server>:/tmp/
ssh root@<server> "docker cp /tmp/patch_slots.py astrbot:/tmp/ && docker exec astrbot python3 /tmp/patch_slots.py \
  /AstrBot/data/plugins/astrbot_plugin_proactive_chat \
  /AstrBot/data/config/astrbot_plugin_proactive_chat_config.json"
ssh root@<server> "docker restart astrbot"
```

脚本自带 `--dry`，且 apply 后会自动跑 7 组单测、回读配置。

## 验证

```bash
ssh root@<server> "docker cp /tmp/verify_slots.py astrbot:/tmp/ && docker exec astrbot python3 /tmp/verify_slots.py"
```

线上实测输出：

```
slots_enable: True
slots: 9,11,14,17
jitter: 30
prompt_len: 461
prompt_has_short: True
has_next_slot_trigger: True
has_slot_target: True

--- 从当前时刻起连算 5 次 ---
   2026-11-12 09:16:26
   2026-11-12 10:36:59
   2026-11-12 13:40:04
   2026-11-12 17:24:36
   2026-11-13 08:46:29
```

四个时间分别落在 9/11/14/17 四个窗口，第五条跨到次日。

7 组单测覆盖：四次触发分属四个窗口、窗口单调递增、已开始窗口跳过、当天窗口耗尽顺延次日、次日复活、空配置返回 `None`、抖动为 0 时正好整点。

## 坑

1. **改完 `session_data.json` 或插件代码必须 `docker restart astrbot`**。内存里的 job 不会自己按新配置重算。
2. **重启后不会立刻按新时段重排**。`init_jobs_from_data` 只恢复已有 `next_trigger_time`；`3529676294` 那条 `count=3` 已经是当天上限，要等 11-12 08:30 那条发出去、`finalize_and_reschedule` 走一遍，才会用新时段算下一次。
3. **`scp` 可以一次传多个远程源**，但 `ssh '...'` 里 `$` 变量会被本地 shell 吞掉，四个 `docker cp` 要逐个写死文件名。
4. **`platform_message_history.created_at` 是 UTC**，日志是本地时间，差 8 小时，别对错。
5. 配置/schema 都有 **BOM**，必须 `utf-8-sig` 读写，否则 AstrBot 解析失败。

## 回滚

把 `slots_enable` 改成 `false` 即刻回到随机 25~55 分钟模式，代码不用动。提示词回滚用同目录的 `.bak.slots-<时间戳>`。

## 产物

- `patch_slots.py` —— 五处改动 + 7 组单测
- `verify_slots.py` —— 线上回读配置、连算五次、打印 `session_data`
- 线上备份：`time_utils.py.bak.slots-*`、`scheduler_service.py.bak.slots-*`、`_conf_schema.json.bak.slots-*`、`astrbot_plugin_proactive_chat_config.json.bak.slots-*`
