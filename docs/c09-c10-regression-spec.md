# C-09 / C-10 离线回归规格（DS-05）

> 交付物：`docs/c09-c10-regression-spec.md` + `data/probe_c09_c10.py`。
> 覆盖两件 P0：**C-09 主动消息部分送达被记成整条成功**、**C-10 停机跨过 `next_trigger+60s` 后静默停摆**。
> 探针直接调用生产代码（不是复制一份逻辑），只注入假平台／假调度器／假对话管理器；不启动 AstrBot、不碰生产数据、不发 QQ。

---

## 一、一句话结论

**现状下 C-09 全线不成立、C-10 有一半不成立，且都是「调用方只能看到一个布尔或一行日志」这一类问题**：24 条用例通过 14 条、失败 10 条，失败已全部登记为 `KNOWN_BUGS`；默认模式**退出码 1**（失败不会被伪装成通过），`--allow-known` 才退 0。

初验补件（2026-10-23）：C09-09 / C10-05 / C10-06 原来把「文件存在」当通过条件，`touch` 一个空文件就能绿。现已改成**状态必须可判定**——点名本会话、本次过期、时间对得上、原因对得上，并各加一条校验器自检（C09-11 / C10-13）堵住「旧文件蒙混」。

修完之后把 `KNOWN_BUGS` 里对应 key 删掉，默认模式必须自己退 0 —— 这就是验收门槛。

---

## 二、怎么跑

```bash
cd C:/Users/OTTO/Desktop/来世
export PYTHONIOENCODING=utf-8
PY="C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe"

"$PY" data/probe_c09_c10.py                 # 全跑；有未登记失败 → 退出码 1
"$PY" data/probe_c09_c10.py --allow-known   # 已登记失败不算失败 → 退出码 0
"$PY" data/probe_c09_c10.py --layer c09     # 只跑 C-09 十一条
"$PY" data/probe_c09_c10.py --verbose       # 连通过的一起打印
```

退出码：`0` 全过（或 `--allow-known` 下只剩已登记失败）；`1` 有未登记失败；`2` 环境错误（导入失败）。

> **不要用 `| tail` 取退出码**：那是 `tail` 的退出码。要么直接跑，要么 `"$PY" ... >/dev/null 2>&1; echo $?`。

隔离性：所有 session 数据在内存字典里；`FakeStorage.save_data()` 是空实现，**不写 `session_data.json`**；`FakeScheduler` 不创建真实 job；`ScriptedSender` 覆写 `send_chain`，不经过任何平台。唯一的磁盘访问是「查文件在不在」（`story_state.json`、`PENDING.md`），只读。

---

## 三、覆盖矩阵（任务单要求 → 用例）

| 任务单要求 | 用例 |
| --- | --- |
| C-09: 0/N 段被平台接受 | C09-01 |
| C-09: 1/N 段被接受（本体） | C09-02 |
| C-09: N/N 段全部接受 | C09-05 |
| C-09: 首段失败 / 首段成功 | C09-04（首段失败）／C09-02、C09-05（成功）|
| C-09: 未开分段的单条基线 | C09-03 |
| C-09: TTS 与文本混合 | C09-06 |
| C-09: 历史写入的期望 | C09-07（段数落库）、C09-08（计数 +1 不能被改坏）|
| C-09: 七日窗口 | C09-09（实现后真跑两分支）、C09-11（状态校验器自检）|
| C-09: DeliverStage 走向（护栏） | C09-10 |
| C-10: 正常到点／未到期仍可恢复 | C10-01、C10-02（60s 边界）|
| C-10: 停机跨 `next_trigger+60s` | C10-04 |
| C-10: 重启时 `enable_auto_trigger` 两种值 | C10-05（false）、C10-06（true）、C10-13（标记校验器自检）|
| C-10: 重复恢复幂等 | C10-07 |
| C-10: 安静时段 | C10-08、C10-09、C10-11 |
| C-10: 未回复上限 | C10-10、C10-12 |
| C-10: 脏数据/禁用（安全侧） | C10-03 |

---

## 四、C-09 样例明细

被测：`core/services/sender_service.py::send_proactive_message`、`core/features/deliver/split_delivery.py::DeliverStage`、`core/pipeline/flow_orchestrator.py::finalize_and_reschedule`、`core/features/record/history_writer.py::RecordStage`。

### C09-01 0/3 段被平台接受 —— KNOWN

- **现状**：`send_proactive_message` 返回 `False`（bool）。实际尝试 3 段、平台接受 0 段。调用方拿到的假与「配置缺失」「平台不可用」完全同形。
- **期望**：`status == "attempted"`、`segment_count_sent == 0`、`segment_count_planned == 3`。
- **源码证据**：`sender_service.py:519` `any_sent = is_tts_sent`；`:599-611` `if not any_sent: return False`。
- **修复后断言**：`status_of(res) == "attempted"`（探针此刻断言的正是这条）。

### C09-02 1/3 段被接受 —— KNOWN（C-09 本体）

- **现状**：返回 `True`。3 段里只有 1 段出去，但调用方看到的是「成功」。
- **期望**：`status == "partial"`、`segment_count_sent == 1`、`segment_count_planned == 3`。
- **源码证据**：`sender_service.py:555-567` 每段成功只 `any_sent = True`、**从不记失败段**；`:599-611` 有任一成功即 `return True`。
- **修复后断言**：`status_of(res) == "partial" and count_of(res,"segment_count_sent") == 1 and count_of(res,"segment_count_planned") == 3`。
- **后果链**：`split_delivery.py:31` 只判 `is True` → `CONTINUE` → `history_writer.py:29` 无条件 `finalize_and_reschedule` → 历史写全文 + 计数 +1 + 窗口写入。**平台只有 1 个气泡，档案里有完整三段。**

### C09-03 未开分段、单条送出（基线） —— KNOWN

- **现状**：返回 `True`，`send_chain` 调用 1 次。
- **期望**：`status == "all_segments_accepted"`、`sent == 1`、`planned == 1`。
- **源码证据**：`sender_service.py:549-575` 非分段分支只调一次 `send_chain`，与分段路径共用同一个布尔出口。
- **修复后断言**：`status_of(res) == "all_segments_accepted"`。
- **注**：这条是「基线也必须带段数」，否则修好后审计仍分不清「单条成功」与「三段折叠成一条」。

### C09-04 首段失败、后两段成功 —— KNOWN

- **现状**：返回 `True`，发送序列 `['一\n','二\n','三']`，但不记录**哪段**失败。
- **期望**：`status == "partial"`、`sent == 2`、`planned == 3`，并能指出失败的是第 1 段。
- **源码证据**：`sender_service.py:555-567` 只有 `any_sent` 累加，没有 `fail_segments`。
- **修复后断言**：`status_of(res)=="partial" and count_of(res,"segment_count_sent")==2`；后续若要「续段」，还需要失败段索引。

### C09-05 N/N 段全部接受 —— KNOWN

- **现状**：返回 `True`。
- **期望**：`status == "all_segments_accepted"`、`sent == 3`、`planned == 3`。
- **源码证据**：`sender_service.py:599-611` 出口只有 bool。
- **修复后断言**：`status_of(res)=="all_segments_accepted" and count_of(res,"segment_count_sent")==3`。

### C09-06 TTS 已发、文本段全失败 —— KNOWN

- **现状**：返回 `True`（`send_chain` 调用 3 次：1 段语音成功 + 2 段文本失败）。
- **期望**：`status == "partial"` 且 `voice_sent is True`。
- **源码证据**：`sender_service.py:519` `any_sent = is_tts_sent` —— **语音成功即算整条成功**。
- **修复后断言**：`status_of(res)=="partial" and count_of(res,"voice_sent") is True`。
- **注**：来世只听到一段语音，历史里却是完整文字。

### C09-07 部分送达的历史条目必须带段数 —— KNOWN

- **现状**：`finalize_and_reschedule` 只写全文（`add_message_pair`），`session_data` 里没有任何 `segment_count_*`。
- **期望**：历史条目或 `session_data` 上有 `segment_count_sent == 1`、`segment_count_planned == 2`。
- **源码证据**：`flow_orchestrator.py:195-205`；`core/domain/delivery_report.py` 定义了 `DeliveryReport`（含 `segment_count`）和 `ProactiveContext.delivery` 槽位，但**全项目从未写入、从未读取**。
- **修复后断言**：`session_data` 含 `segment_count_sent`，或历史条目带 `1/2` 标注。
- **注**：段数必须独立字段，不许拼进正文。

### C09-08 部分送达：计数 +1 与写历史（护栏，PASS）

- **现状**：`unanswered_count` 变成 1 且写了历史 —— 已是正确行为。
- **期望**：保持。口径是 **「计数和窗口认『有没有出去过』，续段认『整条出没出去』」**。
- **源码证据**：`flow_orchestrator.py:219-225` 无条件 `+1`；`docs/reconnect-experience-acceptance.md` §六-1 后果表。
- **修复后断言**：同现状（`unanswered_count == 1` 且历史非空）。
- **注**：**修 C-09 时最容易犯的错是把 partial 也改成「不 +1」**，那是 `attempted` 的口径。这条用例专门盯着它。

### C09-09 七日故事窗口 —— KNOWN（且判据已改成「状态可判定」）

- **现状**：全插件 `rglob("*.py")` 扫描 0 处出现 `story_state.json` / `last_story_sent_at_utc` —— 功能未实现。
- **期望**：`<data_dir>/proactive/story_state.json`，字段 `last_story_sent_at_utc`（**带时区 UTC**）、`story_id`（非空）、`continue_used`（布尔）、`last_story_sha256`（64 位十六进制）；**首段平台接受（F3）时写入，不等 `all_segments_accepted`**；首段失败不写；后段失败不撤销。
- **源码证据**：`docs/story-opening-acceptance.md:295`（状态文件定义）、`:18`「硬拦截必须在发送侧」、`:181`「续段不重置窗口」、`:217-221`「滚动 168h、存 UTC、三条全 fail-closed」。
- **修复后断言**（探针里已经写死，实现一落地就自动开跑）：
  1. 首段接受 + 后段失败 → 文件存在，四个字段都合法，`last_story_sent_at_utc` 与本次发送时间偏差 ≤90s（**后段失败没有撤销窗口**）；
  2. 首段失败（整体 0/N）→ **不得写**这个文件。
- **为什么不再查「文件存在」**：初验指出 `touch story_state.json` 就能通过。现在缺实现时直接判缺口，且校验器连「没时区的时间」「空 story_id」「sha 长度不对」都拒（C09-11 自检）。
- **注**：若按 `all_segments_accepted` 写窗口，首段已出、后半段失败的故事完全不占窗口，七天后又开新的 —— **7 天讲两则**。

### C09-10 DeliverStage 对 1/2 部分送达的走向（护栏，PASS）

- **现状**：`CONTINUE`，无 abort（1 段成功 1 段失败）。
- **期望**：**不得**因为「有一段没出去」就 `RESCHEDULE` —— 那会把已经发出去的一半当成没发，到点重发，造成重复。
- **源码证据**：`split_delivery.py:31` `sent_ok = (... is True)`，只有 `False` 才 `abort("send_failed") + RESCHEDULE`。
- **修复后断言**：`stage == "CONTINUE"` 且 `abort == []`。
- **注**：这条是护栏。修 C-09 时把 partial 判成 RESCHEDULE 是最直觉的错。

---

### C09-11 七日窗口状态校验器自检（PASS，补件新增）

- **为什么要有这条**：C09-09 的判定完全依赖 `validate_story_state()`。校验器一旦写松（比如「有 `last_story_sent_at_utc` 就算过」），前面的回归等于没测。
- **断言**：完整状态通过；**缺 `story_id`**、**时间不带时区（`2026-10-23 12:00:00` 这种）**、**sha256 只有 8 位** —— 三条全判红。
- **证据**：`docs/story-opening-acceptance.md:217-221` 三条规则全 fail-closed。

---

## 五、C-10 样例明细

被测：`core/services/scheduler_service.py::is_persisted_task_still_valid` / `init_jobs_from_data`、`core/features/gating_feature.py::GatingStage`、`utils/time_utils.py::is_quiet_time`。

### C10-01 正常未到期任务仍可恢复（PASS）

- 现状/期望：`valid == True`。证据 `scheduler_service.py:133-152`。
- 修复后断言：不变。**C-10 的修法不许把正常任务也清掉** —— 这条是对照组。

### C10-02 60 秒宽限边界（PASS）

- 现状：`-59s → True`、`-60s → False`、`-61s → False`。
- 期望：同上（严格小于 `next_trigger + 60`）。
- 证据：`scheduler_service.py:151` `return check_time < (next_trigger + 60)`。
- 修复后断言：不变。**60 不是拍脑袋，是写死在这个函数里的常量**；要改宽限只能改这一处，改别处不生效。

### C10-03 缺字段／脏数据／会话禁用（PASS，安全侧）

- 现状：`info=None → False`、`next_trigger_time="not-a-number" → False`、`正常 → True`、`enable=False → False`。
- 证据：`scheduler_service.py:140-148`。
- 修复后断言：不变。**fail-closed**：脏数据一律当无效，不能因为解析失败就默认要恢复。

### C10-04 停机跨过 `next_trigger+60s`（PASS）

- 现状：无 job、`next_trigger_time` 被清除。
- 期望：同上，**且不补发**（`init_jobs_from_data` 不调用发送）。
- 证据：`scheduler_service.py:497-508`（`clear_session_schedule_state` + `continue`）。
- 修复后断言：不变。**§六-4：不许为「看起来没断」加补发逻辑**，要在代码里写注释挡住后人「优化」。

### C10-05 过期任务 + `enable_auto_trigger=false` —— KNOWN（C-10 本体，判据已收紧）

- **现状**：无 job、没有任何显式状态，只有一行 `logger.info(... 持久化任务已过期或无效，清理后跳过恢复喵。)`；插件源码 0 处出现 `stall_state.json` / `PENDING.md` / `last_stall` 的写入。
- **期望**：写 `<data_dir>/stall_state.json`，**点名本会话**：
  ```json
  {"sessions": {"<umo>": {
      "session_key": "<umo>",
      "reason": "persisted_task_expired",
      "stalled_at": "<UTC ISO>",
      "expired_next_trigger": 1761...,
      "unanswered_count": 0,
      "auto_trigger_enabled": false,
      "recover_when": "next_peer_message"
  }}}
  ```
  文案仍要含「主动消息链路已停摆（原因：任务过期且未启用自动触发器）」「待对方下次发言后恢复」。
- **源码证据**：`scheduler_service.py:497-508`；`docs/reconnect-experience-acceptance.md` §六-3。
- **修复后断言**：标记存在，且 `validate_stall_marker()` 逐项通过——`session_key` 等于本会话、`reason` 精确等于 `persisted_task_expired`、`stalled_at` 与本次时间偏差 ≤90s、`expired_next_trigger` 等于本次那个过期时间、`recover_when == next_peer_message`。
- **为什么不再查「有没有文件」**：初验指出旧文件、别的会话、别的原因都能让它绿。现在这些情况全部判红（C10-13 自检 6 条反例）。
- **注**：现在从外部看只是「安静了」，分不清「没到点」和「链路死了」。这是 C-10 最难查的地方 —— 没有任何错误、没有任何告警。

### C10-06 过期任务 + `enable_auto_trigger=true` —— KNOWN

- **现状**：无 job、无 timer、无标记（`init_jobs_from_data` 里没有 `auto_trigger` 分支）。
- **期望**：两种出路**二选一，且都要留痕**——(a) 真把本会话的 job 排上，`run_date` 在未来；(b) 写同一条严格停摆标记（`auto_trigger_enabled: true`）。不得静默。
- **源码证据**：`scheduler_service.py:455-535` 完全没有 `auto_trigger` 分支（`setup_auto_trigger` 只在启动时按配置跑一遍，不处理「恢复时发现过期」）。
- **修复后断言**：只认两种真凭据——**本会话 job 的 `run_date` 在未来**，或**本会话的严格停摆标记**。别的会话的 timer、上一轮遗留的 job 一律不算（初验点名的漏洞）。
- **注**：如果走「重新排期」，`run_date` 必须在未来；把过去时间塞进去等于假装没断。

### C10-07 重复恢复幂等（PASS）

- 现状：连跑两次 `init_jobs_from_data`，job 数都是 1。
- 证据：`scheduler_service.py:254-267`（固定 `id=normalized` + `replace_existing=True`）、`:515`（已存在则跳过）。
- 修复后断言：不变。**新增任何重连重排逻辑必须沿用同一个 id 约定**，否则重连一次多一个 job、N 次重连 N 倍发送。

### C10-08 免打扰边界（PASS）

- 现状：`1-8` 的 1 点/7 点禁、8 点放；`23-6` 的 23 点/2 点禁、6 点放。
- 证据：`utils/time_utils.py:12-28`（右开区间 + 跨天分支）。
- 修复后断言：不变。

### C10-09 免打扰配置非法（PASS）

- 现状：`is_quiet_time("not-a-range") → False`。
- 证据：`utils/time_utils.py:26-28`。
- 修复后断言：不变。**配置写错不能变成全天免打扰**（那才是真正静默停摆）。

### C10-10 未回复达上限（PASS）

- 现状：`STOP` + `abort("max_unanswered")`。
- 证据：`gating_feature.py:64-69`。
- 修复后断言：不变。

### C10-11 免打扰时段（PASS）

- 现状：`RESCHEDULE` + `abort("quiet_hours")`（注意是 RESCHEDULE，不是 STOP）。
- 证据：`gating_feature.py:35-40`。
- 修复后断言：不变。**免打扰是「等会儿再来」，未回复上限是「别来了」，两者语义不同。**

### C10-12 已超上限的会话被恢复后，到点仍被 GATE 拦下（PASS）

- 现状：恢复出了 1 个 job，但 GATE 判 `STOP` + `abort("max_unanswered")`。
- 期望：保持不变 —— **恢复阶段不读上限是有意为之**（上限是发送期判定），但端到端必须发不出去。
- 证据：`gating_feature.py:64-69`。
- 修复后断言：`STOP` + `abort("max_unanswered")`。
- 注：修 C-10 时**不要**顺手在恢复阶段也加「超上限就不恢复」——上限是发送期判定（`gating_feature.py:64-69`），恢复期再判一次等于把同一条策略写两处，将来改一处必然漂移；而且恢复阶段不建 job 时，到点连「该不该发」的判断都不会发生，反而更难诊断。

---

### C10-13 停摆标记校验器自检（PASS，补件新增）

- **为什么要有这条**：C10-05/C10-06 的判定完全依赖 `validate_stall_marker()`。初验点名的风险就是「随便一个 `PENDING.md` 就能过」——那等于没测。
- **断言**（6 条）：完整标记（`sessions` 包裹）通过、扁平单会话通过；**别的会话**、**别的原因（`max_unanswered`）**、**一天前的旧标记**、**`expired_next_trigger` 不符** —— 四条全判红。
- **证据**：`docs/reconnect-experience-acceptance.md` §六-3 的停摆状态要求。

---

## 六、给 Codex 的验收清单（= `KNOWN_BUGS` 十条）

| ID | 缺陷一句话 |
| --- | --- |
| C09-01 | 0/N 段只返回 `bool False`，没有 `attempted` 态，调用方分不清「一段没出去」和「配置缺失」 |
| C09-02 | 1/N 段返回 `bool True`，被当成整条成功继续走（**C-09 本体**）|
| C09-03 | 非分段单条也只有 `bool True`，没有 `all_segments_accepted` 与段数 |
| C09-04 | 首段失败、后段成功同样返回 `True`，缺 `partial` 与「哪几段失败」 |
| C09-05 | N/N 全成功仍是 bool，没有 `segment_count` 供审计 |
| C09-06 | TTS 已发、文本段全失败 → 返回 `True`，文本全丢却记成整条成功 |
| C09-07 | 部分送达的历史条目没有 `segment_count_sent / segment_count_planned` |
| C09-09 | 七日窗口未实现：插件源码 0 处读写 `story_state.json`，窗口无法按「首段平台接受」计时 |
| C10-05 | 过期任务 + `enable_auto_trigger=false` → 只有一行 info 日志，没有点名本会话的停摆状态（**C-10 本体**）|
| C10-06 | 过期任务 + `enable_auto_trigger=true` → 同样只有日志，没有重新上膛路径 |

**验收步骤**：修完一条 → 从 `KNOWN_BUGS` 删掉该 key → `"$PY" data/probe_c09_c10.py` 必须退 0。全部删完时 `--allow-known` 与默认模式应当完全一致（都退 0）。

---

## 七、五条判定口径（比代码更容易出错的地方）

1. **四级枚举，禁布尔**：`attempted` / `platform_accepted` / `all_segments_accepted` / `partial`。后果表：

   | 状态 | 未回复计数 | 写历史 | 续段 | 七日窗口 |
   | --- | --- | --- | --- | --- |
   | `attempted`（一段没出去）| 不 +1 | 不写原文 | 否 | 不动 |
   | `platform_accepted`（出去了，但不确定整条）| +1 | 写全文 | 待定 | **写** |
   | `partial`（首段出去了、后面失败）| +1 | 写全文 + `segment_count_sent/planned` | 否 | **写** |
   | `all_segments_accepted` | +1 | 写全文 | 是 | **写** |

   一句话：**窗口与计数认「有没有出去过」，续段认「整条出没出去」。**

2. **段数独立字段**，不许拼进正文（`segment_count_sent` / `segment_count_planned`）。

3. **60 秒宽限只有一处**：`scheduler_service.py:151`。改宽限改这一行，别在别处加。

4. **停摆状态必须显式**，且措辞固定 —— 因为它是给人看的诊断信号，四种停摆原因要能一眼区分：任务过期且未启用自动触发器 / 未回复达上限 / 免打扰 / 正常等待。

5. **状态类断言只认「可判定」，不认「文件存在」**。

   凡是新增持久化状态（`story_state.json`、`stall_state.json`），验收必须同时成立：**文件在 + 字段齐 + 会话对 + 时间对 + 原因对**。缺一条都判红。

理由很实际：初版权威探针里 C09-09 只查文件存在，`touch` 一下就是绿的；C10-05 只要目录里有一个叫 `PENDING.md` 的东西就绿。这种断言在「功能没实现」和「功能实现了但写错会话」之间没有区别——而后者比前者更危险，因为它会让人以为可观测性已经有了。

配套两条自检（C09-11 / C10-13）就是用来证明校验器本身不放水的：喂进去缺字段、无时区、别的会话、旧时间、错原因，必须全部判红。

---

## 八、测试盲区（探针测不到，靠运行时观察）

1. **`OnAfterMessageSentEvent` 只在分段循环之后派发一次**（`astrbot_event.py:592-596`），所以观察插件每「一次主动消息」记一行 —— **出站记录条数 ≠ QQ 气泡数**。真实验收必须用收件端气泡数，不能用日志条数。
2. **真实平台的部分成功**：探针用脚本模拟「平台接受/不接受」，测不到 QQ 侧的限流、撤回、风控吞消息。真机只能靠来世那边看到几条。
3. **进程内重启**：探针是「新进程读到旧 state」，测不到 `init_jobs_from_data` 与正在运行的 timer 同时存在的竞态。
4. **`data_dir` 实际内容**：探针只查文件存在性，不校验原子替换和 JSON 完整性。
5. **跨天/时区**：免打扰用 `plugin.timezone`，探针固定 `Asia/Shanghai`，测不到实例时区配错的情况。

---

## 九、变更记录

- **2026-10-23 初版**：22 条（C-09 十条 / C-10 十二条），12 通过 / 10 失败。
- **2026-10-23 补件 v2**（初验后）：判定收紧 + 新增两条自检，**24 条（C-09 十一条 / C-10 十三条）**，14 通过 / 10 失败。
  - C09-09：判据从「`story_state.json` 存在」改成「实现存在则真跑两分支并逐字段校验，实现缺失则判缺口」，并把契约（字段/UTC/写入时机）写死；
  - C10-05：判据从「任意 `PENDING.md`/`stall_state.json` 存在」改成「严格校验会话、原因、时间、恢复条件」；
  - C10-06：判据从「jobs 或 timers 或标记任一存在」改成「本会话 job 的 `run_date` 在未来，或本会话严格标记」；
  - 新增 C09-11 / C10-13（校验器自检），当前 PASS，专防校验器放水。

- 2026-10-23：DS-05 交付。探针 22 条（C-09 十条 / C-10 十二条），通过 12、登记失败 10，未登记失败 0。默认退 1，`--allow-known` 退 0。
