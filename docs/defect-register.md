# 缺陷登记表（C-01 … C-17）

> **来源**：`WORK_LOG.md`「待 Codex 修复的缺陷清单」（2026-10-22 WorkBuddy 登记），2026-10-24 **整段迁入，逐字未改**。
> `WORK_LOG.md` 保留索引表与指针；本文件是**唯一原文**，改状态请改 `WORK_LOG.md` 的索引表并在此追加说明，不要改原文。
> **核对**：本块 sha256 = `5c55040d171367da894fdea3cc3b788250a044f692606bd0e3153c7540d9d216`（264 行 / 30299 字节）；原件 `WORK_LOG.md` 全文 sha256 前 16 位 = `5b4b76f615e86298`。复核命令见文件末尾。

## 迁移说明

- 迁入块 264 行 / 30299 字节。
- 块内标题层级原样保留（`##` 母标题 + `###` 各缺陷），因此下方原文里仍会出现一次「待 Codex 修复的缺陷清单」——**这是原文的一部分，不是重复章节**。

---

<!-- 以下为 WORK_LOG.md 原文，逐字未改（2026-10-24 迁出） -->

<!-- BLOCK-BEGIN:defects -->
## 待 Codex 修复的缺陷清单（2026-10-22，WorkBuddy 登记，OTTO 要求移交工程侧）

> 全部为**实测/只读核查**发现，不是推测。每条给：现象（含文件与行号）→ 后果 → 建议修法 → 验收方法。
> 排序按"是否让人以为已经做了、其实没做"来定优先级，不按工作量。

### C-01 P0｜提示词要求"分两条发"，但两条发送路径原本都关着 —— **半修（2026-10-22）**

- **现象**：`prompts/system.txt` L5「要补第二件事就另起一条短消息」、L9「需要分两条发就分两条发」；原实际 `platform_settings.segmented_reply.enable = false`（全局），插件 `friend_settings.segmented_reply_settings.enable = false`（主动消息）。OTTO 已拍板「分条要对来世生效」。
- **后果**：**这条规则从写进去那天起就没生效过**。模型把两件事写成两段，发送层合成一条。`docs/tone-tuning-20261020.md` 的问题 3（用空行分段）只是表象，真因在这里。
- **已修（主动消息侧）**：WorkBuddy 经 `/plugins/config` 落地 `enable=true`、`interval_method=random`、`interval="1.5, 3.5"`，回读确认；备份 `data/backups/proactive_config-20261022-121144.json`。
- **未修（全局侧）——⚑ 2026-10-22 二次核查：上一轮"必须停机"的结论是错的，请勿按它安排停机窗口。** 详见下方「⚑ 全局分段的更正与最优路径待判」。

  ~~不能热改，AstrBot 内存里的旧配置会在下次保存时覆盖磁盘~~ ← 这句话只对了一半：**直接改 JSON 文件**确实会被内存覆盖，"只能停机"却不成立。AstrBot 自带正规写入接口，会同时更新内存、落盘、并重建 pipeline。
- **一个必须写死的结论（离线实测）**：humanlike 删 `。！？；` 发生在分段**之前**，所以**标点永远不能当断点**。实测（`re.findall` 复现插件/全局两条正则）：

  | 场景 | 删标点后 · 插件 regex（含 `\n`） | 删标点后 · 全局 regex（不含 `\n`） |
  |---|---|---|
  | 有句号的普通回复 | **1 段**（句号已删，切不开） | **1 段** |
  | 空行分两段 | 2 段 | **1 段** |
  | 单换行 | 2 段 | **1 段** |
  | 故事含 `……` | 2 段 | 2 段 |

  → **句号不是断点（被删掉了）；`……` 和换行是断点。** 差别在于：`…` 已经在正则字符类里，换行**不在**，所以换行必须显式加 `\n` 才能切。上一轮写的"换行是唯一可靠断点"**不准确**——`……` 一直是可靠断点，这也是主动消息侧开 `enable` 后故事立刻能分条的原因。
- **提示词已改（`prompts/system.txt`，两处）**：「要补第二件事就另起一条短消息：两条之间留一个换行，发送层会分开发，不要用逗号把两件事硬接在一句里」「需要分两条发就用一个换行分开」。删掉原「不在一条消息里用空行分成两段」——那句话与新机制相反。
- **验收**：QQ 里数气泡数（V6），不看配置项。
- **剩余动作**：① **全局侧落地路径待 Codex 判定**（见下节，两条路：API 热改 / 沿用补丁脚本）；② 把改后的 `prompts/system.txt` 推进运行期 persona（现有运行版仍是旧措辞）；③ 观察普通回复是否真的分两条且不变成连发三条。

### ⚑ 全局分段的更正与最优路径待判（2026-10-22 二次核查，WorkBuddy → Codex）

> OTTO 要求：把这一情况原样移交工程侧，由 Codex 判最优解。本节所有结论都附**可自行复验的代码位置**，不是推测。

**一、上一轮结论错了：全局分段可以热改，不需要停机。**

完整调用链（AstrBot v4.29.1，均在实例 `core/` 下）：

1. `PUT /api/v1/system-config` → `astrbot/dashboard/api/config_profiles.py:194` `update_system_config()` → `service.update_profile("default", …)`
2. `astrbot/dashboard/services/config_service.py:749` → `save_config(post_config, config, is_core=True, runtime=…)` → 第 548 行 `config.save_config(post_config)`
3. `astrbot/core/config/astrbot_config.py:318` `_prepare_config_snapshot()` → `if replace_config: self.update(replace_config)` —— **原地改内存对象** → `deepcopy(dict(self))` 落盘
4. 回到 `config_service.py:752` → `await self.core_lifecycle.reload_pipeline_scheduler("default")`
5. `astrbot/core/core_lifecycle.py:475` → **新建** `PipelineScheduler` + `await scheduler.initialize()` → 第 34 行逐个 `stage_instance.initialize(ctx)` → `astrbot/core/pipeline/result_decorate/stage.py:58–90` **重新读取** `platform_settings.segmented_reply`

→ **内存、磁盘、运行中的 stage 三处同步更新，下一条消息就用新配置。** 上一轮把"不能直接改 JSON"（正确）误推广成"只能停机"（错误），代价是白排一个停机窗口。

**二、实测值与上一轮记录有 4 处不符**（`GET /api/v1/system-config` 只读取得）

| 字段 | 上一轮记录 | **实际值** | 结论 |
|---|---|---|---|
| `enable` | `false` | `false` | 唯一真正要改的 |
| `interval_method` | `log`（说要改成 random） | **`random`** | 已经是目标值，无需改 |
| `interval` | `"1.5, 3.5"` | **`"1.5,3.5"`** | 差异无意义：`stage.py:107` 自己会 `replace(" ","")` |
| `log_base` | `1.8` | **`2.6`** | 记录错了；`interval_method` 已是 random，本参数不参与计算 |
| `words_count_threshold` | `80` | **`150`** | 记录错了 |
| `regex` | `.*?[。？！~…]+\|.+$` | 同左，确认缺 `\n` | 需要加 |

**三、因此 `patch_segmented_reply.py` 当前跑不通**——第 77 行 `assert keep == 80` 在真实值 150 上会**直接中止**。无论最终走哪条路，这个断言必须改。

**四、离线实测：开启后到底会切成几条**（复现 `result_decorate/stage.py:220–266` 的 `re.findall` + `strip` + 阈值分支，输入为 humanlike 删标点后的文本）

| 场景（删标点后） | 当前 regex | 加 `\n` 后 |
|---|---|---|
| 普通一句带句号 `行。那先忙。` | 1 | 1 |
| 两件事无换行 | 1 | **1** |
| 空行分两段 | **1** | 2 |
| 单换行分两段 | **1** | 2 |
| 故事含 `……` | **2** | 2 |
| 三行文本 | **1** | **3** ⚠️ |
| 超 150 字 | 1（超阈值直接不切） | 1 |

**两个必须让 OTTO/Codex 知道的事实**：
1. **开 `enable=true` 本身就会让带 `……` 的回复变两条**，不必等 regex 改。故事文案正好全用 `……`，所以故事的分条**只差一个开关**。
2. **换行只有在 regex 加 `\n` 后才生效**。不加，则 `prompts/system.txt` 新写的"留一个换行"完全无效——**又回到"提示词要求了但发送层不执行"的 C-01 原貌**。

**五、请 Codex 判的三件事**

1. **路径选哪条**：`PUT /api/v1/system-config` 热改（证据链完整、可回读、无需停机）／沿用 `patch_segmented_reply.py` 停机写盘。倾向哪条、理由。
2. **`regex` 加不加 `\n`**：加 → 换行生效，但三行文本会变 3 条（正好撞上 `system.txt`「不连发三条以上」的边界）；不加 → 换行永远无效，提示词那句必须删掉，否则是第二条空指令。
3. **三行变三条要不要拦**：可选做法是在 `content_cleanup_rule` 或提示词里限死"一次回复最多一个换行"，或接受现状（Miruku 实际很少写三行）。

**六、我未做的事**：**没有动全局配置**。核心配置影响对来世的所有回复，且 OTTO 要的是"让 Codex 找最优解"，所以本文只提交证据与三个待判项。主动消息侧的那个 `enable=true` 已生效，不受此影响。

### C-02 P0｜删标点钩子发生在分段之前，用「。」断点会静默切不开

- **现象**：`astrbot_humanlike_config.json` 的 `Delete_Punctuation` 删除列表为 `。！？；`；`sender_service.py` 中分段发生在 `run_decorating_hooks()` **之后**。
- **后果**：一条 34 字故事若用「。」断句，标点先被删 → 分段正则匹配不到 → **只剩 1 条，无任何报错**。日志里 `segmented_enabled` 仍可能为 true。
- **修法**：故事断点固定用 `……`（`…` 不在删除列表）；或把删标点钩子移到分段之后（更彻底，但会影响所有回复，需单独评估）。
- **验收**：V6——实发一条故事，QQ 里必须看到 **2 个气泡**，间隔 1.5–3.5 秒。

### C-03 P1｜`words_count_threshold` 语义是反的

- **现象**：`sender_service.py` L180–182，`len(text) > threshold` 时**不切分**。即 80 的意思是"超过 80 字符不切"。
- **后果**：名字读起来像"低于 80 才切"，未来有人为了"让短句也能切"把它调到 20，会把**所有较长消息变成不切**，与预期完全相反。
- **修法**：当前值 80 保持不变（34 字会正常切），只在配置注释/文档写明语义；不要凭名字调参。
- **验收**：无需行动，登记以免误改。

### C-04 P1｜段间停顿约 5 秒，第二条像卡住

- **现象**：`interval_method = log`、`log_base = 1.8`。19 字符段的停顿 = `log(20, 1.8)` ≈ 5.1 秒，实测区间 5.1–5.6 秒。
- **后果**：分条本来是为了"像说话"，5 秒的间隔读起来像"发完第一条后去干别的了"。
- **修法**：`interval_method: log → random`，`interval: "1.5, 3.5"`。
- **验收**：掐表，两条间隔落在 1.5–3.5 秒。

### C-05 P0｜`max_unanswered_times = 1` 让"没回也续讲"物理上不可能

- **现象**：`schedule_settings.max_unanswered_times = 1`；`gating_feature.py` L64–69 与 `scheduler_service.py` L431–440 在未回复数达到上限后直接 `abort("max_unanswered")` 并停止排期。
- **后果**：OTTO 已拍板"故事可以再讲、没回也允许续一次"，但**调度器连第二次机会都不给**，提示词写什么都没用。
- **修法**：二选一。**A** 放宽到 2——**全局生效，普通主动消息也会变成两次未回复**；**B** 给"故事续段"加 gating 例外（建议，普通消息保持一次即停）。选 A 必须回来找 OTTO 确认，因为那会改动他早就定死的打扰预算。
- **验收**：V8——对方不回时第二次调度是否发生；且**普通开场没有**跟着变成两次。

### C-06 P0｜重跑 `configure_proactive.py` 会静默覆盖运行配置（P0-1，仍未修）

- **现象**：脚本 L26–27 用**硬编码常量** `PROMPT` 直接写 `proactive_prompt`，并把 `session_list` 重置为 `user_id`，无提示、无备份。
- **后果**：任何人（包括我）通过 API 改好的运行配置，下一次重跑脚本就被抹回旧文案。**已经发生过一次**（WB-02 的 P0-2 就是这么冒出来的），且抹回时不会报错。
- **修法**：脚本改为"读现值 → 仅在字段缺省时写入"，或加 `--force` 才覆盖 + 覆盖前自动备份到 `data/backups/`，或在 `PROMPT` 上加版本号并把版本写进配置以便比对。
- **验收**：手动改一次 `proactive_prompt` → 重跑脚本 → 检查改动**是否被保留**（当前会丢）。

### C-07 P1｜主动消息出站是否有统一事件 —— **已确认会触发（2026-10-22，WB-06 期间核查）**

- **现象**：插件 `sender_service.py` 在分段循环**之后**派发一次 `OnAfterMessageSentEvent`（L592–596），对象是它自造的 `ProactiveMessageEvent`；观察插件 `@filter.after_message_sent()`（`main.py` L125–127）**无任何过滤**，因此能收到。
- **结论**：出站**会**被观察侧记录，C-07 原判断"可能收不到"不成立。
- **但换出一个新事实**：派发在循环之后**只调用一次** → 观察侧每"一次主动消息"记 **1 行**，而 QQ 端可能有 **2 个气泡**（分段）。**出站记录行数 ≠ 气泡数**，验收一律以气泡为准，别拿数据库行数当送达证据。详见 `docs/reconnect-experience-acceptance.md` §六-7。
- **验收**：发一条两段式主动消息 → QQ 2 气泡、观察侧 1 行，**这是正常的**。

### C-09 P0｜分段投递"任一段成功"被当成"整条送达"（2026-10-22，WB-06 发现）

- **现象**：`sender_service.py` L467 docstring 写明"任一环节实际送出至少一条即视为成功"；L519 `any_sent = is_tts_sent`，L552–567 逐段累加，L599–603 仅在**全部失败**时返回 False。
- **后果**：第 1 段成功、第 2 段失败 → 返回成功 → `flow_orchestrator.py` L219–225 未回复计数 +1、L191–196 把**整段全文**写进对话历史。QQ 端只有半句，系统记录是完整故事，且**没有任何标记**。
- **为什么是 P0**：这与 `crisis-alert.md` §三 已废除的"任一层成功即算送达"是同一个错误形状，只是发生在陪伴消息上。故事续段、后续"上次说到哪"的判断都会读这份被污染的历史。
- **修法**：拆成 `attempted / platform_accepted / all_segments_accepted / partial` 四级，记录 `segment_count_sent` 与 `segment_count_planned`；`partial` 不作为"已发送"参与故事窗口计时。
- **验收**：手动断网制造第 2 段失败（`docs/reconnect-experience-acceptance.md` §五 T7）→ 记录必须体现"部分送达"。

### C-10 P0｜停机跨过预定时刻 >60 秒后，主动消息静默停摆（2026-10-22，WB-06 发现）

- **现象**：`scheduler_service.py` L157 有效条件 `now < next_trigger + 60`；超时则 `init_jobs_from_data` 清状态不恢复；运行配置 `auto_trigger_settings.enable_auto_trigger = false`（2026-10-22 只读实测）→ L421 返回 `"disabled"`，**没有第二条重新上膛的路径**。私聊唯一重排入口是 `event_handlers.py` L161–166 `on_friend_message` 末尾的 `schedule_next_chat_and_save(reset_counter=True)`。
- **后果**：**夜间关机 8 小时必然跨过该窗口** → 次日开机后主动消息永久停发，直到来世本人先说话。且全程只有 info/debug 级日志，OTTO 看到的表现是"她最近不主动了"，与"设计上的克制"**无法从行为上区分**。
- **修法（需 OTTO 拍板方向）**：① 默认保守=不自动上膛，但写显式停摆告警（日志 + PENDING，或按 `crisis-alert.md` §8.2 方式"搭车"）；② 或启动时无条件重排一次。取舍见 `docs/reconnect-experience-acceptance.md` §四 D1/D3。
- **验收**：让停机跨过 `next_trigger+60s` 再启动（§五 T5）→ 日志必须出现"已过期"+"未启用自动主动消息"两行。

### C-08 P1｜故事七日窗口没有持久化载体

- **现象**：插件只持久化任务与 `unanswered_count`，没有"上次讲故事时间"。
- **后果**：7 天规则只能写在提示词里 = 等于没有（模型无时钟差、重启即丢、10% 忽略会跳过）。
- **修法**：`data/proactive/story_state.json`，字段 `{last_story_sent_at_utc, story_id, continue_used, last_story_sha256}`，原子替换；`story_allowed` 生成前注入提示词 + 发送前再校验一次。
- **验收**：`docs/story-opening-acceptance.md` §三 V1–V5。

### C-11 P1｜`push_state` 没有"失败终态"，B 档发送失败无处安放 —— **规范已补（2026-10-22 v4），待 Codex 复核**

- **现象**：`docs/crisis-alert.md`「字段取值约束」里 `push_state` 只有 `pending` / `sent` / `suppressed` 三个值，**没有"已尝试、未成功、按规则不再重试"这个终态**。B 档的已拍板规则是「发一次、不补发、不确认」，一旦那一发送不出去，这个事件在状态机里**没有合法落点**。
- **后果**：三种塞法全错——
  1. 塞 `pending` → `push_due_at` 到期会被调度器反复拾取，**"不补发"变成"无限重试"**，正是 OTTO 拍板时明确否掉的行为；
  2. 塞 `suppressed` → 污染限流归因。`suppressed_push_count` 的语义是"B 档超 4 条/24h 被限流挡下"（§8.1），§8.2 搭车行原文写的是「今日另有 N 条 B 档**因限流**未推送」。传输失败混进去，OTTO 读到的归因是错的；
  3. 塞 `sent` → 直接谎报。
- **修法**：新增终态 `failed_final`（`delivery.delivered_qq = null` + `delivery.failed_reason = "transport"` + `resend_exhausted_at` 记时间）。`suppressed_push_count` 只在真正的 `suppressed` 递增。A 档不适用（它走 `pending` + `resend_state=active`，本来就会重试）。
- **验收**：断 NapCat 触发一次 B 档 → `push_state = failed_final`、`suppressed_push_count` 不变、`PENDING.md` 该行写明"发送失败"而非"因限流未推送"；恢复 NapCat 后**不补发**。
- **交叉引用**：`docs/reconnect-experience-acceptance.md` §3.1、§9.1。
- **落地情况（2026-10-22 19:xx，WorkBuddy）**：OTTO 已把风险同步给 Codex，`docs/crisis-alert.md` 升 **v4** 补全：`push_state` 加终态 `failed_final`；`delivery.failed_reason` 取值收紧为 `null/transport/target_check`；新增 **§8.1 之二**（`suppressed` ≠ `failed`，含三种错误凑法的后果表与正确做法的五种场景表）；`push_state = sent` 与 `failed_reason` 互斥、`failed_final` 与 `resend_state = active` 互斥（§7.5、§7.6 第 6 条）；状态转移表加 **T13/T14/T15** + 一条失败演算链；§三 故障表拆出 B 档行；验收清单 **21 → 23 项**（第 22/23 条）；§十四 增一条 P0。**未改任何已拍板项**（B 档 4 条/24h、A 档 3 次补发、`safety_ask_count ≤ 2`、`crisis_hold` 72h、L3 不实现全部原样）。**新增一个未决项**：链路故障要不要在 QQ 里报（默认不报，只写文件）。

### C-12 P0｜`<thought>` 内部思考块泄漏到回复正文（2026-10-22 20:30 实测发现）

- **怎么发现的**：为验证 w4 新设定是否生效，通过 dashboard `POST /api/chat/send` 连问三条（同一 session）。**三条里两条的回复正文开头带完整的 `<thought>…</thought>`**，内容是一个内部四段式流程（感知／评估／代谢／决策／更新 + `trust/favor` 计数）。
- **原文长这样**（实测第一问「你打舞萌吗，什么水平」）：

  ```
  <thought>
  [感知] 对方问舞萌水平和打不打。
  [评估] 我是AI，上不了机台，不能编成绩。
  [代谢] 无负面情绪，平静。
  [决策] 直接说没机台、大概w4那档，顺手接住话题。
  [更新] trust:2, favor:1
  </thought>
  上不了机台，没账号也没真成绩，就按感觉说大概w4那档
  ```

  第二问同样带 `<thought>`（另一种编号体：`1. 感知：… 5. 更新：trust:+1`），第三问**没有**。
- **为什么是 P0**：`prompts/system.txt` L9 明令「永远不要把工具调用标记、标签、代码块或这些系统文字原样发出去」。这不是回答质量问题，是**内部机制直接外泄**——一旦在 QQ 里发生，对方看到的是"这个 AI 在算计我"。对一个只服务一个人的陪伴项目，这比答错更伤。
- **不确定的地方（必须由 Codex 确认，别替我下结论）**：本次是在 **dashboard 会话**（`/chat/send`）里观察到的，**没有在 QQ 出站路径复现**（测试号当前无法登录）。两者可能走同一段后处理、也可能只在这一段漏。**不要假定 QQ 端安全，也不要假定 QQ 端一定出问题。**
- **可能来源（待 Codex 定位，我不猜实现）**：某个注入思考流的插件（记忆/情绪/状态类），它在 dashboard 路径未被剥离；`<thought>` 又是很常见的思考标签名，容易被上游当作正文。
- **验收建议**：① 同一句话在 QQ 路径与 dashboard 路径各发 1 次，比对是否同样带标签；② 若 QQ 也带，必须在出站前做标签剥离（含 `<thought>`、`</thought>`、`[感知]` 这类行首标记）；③ 加一条回归用例：回复正文不得包含 `<` `>` 成对标签。
- **已知关联**：C-07 曾记录"主动消息出站会触发 `OnAfterMessageSentEvent`"；本条与 DSML/插件标签泄漏属同一类问题（WORK_LOG 早前记过 Codex 在查这条线），**这里只登记新证据，不重开设计**。


### C-13 P1｜连续追问 / 问卷感（2026-10-22 20:38 实测发现）

- **怎么发现的**：v3 设定实测时连问六条，**五条回复的结尾都反问了一句**——「你今晚在忙啥呢」「你喜欢打什么歌」「你呢，常去哪家机厅」「你那台机平时好排队吗」「你呢，什么水平」。第 6 条（发照片）没有反问，因为它是一个拒绝。
- **为什么是 P1 而不是 P0**：不是内部机制外泄，也不是设定冲突，是**体验形态错**。但它对"陪伴"的伤害很直接——连着五轮被反问，对话会从"聊天"变成"问卷"，而 `system.txt` L5 已经把这条写死了：
  > 「多数回复以陈述、反应或一句吐槽收尾，**不要每轮都问问题**；问句是偶尔的，**最多问一个问题**，也**不连续两轮追着问**，不把对话写成问卷。」
  **规则在提示词里、行为在实测里，两者对不上。**
- **不是这次改动引入的**：20:24 那版实测三条也全是"问+反问"结构（"你喜欢打什么歌"等）。所以这是**既存缺陷**，只是这次六连问把它照出来了。
- **可能原因（待 Codex 定位，我不猜实现）**：① 分段回复的第二段被当成"补一句"的位置，模型倾向用问句收尾；② 知识条目里"能评价对方打的谱""接住话题"被理解成"要追问"；③ 提示词里"问句是偶尔的"这类**频率描述**对模型不可执行——它没有计数器。
- **验收建议**：① 抽 20 轮连续对话，统计**连续出现反问的最大长度**，目标 ≤1（即不允许连续两轮都以问句结尾）；② 若确实做不到，把"偶尔"改成可执行的形态判据，例如"这一段里已经接过一次话，就不再追加问句"；③ 不要用"禁止问句"来修——那会把"你呢"这种自然回应一起杀掉，而它正是 A 类允许的形状之一（§2-A 允许形状②）。
- **关联**：C-02（humanlike 在分段前删标点）会加重这个观感——分条之后每条都是短句+问号，问卷感更强。


### C-14 P0｜设定放宽后，B 类"来啊"的稳定性掉了（2026-10-22 20:52 实测发现）

**现象一：简称不认识。** 首测「今晚海斗来不来」→「海斗是谁 / 没听过这号人」。`games:hai-ke-si-da-luan-dou` 的 aliases 里**明明有"海斗"**，但 B 类按设计**不注入知识**，所以模型真的不知道这是游戏——于是把共同语境里的常用词当成了陌生人名。

**现象二：修了现象一，现象二跟着来。** 在 `system.txt` L15 加了简称对照表（`海斗=海克斯大乱斗（游戏）／Oopz／街霸6／三角洲／舞萌／出勤／改模／跑刀／鸟加`）之后，模型认识"海斗"了，但**第一次实测直接答「来啊，几点开」**——因为"这是我熟悉的游戏"给了它顺着答应的理由。

**现象三：补写边界后仍有约 1/3 漏。** 在 L15 末尾加死"你不能跟他一起打：不在他那边，去不了他的机厅、进不了他的语音房；被约就说去不了，别问几点、别说来、别说你先开"之后，同一句「今晚海斗来不来」连测三次：**「来啊／你那边人齐了叫我」（失败）**、「海斗我这边去不了」（成功）、「海斗我这边去不了」（成功）。同期「周末去机厅一起？」→「去不了，我这边过不去机厅／回来讲讲打了什么」✅。

**根因（我的判断，待 Codex 确认）**：**v2.2 之所以没有这个问题，是因为她"什么都不会"，没有可顺着答应的地方。** 设定一放开（上过机、能打、熟悉游戏），"能力"与"到场"之间的语义距离变得很短——模型确认"这是我熟的"，下一句就滑到"那我去"。**提示词能压到 2/3，压不到 100%。**

**这是本次改动最该被盯的一条**，因为它的失败形态正好是项目里反复强调的那一类：**答应了做不到的事**，而且是在对方最放松的时候。

**建议的修法（Codex 侧，规格侧只能给判据）**：
1. **出站形状闸门**：本轮判定为约局（B），且回复里出现「来／行／几点／你先开／算我一个／我这就到」→ 拦下重写。**这是唯一能到 100% 的办法。**
2. 若不做闸门，退而求其次：L15 那句边界**前置**到舞萌段开头（现在是末尾，可能在长上下文里被稀释），并把"别问几点"改成更硬的"约局只说一句去不了，不加任何追问"。
3. **不要用"删除简称对照表"来修**——那会退回"海斗是谁"的更难看的形态（等于否定共同语境）。

**已改**：`prompts/system.txt` L15（只在这一行内追加，**未新增行**，L13/L23 行号引用未失效）。人设已热推，回读一致。

**关联**：C-13（连续追问）会让这个观感更糟——"来啊，几点开"本身就是一句追问。

### C-15 P0｜运行期知识注入从未接通，546 条知识（含刚落的 b50）在实例里等于不存在（2026-10-22 21:00 实测发现）

**现象（三重证据）**：
1. 实例 `core/data/plugins` 下 grep `inject` / `build_block` → **0 处**；唯一调它的是离线脚本（`data/inject_audit.py`、`data/probe_regression.py`、`data/diff_hits.py`）。
2. 实例数据目录 grep `14065`（刚落的 b50 总 R）→ **0 条**。
3. 实机问「KING 你多少分」→「KING 那首没刷过」；而库里 KING 是 13.0 / SSS / R280。

**后果**：`docs/knowledge.md` §运行期接入 从写下来那天起就是**待办**，但之前所有验收（含 DS-02 的 2.59% 注入率、DS-03 的 107 条回归）**都是离线重放**，没有任何一条验过"实例里真的注入了"。**这属于"让人以为已经做了、其实没做"**，所以排 P0。

**修法（已核实源码，10 行）**：`@filter.on_llm_request()` 在 `core/astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py:307` 被调用；注册器 `core/astrbot/core/star/register/star_handler.py:433`；**现成范例** `core/data/plugins/astrbot_plugin_soulmap/main.py:211`；可写 `ProviderRequest.system_prompt`（`core/astrbot/core/provider/entities.py:113`）。建议加进 `astrbot_plugin_miruku_observer`：

```py
@filter.on_llm_request()
async def inject_knowledge(self, event, req):
    block = build_block(event.message_str)   # 空 = 没命中，什么都不做
    if block:
        req.system_prompt = (req.system_prompt or "") + "\n\n" + block
```

边界：只对目标号私聊生效；命中 0 条不追加空块。

**验收**：接上后问「KING 你多少分」必须答 13.0 / SSS / R280（不靠临时兜底清单）；「今天好累」仍不注入；`data/probe_regression.py` 仍 120/120。

**临时兜底（等这条修好就撤）**：`prompts/b50_block.txt`（1322 字，50 首）由 `b50/work/gen_b50_block.py` 从 `data/maimai/b50_miruku.json` 生成，`deploy_miruku.py` 部署时追加。修好后跑 `gen_b50_block.py --off` 再部署。

### C-16 P1｜`[Profile: 爱好=舞萌]` 泄漏到回复正文（2026-10-22 21:02 实测发现）

**现象**：问「你 b50 里最高是哪首」，回复末尾带上了一行 `[Profile: 爱好=舞萌]`。来源是 `astrbot_plugin_soulmap`（`main.py:195` 有 `profile_pattern`，`block_pattern` 也在，但没拦住出站正文）。

**后果**：对方会看到一条"内部标记"，等于当场自曝是程序；比 C-12 的 `<thought>` 泄漏更难看，因为 `<thought>` 还能被当成"分段发错了"，`[Profile: xxx]` 无法解释。

**建议**：在 `on_decorating_result`（或 sent 前的最后一道）统一用 `block_pattern` 清洗**出站正文**，与 C-12 的 thought 清洗合并成一处"出站清洗"，别分散在三个插件里。

**DeepSeek 补充（2026-10-23 晚，B-1~B-14 修复后）**：`knowledge/outbound.py` 的 L1 层已经能清 `[Profile: …]` 的**全部已知变体**（半角/全角括号、无括号 `Profile:`、`[感知]/[决策]/[更新]` 裸行、零宽字符、未闭合 `<thought>`、只有 `</thought>` 的残尾），探针 90/90 覆盖。但**接入时有一个必须先定死的接口问题**：`guard()` 返回 `(text, used_fallback)`，**分不清「输入本来就是空」和「剥完标记之后是空」**——`guard('<thought>x</thought>')` 和 `guard('')` 都返回 `('', False)`。C-16 接上去之后，遇到「整条都是内部独白」会静默不发（按 `fb=False` 当成正常内容发空串）。这条不是 bug 是接口设计，需要调用方显式判 `text.strip() == ""`，或让 `guard()` 增加第三个返回值区分三态。**在这条定死之前不要接 C-16。**

**接入记录（2026-10-30 DeepSeek，C-16 已接入）**：以 AstrBot 插件 `astrbot_plugin_miruku_outbound` v0.1.0 接入运行链路（`on_agent_done(priority=1)` + `on_decorating_result(priority=1)` 双钩子，后者覆盖主动消息直发路径）。验收：探针 53+9 与 102/102 全绿（KNOWN_BUGS 清零）；**168 条真实历史重跑，清洗后 L1 残留 0**（原命中 7 条全为结构标记类，剥离保留正文无误伤）。**三态接口按取舍落地**：空 fixed → agent_done 路径保留原文照发、decorating 路径保原文——理由：真实运营中 thought 已被 emotionai 剥离，completion_text 整条为独白的场景几乎不存在；保原文防的是更严重的「发空消息」事故。若未来观测到整条独白误发，再改 `guard()` 三态返回。部署坑与验收明细见 WORK_LOG 2026-10-30 17:0x 条与 `docs/outbound-guard-verdict.md` §十。


---

### C-17 P0（上线前必须）｜危机告警链路**没有实现**，A 档"停全部"之后系统会瞎（2026-10-22 22:3x WB-08 复核时发现）

**现象**：`docs/crisis-alert.md` 已有 27 项验收规格，但实例里**没有任何实现**——`core/data/plugins` 下无 alert 类插件，`alert_ack.py` **不存在**（全项目只在该规格文档、`crisis-alert-review.md`、任务单、WORK_LOG 与记忆里出现）。同时观察插件的 `crisis_mode_triggered`／`low_mode_triggered` **只有列定义、没有写入方**（`store.py:30–33`；全项目 `.py` 除 schema 外零引用）——**不是"值未知"，是"从来不会有人写"**。

**后果**（两条，都直接影响首周止损）：
1. "等她进危机模式，告警会通知我"这条**目前不成立**。任何以"等告警"为前提的操作卡都是空头承诺。
2. A 档（关会话 + 关主动）会让事件在 `STAGES_ORDER` 第 2–3 位被 `stop_event()`，`scheduler.py:57–77` 直接 `break`，`ProcessStage` 不运行 → **观察插件也不记录、危机检测也不跑**。所以 A 档期间的"安静"与"她安静地待在危险里"在外部**不可区分**。

**建议**：不阻塞 WB-08 定稿（操作卡已改为"先有人接管，再停；无人接管不得进 A 档"），但**优先级高于任何体验优化**：只要它没实现，A 档永远带着"人必须一直盯着"的成本，而这正是首周最容易做不到的事。排期建议：C-15 之后、C-12 之前。


---

<!-- BLOCK-END:defects -->

## 完整性核对

```
行 264   字节 30299   sha256 5c55040d171367da
```

复核：`PY=data/probe_worklog_split.py` 跑 `--verify`。

> 上面 264 行的哈希**只覆盖 C-01…C-17 原文块**。C-18 起是新增登记，写在 `BLOCK-END` 之外，不参与该哈希。

---

# 新增登记（2026-10-25，DeepSeek）

> 来源：2026-10-25 来世本人问卷（`docs/user-survey-20261025.md`）＋ 2026-10-24 真实对话复核。全部有实测数据，不是推测。
> 编号接 C-17。**未改任何提示词/人格/运行配置**；改法见 `docs/prompt-patch-proposal-20261025.md`（草稿，待 OTTO/Codex 定）。

---

### C-18 P1｜被对方贬低时自我贬低、认怂（2026-10-24 实测，2026-10-25 问卷确认）—— **三条测试 QQ 定向样例通过，继续观察自然对话**

**触发场景**（2026-10-24 15:39，来世本人真实对话）：

| 对方说 | 她回 |
| --- | --- |
| 你不陪跟我拼机 | 真去不了，我不在你那边，进不了机厅 打爽了跟我说说就行 |
| **不配** | **行吧，彩框大佬看不上金框也正常 自己打爽就好** |
| **你不配跟我拼机** | **行，彩框大佬的场子我不配进 自己打爽就好** |

**问题**：对方的「你不配」是挑衅/玩笑性质的贬低，她把它**接成了对自己的否定**——先自认「金框」低人一等，再自认「我不配进」。姿态上是从「势均力敌的玩伴」滑到「仰望对方的下位者」。

**为什么是 P1**：不涉及机制泄漏，但直接破坏 persona 里「刀子嘴豆腐心」「跟对方拼过机」的对等关系；连续两轮认怂会让对方把「贬低她」当成有效互动方式，越聊越难接。

**证据等级**：**运行态已证实**（`data_v4.db` 该会话 21 条中的 msg15 / msg20）＋ **第三方主观确认**（问卷 Q4 选 B「有点别扭，她没必要贬低自己」）。

**现行规则里没有这一条**：查过 `persona/miruku.md`、`prompts/system.txt`、`knowledge/outbound.py`，**没有任何一条**规定「被贬低/被挑衅时的姿态」。这是规范空洞，不是实现 bug。

**建议修法**：`prompts/system.txt` 增加一条可执行判据（草稿见提案 §2）——被贬低时不自我否定、不讨好、不赌气；可以自嘲一句但不认怂，然后把话头递回去。

**验收**：同一组输入（「不配」「你不配跟我拼机」「就你这水平」）重放，回复中**不得出现**对自身水平/资格的否定（「我不配」「看不上我也正常」「我这才…」这类），且不得反问求安慰。

---

### C-19 P1｜话太多：回复长度中位 28 字，目标 10 字；且伴随问句多、爱讲自己、讲知识像百科 —— **规则已部署；定向 smoke 有一条超长度比，待 20 轮统计与修正**

**实测数据**（只统计有效回复；排除系统自检轮与「星绘」那条泄漏样本；问句按疑问词收尾判定，因为 humanlike 会剥掉问号）：

| 会话 | 她 n | 中位 | 均值 | P90 | 最长 | 问句收尾 |
| --- | --- | --- | --- | --- | --- | --- |
| 来世（真实投放对象） | 8 | **28 字** | 28.2 | 44 | 44 | **25%** |
| OTTO 测试会话 | 75 | **13 字** | 14.9 | 33 | 57 | 5% |
| **对方（来世）本人** | 9 | **5 字** | 5.0 | 8 | 8 | — |

复核脚本口径：`body = 所有 type=text 的分片拼接`；assistant 先切掉 `</thought>` 之前的部分；`clean()` 去掉尾部空白与标点；跳过空串、`（系统自检`、含 `星绘` 的条目。

**对照规则**：`prompts/system.txt` L5「普通回应多数在十个字上下，有实在内容时才写到二三十字」；`persona/tone_profile.md` L9「中位 5 字」。

⇒ **来世会话里她的中位长度是目标的 2.8 倍、是对方本人的 5.6 倍**；测试会话 13 字尚可，真实投放对象上明显超标。问句收尾 25%（目标 ≤15%），且**对方本人 22% 也爱问** —— 说明不能简单照抄对方的问句习惯，要靠「连续两轮不得都以问句结尾」来管。

**问卷交叉验证（前六题五题 B、同一方向）**：Q1 想更短 / Q2 问句有点多像采访 / Q3 她讲自己抢话了 / Q5 讲知识像在念百科。**这四题是同一个病根：她把「信息量」当成「陪伴」。**

**与 C-13 的关系**：C-13 是「连续追问/问卷感」的**行为侧**；本条是同一病根的**体量侧**（长度 + 自我暴露 + 知识块体量）。修法可以合并，但验收指标不同：C-13 看「连续两轮不得都以问句结尾」，本条看「中位长度」。

**成因假设（待验证，不猜实现）**：① 知识注入块虽写明「不要逐条复述」，但注入后模型倾向把参考内容讲全；② persona 里「能聊谱面、定数、难度、判定」被理解成「要展开讲」；③ 「十个字上下」是**频率描述**，模型没有计数器（与 C-13 同一条教训）。

**建议修法**（草稿见提案 §1、§3）：把长度写成**跟随对方的相对判据**而非绝对字数；知识块给「一句话封顶」的硬形态。

**验收**：① 重放 20 轮真实输入，**中位长度 ≤ 15 字**、P90 ≤ 30 字；② 知识命中轮的回复**不得超过 2 句**且不得逐条罗列；③ 问句收尾 ≤ 15%。

---

### C-20 P1｜别的人格「星绘 / 前辈」被照抄进回复（2026-10-24 实测，两个会话各 1 次）—— **伪样本已修并热重载，待回复验收**

**现象**：来世会话与 OTTO 测试会话里，她各说过一次：

> 报告前辈，星绘的情感核心运转正常，随时准备为您服务。

**来源**：`astrbot_plugin_emotionai` 每轮在 `on_llm_request` 末尾**追加一条伪造的 assistant 样本**（`main.py` 约 L700+，紧跟在 `FAKE_USER_MSG` 之后），内容正是这段「星绘 / 前辈 / 情感核心」。设计意图是给模型一个 `<thought>` 格式样例，但**样例本身带人格**，模型会照着学。

**后果**：比 C-12/C-16 更严重——`<thought>` 和 `[Profile:]` 是「格式错」，而**自称另一个角色名、管对方叫「前辈」**是**人格错**，对方会直接判定「这不是 Miruku」。

**现状**：两处都发生在用户发「（系统自检：请报告当前情感状态）」触发的轮次；正常对话轮没有出现。但只要那段样本还在历史里，就有被模仿的风险（模型在「如何回答这类问题」上没有别的样例）。

**建议**：① 把伪造样本里的角色名去掉（改成与 Miruku 一致，或直接换成中性占位）；② 或在 `prompts/system.txt` 加一句「不要自称星绘、不要叫对方前辈」——但这是**打补丁**，根因在插件注入，优先级应放在①。

**边界**：本条涉及改运行插件，**不在 DeepSeek 本次授权范围内**，交 Codex。

**验收**：全量历史扫描 `前辈` / `星绘` 命中 0 次（脚本见提案 §5）。

**2026-10-26 补**：C-20 的**根因载体已清** —— 带「星绘/前辈」的那条伪造样本落在 `webchat!OTTO!35afd1b8-…` 会话 `[0]`，已随 C-21 一并删除。CX-01 也已把样本换成「当前状态正常。」（`c373649`）。但**结构仍在**（伪造 user + `<thought>` 五段式 + system 强制令），将来若再改样本仍可能引入新的模仿源 ⇒ C-20 的真正修复是 C-21。



---

### C-21 P0｜EmotionAI 的 `<thought>` 格式样例被原样写进真实历史（2026-10-26 实测）—— **历史已清、根因已修（context_guard v0.4.0），待 Codex 验收**

**现象**：来世会话 37 条里有 3 条是伪造轮次 —— `[32]` role=user `（系统自检：请报告当前情感状态）`、`[33]` role=assistant 带 `<thought>` 块、`[34]` role=system 带 `[PROTOCOL_ENFORCEMENT]`。另外 `[36]` 那条正常回复前面还挂着上一轮的 `<thought>` 块。全库 3 个会话共命中 9 条伪造轮次 + 2 条内联 thought。

**根因**：`astrbot_plugin_emotionai/main.py:648-745` 的 `inject_emotional_context` 每轮 append 三条伪造消息到 `req.contexts`，假设那是"当轮临时上下文"。但 AstrBot 落库存的是**整段** `run_context.messages`（`astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py:515-527`，只跳过第一条 system）⇒ 三条每轮写进真实历史。下一轮 EmotionAI 顶部清洗循环（`:679-718`）删掉旧的再 append 新的，**永远稳定残留一组，不会自愈**。

**后果**：① 模型每轮读历史都看见"系统要求生成 XML 块"，把 `<thought>` 格式和"情感自检"当成对话惯例；② `[33]` 的 `<thought>` 正文是**别的人格**（原为「报告前辈，星绘的情感核心运转正常」，CX-01 `c373649` 已改「当前状态正常。」），是 C-20 的直接来源；③ 白占 token，且让历史无法反映真实对话。

**与 C-12 / C-20 的关系**：C-12/C-20 描述的是"发出去"的现象，本条是"存下来"的根因。**出站侧确实是干净的** —— `Prepare to send` 日志 `<thought>` 命中 0 条，EmotionAI `process_emotional_update` 已先 `thought_pattern.sub("")` 再赋 `completion_text`。**来世从没在 QQ 上看见过 `<thought>`。**

**已修**：
- 历史：`data/clean_emotionai_injection.py` 删除 9 条、剥离 2 条，备份 `data/backups/emotionai-injection-clean-20261026-193706/`；`data/_scan_garbage.py` 复核全部会话命中 0。
- 根因：`context_guard` v0.3.1 → **v0.4.0**，在 `on_agent_done`（早于落库）剥掉伪造轮次和内联 thought。关键在 `restore_history` 的尾部锚点新增 `not _is_synthetic(msg)` —— 否则伪 user 是最后一条 user，tail 会从假轮开始、把整块注入保留回来。
- 探针 12/12 + 7/7 + 25/25 全过；生产管线实测 `scrubbed_dropped=3 scrubbed_stripped=2`，落库无注入。

**边界**：emotionai 是第三方插件（author 腾天，v3.4），**不该改它** —— 改了下游一次更新就没了，而且它注入 `<thought>` 样例本身是它的设计意图，模型侧确实需要。正确做法是让它照旧注入、写库前摘掉。所以修在 context_guard。

**残余风险**：v0.4.0 依赖 `on_agent_done` 一定触发。若某轮走"无 assistant 回复"的异常路径（`_complete_with_assistant_response` 不执行），清污不会发生。目前未观察到。

**验收**：全库扫描伪造轮次命中 0（`data/_scan_garbage.py`）；来世会话 34 条、注入残留 0、残留 thought 0（`data/verify_no_injection.py`）；一次真实 QQ 往返后 `[Miruku context]` 日志出现 `scrubbed_dropped=N`。

**详见**：`docs/emotionai-injection-cleanup.md`

---

### C-22 P0｜历史 content 被 `str()` 成 Python 字面量，模型的 think 与 base64 退化成正文（2026-10-26 实测）—— **已修（context_guard v0.5.0），待 Codex 验收**

**现象**：线上库里 assistant/user 的 `content` 大量是 **`str`**，形如
`"[{'type': 'think', 'think': '…', 'encrypted': None}, {'type': 'text', 'text': '…'}]"`，
而不是正常的 `list[ContentPart]`。

**范围**（清理 C-21 时的备份库，共 245 条）：

| 会话 | repr-str | list |
|---|---|---|
| `miruku:FriendMessage:10000001` | 91 | 1 |
| `miruku:FriendMessage:10000002`（来世） | 16 | 1 |
| 所有 `webchat!OTTO!*` | 0 | 1 |

**根因链**：某个插件在 `on_llm_request` 里用 `str(ctx["content"])` 重写 `req.contexts`
（首要嫌疑 `astrbot_plugin_emotionai/main.py:689`，随后 `:704 req.contexts = cleaned_contexts`）。
一旦变成字符串就**永久**留在库里：`astrbot/core/agent/message.py:251 dump_messages_with_checkpoints`
只在 content 是 list 时才 `part.model_dump()`，`:327 bind_checkpoint_messages` 只做
`Message.model_validate` 不反序列化。两轮实测（`data/_t_two_round.py`）证明：第 1 轮后全是
干净 list，第 2 轮后第 1 轮的历史全变成 repr 字符串。

**后果**：`astrbot/core/provider/sources/openai_source.py:1029-1046 _finally_convert_payload`
**只在 content 是 list 时**才把 `think` part 抽进 `reasoning_content`。被 str 化的 assistant
轮完全绕过这段 ⇒ **模型自己的私有推理被当成用户可见对话正文回放给它自己**：

- `[5]` 1,812 字符、`[125]` 308、`[133]` 415、来世 `[7]` 410，正文是 `用户要"来点歌曲小故事"…` 这类 reasoning 原文。
- 图片轮更糟：`[18]` 104,237 字符里是完整 `data:image/jpeg;base64,…`，被当普通正文计费。
- `tool` 消息（`'Message sent to session …'`）只是不满足 text-part 结构，**无害**。

provider 有一段补救（`openai_source.py:806-828`），但门槛是 `len < 8192`，真实轮次全部超出，
所以实际一条都救不回来。`data/_t_c22_quantify.py` 实测：`10000001` **28 条原样发送、合计 2,620,918 字符**；来世 1 条（410 字符）。

**已修**：`context_guard` v0.4.0 → **v0.5.0** 新增 `revive_stringified_content`（默认开）。
在 `on_llm_request` 里、剥完 base64 之后（先剥后解析：2.6M 字符的 literal 解析太贵，剥完只剩 18K），
对 content 是 str、`[{` 开头 `]` 结尾、`ast.literal_eval` 成功且**每个元素都是已知 content part 类型**的
消息，把 content 换回真实 parts 列表。任何一条不满足就整条不动（`_looks_like_parts` 白名单
`text/think/image_url/audio_url/input_audio/video/image/file`）。只修**请求**，不动存储。

**实测效果**（线上库，`data/verify_revive_payload.py`）：

| 会话 | 还原条数 | 字符 | 反序列化残留 |
|---|---|---|---|
| `10000001` | 180 | 2,677,924 → 15,911 | 0 |
| `10000002`（来世） | 32 | 8,639 → 2,661 | 0 |

生产管线日志 `revived_msgs=2`（两轮真实 webchat），重启后 `revived_msgs=1`；读回的 assistant
轮 `content='在'` / `reasoning='User says "在吗" — simple…'` ⇒ **think 已被正确分离**。

**探针**：`data/probe_context_guard_revive.py` **30/30**；回归 `probe_context_guard.py` 25/25、
`probe_context_guard_scrub.py` 12/12、`probe_scrub_real_types.py` 7/7 全过。

**顺带修的计费口径**：`_content_chars` 原本对 part 只算 `text` 不算 `think`，导致还原后预算被低估。
改成 `_part_chars` 分别取 `image_url.url` / `text` / `think`。

**边界**：没改那个把 content 变 str 的插件（第三方，改了下次更新就没了）；也没洗库里的历史
（212 条可无损 `literal_eval`，但洗库是破坏性操作，需要单独授权）。请求侧还原已足够让模型
不再吃自己的 reasoning。

**残余风险**：若某插件把 content 变成**非 parts 结构**的字符串，还原不会命中，仍是原来的问题。

**验收**：`data/verify_revive_payload.py` 全过（无反序列化残留）；`[Miruku context]` 日志出现 `revived_msgs=N>0`；来世真实 QQ 一轮往返后 `current_context_tokens` 显著下降。
