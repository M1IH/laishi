# 分时段主动消息节奏（2026-10-27）

## 一、需求

OTTO：让 Miruku 在 **上午 8:30–12:00** 与 **下午 13:30–18:00** 主动发消息频率更高，
**其余时间完全静默**（0:00–8:30 / 12:00–13:30 / 18:00–24:00）。

## 二、为什么不能只改配置

插件自带的 `utils/time_utils.py` 里 `is_quiet_time()` 的解析是：

```python
start_str, end_str = quiet_hours_str.split("-", 1)
start_hour = int(start_str)
end_hour = int(end_str)
```

三个限制叠在一起决定了它表达不了这次的需求：

1. **只切两段** ⇒ 只能有一个区间，写不出三段静默；
2. **`int()`** ⇒ 端点必须是整点，`8:30` 直接 `ValueError`；
3. **`except (ValueError, TypeError): return False`** ⇒ 解析失败按"非免打扰"处理。

**第 3 条最危险**：写 `0-8:30,12-13:30,18-24` 不会报错、不会静默，
而是**静默彻底失效**（全天可发）。比"不支持"更糟，因为看不出异常。

## 三、改动（两处，都在插件内）

### 3.1 新解析器 `utils/time_utils.py`

- 新增 `_parse_hhmm()`：认 `"8"` / `"08"` / `"8:30"` / `"24"`（24 = 当天末尾，1440 分）
- 新增 `parse_quiet_spans()`：按逗号切多段，返回 `[(开始分钟, 结束分钟), ...]`；
  **单段非法只跳该段**，不影响其余段
- `is_quiet_minute(minute_of_day, quiet_hours_str)`：新判定入口
- `is_quiet_time()` 改为调用它 ⇒ **对外行为与旧版在单段整点写法下完全一致**
  （`"1-7"` / `"23-6"` 语义不变），旧配置不会失效
- 新增 `next_active_offset(quiet_hours_str, now_minute)`：
  从某分钟起向前找，返回**多少分钟后进入下一个可发送时刻**；
  全天静默时返回 `None`

### 3.2 排期跳过静默段 `core/services/scheduler_service.py`

`compute_next_trigger()` 在算出随机时刻后追加一段：

```python
quiet_hours_str = schedule_conf.get("quiet_hours", "") or ""
if quiet_hours_str:
    candidate = datetime.fromtimestamp(next_trigger_time, tz=plugin.timezone)
    minute_of_day = candidate.hour * 60 + candidate.minute
    offset = next_active_offset(quiet_hours_str, minute_of_day)
    if offset:
        next_trigger_time += offset * 60
```

**为什么值得改**：不改也能工作——排到静默时刻时
`gating_feature.py:32-50` 会记「当前为免打扰时段，跳过并重新调度喵」再随机一次。
但那样每次撞静默都要白跑一轮 LLM 排期逻辑，而且"随机→撞墙→再随机"让
分布不可预测。改了之后排期**一次就算准**，落点全在活跃时段内。

## 四、配置值

| 项 | 改前 | 改后 |
|---|---|---|
| `schedule_settings.min_interval_minutes` | 30 | **25** |
| `schedule_settings.max_interval_minutes` | 75 | **55** |
| `schedule_settings.quiet_hours` | `"1-8"` | **`"0-8:30,12-13:30,18-24"`** |
| `auto_trigger_settings.auto_trigger_after_minutes` | 60 | 60（不动） |
| `schedule_settings.max_unanswered_times` | 0 | 0（不动） |

**间隔为什么收紧到 25–55**：原来 30–75（均 52.5）是按全天摊的。
现在可发时间只剩 8.5 小时（上午 210 分 + 下午 270 分 = 480 分），
若沿用旧间隔，一天只有 480/52.5 ≈ 9 条，且上午仅约 4 条——
"更高"就感觉不出来。收到 25–55（均 40）后，上午约 5 条、下午约 7 条。

## 五、离线验证

### 5.1 静默判定（1=静默，0=可发）

```
00:00:1  08:00:1  08:30:0  08:50:0  11:59:0  12:00:1
13:00:1  13:30:0  17:59:0  18:00:1  20:00:1  23:59:1
```

四个边界 `08:30 / 12:00 / 13:30 / 18:00` 全部落在可发侧，符合"前闭后开"。

### 5.2 从静默时刻跳转

| 起点 | 跳转 |
|---|---|
| 00:00 | +510 分 → 08:30 |
| 12:00 | +90 分 → 13:30 |
| 13:00 | +30 分 → 13:30 |
| 18:00 | +870 分 → 次日 08:30 |
| 23:59 | +511 分 → 次日 08:30 |

### 5.3 排期模拟（25–55，从 08:30 起）

```
09:02  09:45  10:27  10:56  11:32  | 13:30(跳过午休 64 分)
14:14  14:54  15:39  16:22  16:49  17:33  17:58
```

- 上午 5 条 + 下午 7 条 = **13 条/天**
- 12:00–13:30 之间零排期，18:00 后零排期
- 200 次蒙特卡洛：一天 **最少 10、最多 15、中位 12、平均 12.0** 条
- **从不同起点（含 00:00 / 12:00 / 17:50 / 23:00 等 12 个边界）各排 3 次，
  落入静默段的次数 = 0**

## 六、部署

脚本：`server/deploy-proactive-hours.sh`（服务器上 `bash /root/deploy-proactive-hours.sh`）

六步：① 检查三个路径 ② 备份并换 `time_utils.py`（base64 内嵌，已验证可解码可编译、
与本地源字节一致）③ 给 `scheduler_service.py` 打补丁（**锚点不唯一或已改就中止**，
改完 `py_compile` 自检，失败自动回滚）④ 写配置 ⑤ 重启 astrbot ⑥ 验证 + 看排期。

- 补丁段已在本机拿**还原出的原始文件**试跑，产物与本地已改版本**逐字节一致**，
  且 `py_compile` 通过。
- `bash -n` 语法检查通过。
- 回滚：把两个 `.bak.<时间戳>` 复制回去 + `quiet_hours` 改回 `"1-8"` + 重启。

## 七、遗留

1. **插件是第三方的**：`astrbot_plugin_proactive_chat` 升级会覆盖这两处改动。
   已在脚本里用"锚点不唯一就中止"兜住（升级后跑脚本会明确报错而不是静默打坏），
   但真升级了需要人工确认改法仍适用。
2. **"上午"只到 12:00**：他如果上午有课到 12:10，那 10 分钟是静默的。
   要挪直接改 `quiet_hours` 里的 `12-13:30`。
3. **未验证运行时行为**：本轮只有离线验证（解析器 + 排期模拟 + 补丁可应用性）。
   部署后应看一次 `/api/jobs` 的 `next_run_time` 是否落在活跃时段内。

**未改** `prompts/`、`persona/`、`knowledge/`，未改运行配置（脚本未执行）。
