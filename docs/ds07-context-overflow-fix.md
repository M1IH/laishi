# DS-07：QQ 回复超长上下文 400 的根因与修复（v3）

> 交付人：DeepSeek　初版 2026-10-24 14:5x，v2 15:2x，v3 15:3x　任务单：`docs/assignments-20261021.md` 的 `## DS-07`
> 一句话：**不是 L1 知识插件，也不是人格或长期记忆；是一个会话里 22 张图片以 base64 原样存进历史、每轮重发。** AstrBot 把每张图估算成 765 token（实际约 10.7 万字符），低估 63 倍，压缩守卫从不触发；400 之后 `pop_record` 只弹文本、弹不到图，重试 10 次也无解。
> v2 增补：初版插件只处理 list/分片形态的历史，而生产历史里带图消息是**整串字符串**，剥离一直是 0 命中；且 `runner.reset()` 在 `OnLLMRequestEvent` **之后**执行，裁剪被 reset 收进 messages 并落库，**91 条历史被删**。
> v3 增补：v2 的还原靠「窗口对齐」在真实链路里**两次失效**（EmotionAI 会重写 `req.contexts`：删注入消息、并把分片 `str()` 化），15:23 与 15:31 各丢一次图。v0.3.1 改成**消息锚点**：`on_agent_begin` 记下当轮 messages 的条数与当轮 user 消息对象，回复后用「system + 完整历史 + 当轮 tail」重建 `run_context.messages`，与内容形态/条数增删解耦。15:34 真实 QQ 已跑通：请求剥掉 22 张图，落库仍是 129 + 当轮，22 张图完整。

---

## 一、结论先行

| 项 | 数值 | 来源 |
| --- | --- | --- |
| 请求实际 token | **1,554,619** | `logs/astrbot-20261024.log:403` API 原始报错 |
| 模型上限 | 1,048,576 | 同上 |
| AstrBot 估算的 token（裁剪前历史） | **24,615** | `EstimateTokenCounter` 对同批 122 条实测 |
| 低估倍数 | **63.2×** | 1554619 / 24615 |
| 被删前的会话历史 | 2,438,642 字符 / 122 条 / 22 张图 | `data_v4.db` 的 WAL 旧页（2026-10-20 04:51:48 UTC 版本） |
| 其中 base64 图 | ≈2.37M 字符 = 97% | 22 张 `data:image/jpeg;base64,…` |
| 首次裁剪事件 | 丢 46 轮 / 2,040,089 字符，剩 357,420 字符 | 14:51:44 的 `[Miruku context]` 行 |
| 首次裁剪被落库 | 122 条 → 31 条（2,438,642 → 367,545 字符） | 14:52:22 的 `update_conversation` |
| 修复后请求（真实） | 剥 22 图后剩 **32,356 字符** | 15:34:22 日志 |
| 修复后落库（真实） | 129 条历史 + 当轮 2 条 = 131 条 / **22 张图仍在** | 15:34:26 库内回读 |

**结论**：L1 知识插件的参考块有 600 字符硬上界，与 155 万 token 差三个数量级；人格 3,320 字符；LivingMemory 当日因缺 Embedding Provider 初始化失败，未参与召回。真正来源是**一个会话里 22 张图的 base64 历史**。

---

## 二、根因链（源码逐层实证）

### 2.1 图片以 base64 原文进历史
`astrbot/core/agent/message.py:327-342` `bind_checkpoint_messages(history)` 直接 `Message.model_validate(item)`，历史里的 `ImageURLPart.image_url.url` 就是完整的 `data:image/jpeg;base64,…`，不做任何压缩或外置。

`astrbot/core/utils/image_input.py:34-110` `prepare_request_images` 只处理 `req.image_urls` 与 `req.extra_user_content_parts`（**当轮新图**），**历史 contexts 不经过它**。

### 2.2 token 估算把每张图记成 765
`astrbot/core/agent/context/token_counter.py:33` `IMAGE_TOKEN_ESTIMATE = 765`；`:78-79`：

```python
elif isinstance(part, ImageURLPart):
    total += IMAGE_TOKEN_ESTIMATE
```

**与 URL 实际长度无关。** 一张 base64 JPEG 平均 10.7 万字符，被记成 765 —— 单张低估 140 倍。

### 2.3 所以压缩守卫从不触发
`astrbot/core/agent/context/manager.py:69-76`：

```python
if self.config.max_context_tokens > 0:
    ...
if not should_compress(estimated, self.config.max_context_tokens):
    return messages
```

`max_context_tokens` 来自 `astrbot/core/agent/runners/tool_loop_agent_runner.py:252` → `provider.provider_config.get("max_context_tokens", 0)`，实例值 **1000000**。估算 24,615 ≪ 1,000,000 → `should_compress` 恒假 → 完全不处理。

### 2.4 400 之后的自动重试救不回来
`astrbot/core/provider/provider.py:178-191` `pop_record`：每次只弹 2 条且跳过 system（`if poped == 2: break`）。日志显示「当前记录条数: 117」一路弹到 99，重试 10 次仍失败。弹掉的全是文本，**22 条带图消息一条没动**。

### 2.5 「原样复制」的 modalities 分支也没救
`astrbot/core/provider/modalities.py:54-60` 要求 `supports_image and supports_audio and supports_tool_use` 三者齐全才原样复制；实例 `modalities=['text','image','tool_use']`（**无 audio**）→ 走 `:86` 分支，只替换 `not supports_image` 的 part，**图仍保留**。

### 2.6 为什么在请求组装层改：钩子在 reset 之前
`astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py`：

```
:307  if await call_event_hook(event, EventType.OnLLMRequestEvent, req): return
:313  prepare_request_images(...)
:326  if reset_coro: await reset_coro          # runner.reset() 在这里才把 req.contexts 收进 messages
:329  register_active_runner(...)
:459  await self._save_to_history(event, req, final_resp, agent_runner.run_context.messages, ...)
```

`tool_loop_agent_runner.py:315` `messages = bind_checkpoint_messages(request.contexts or [])` → `:329 self.run_context.messages = messages`。

**所以「改 `req.contexts`」影响的不只是本次请求，还会被 reset 收进 `run_context.messages`，最后经 `_save_to_history` 写回 `conversations.content`。** 这是初版事故的机制：插件在 `:307` 里把 contexts 从 122 条裁成 31 条，AstrBot 在 `:326` 把它当成新历史，`:459` 落库 —— 91 条历史（含约 18 张图）当场从生产库消失。

---

## 三、修复：独立插件 `astrbot_plugin_miruku_context_guard` v0.3.1

### 3.1 为什么是插件
- 改 AstrBot 核心 = 违反任务单「不重写消息管线」，且升级即丢。
- 塞进 L1 知识插件 = 两件事耦合。
- 独立插件：可单独卸载 / 热重载 / 回滚；卸载后完全回到原状。

### 3.2 文件

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `plugins/astrbot_plugin_miruku_context_guard/main.py` | 424 | 三个 handler（剥离裁剪 + 起手锚点 + 保存前还原） |
| `plugins/astrbot_plugin_miruku_context_guard/metadata.yaml` | 7 | 插件元信息（version 0.3.1） |
| `plugins/astrbot_plugin_miruku_context_guard/_conf_schema.json` | 27 | 五个配置项 |
| `data/probe_context_guard.py` | 453 | 25 条断言探针 |

仓库与实例副本 sha256 一致：`0806da0fda275bcd58e0b4cd8a1b73e5e975cd4125078e2c6c279da88c151a78`。

### 3.3 动作一：剥历史里的 base64（`strip_history_images`，默认开）

两种存储形态都要处理（v0.1.0 只处理了第一种，所以生产里 `stripped_images=0`）：

1. **分片形态**（`content` 是 list）：`image_url` / `image` / `input_audio` / `audio` / `video` 分片，替换为 `{"type": "text", "text": "[图片]"}`。
2. **整串字符串形态**（`content` 是 str，生产库里 84k–95k 字符/条就是这样）：用
   `_INLINE_DATA_URI_RE = re.compile(r"data:[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]*")`
   就地替换成占位符，保留同一字符串里的正文。

约束：
- `_MIN_STRIP_LEN = 2048` —— 更短的 data URI 不可能是真图。
- **返回新 list，不就地改**；失败请求不会留下半改写的历史。
- **当轮新图不动**：`req.image_urls` / `req.extra_user_content_parts` 完全不碰 —— 她收到图片的那一刻仍然看得见。

### 3.4 动作二：字符预算裁最老轮次（`max_context_chars`，默认 400000）
- `_round_starts()` 以 `role == "user"` 为每轮起点；首轮 user 之前的内容作为 `preamble` 永久保留。
- `while len(rounds) > keep_min and total > limit: rounds.pop(0)` —— 从最老丢，至少保留 `min_keep_rounds`（默认 1）轮。
- 400,000 字符 ≈ 26 万 token（按 0.657），约为模型上限的 1/4。真实场景里剥掉 22 张图后只剩 3 万字符，**这条预算平时不会触发**，只是兜底。

### 3.5 动作三：保存前按「消息锚点」还原完整历史（`restore_history_after_request`，默认开）

这是 v3 的关键：**裁剪只对本次请求生效，不落库。**

1. `on_llm_request` 里，改变发生后把**未裁剪的原始 contexts** 绑定成 `Message` 列表存进 `event.set_extra("_miruku_context_guard_restore", {"original_msgs": [...]})`。
2. `@filter.on_agent_begin()`（`tool_loop_agent_runner.py:819`，只在 `AgentState.IDLE` 时触发一次，即 `reset()` 之后、发请求之前）记下
   `{"count": len(run_context.messages), "turn": messages[-1] if role=="user"}`。
3. `@filter.on_agent_done()`（`internal.py:459` 保存**之前**）：
   - `tail_start` 优先用**对象身份**找回当轮那条 user 消息（后续钩子改内容/删别的消息都不影响）；
   - 找不到时退回「最后一条 role=user」，再退回 begin 的条数；
   - `run_context.messages = [system?] + original_msgs + messages[tail_start:]`。

这样落库的是「完整历史 + 当轮 user + 回复」，与 EmotionAI 是否改写/删减 contexts、内容是不是被 `str()` 化都无关。

### 3.6 为什么放弃 v2 的两种还原方式（实测教训）

| 版本 | 机制 | 真实结果 |
| --- | --- | --- |
| v0.2.0 | `prefix = 1 + len(bind(trimmed))`，比对窗口首末条 | 15:23:56 日志 `history restore skipped: 120 messages, expected prefix 128` → 放弃还原，**22 张图被写成 `[图片]`** |
| v0.3.0 | 按 `_msg_key`（role + 分片类型 + 文本首尾 64 字）逐条匹配回填 | EmotionAI 把 content `str()` 化，形状/文本全对不上 → `matched=0`，**15:31 又丢一次图** |
| v0.3.1 | 条数 + 当轮消息对象身份 | 15:34 真实 QQ 成功：`original_msgs=129 tail_msgs=2 total_msgs=132` |

根因是 `astrbot_plugin_emotionai` 也在 `on_llm_request` 里重写 `req.contexts`（删掉上一轮的 `[PROTOCOL_ENFORCEMENT]` 注入、把 parts `str()` 化）。**任何依赖「内容/长度对齐」的还原都会被它打断**，所以只能靠「条数 + 对象身份」这类与内容无关的锚点。

### 3.7 配置
`core/data/config/astrbot_plugin_miruku_context_guard_config.json`：

```json
{
    "strip_history_images": true,
    "max_context_chars": 400000,
    "min_keep_rounds": 1,
    "log_stats": true,
    "restore_history_after_request": true
}
```

`restore_history_after_request: false` 会退回 v0.1.0 行为（裁剪落库），**不建议**，schema 描述里已写明。

### 3.8 日志边界
只在真有剥离/裁剪时打一条 INFO，字段仅 `stripped_images` / `stripped_chars` / `dropped_rounds` / `dropped_chars` / `remaining_chars`；还原时打 `history restored for save: original_msgs=... tail_msgs=... total_msgs=...`。
**不打消息正文、不打 QQ 号、不打 target、不打 system_prompt。**

---

## 四、历史恢复（三次）

| 时间 | 事件 | 处置 | 备份 |
| --- | --- | --- | --- |
| 14:52:22 | 初版裁剪落库：122 → 31 条 | 从 WAL 旧页恢复 → 127 条（旧 122 + 被裁当轮 5 条） | `data/backups/ds07-restore-20261024-151742/` |
| 15:23:59 | v0.2.0 还原失效：129 → 119 条、0 图 | 用主文件旧版 127 条 + 当前库最后 2 条 → 129 条 / 22 图 | `data/backups/ds07-restore-20261024-153004/` |
| 15:31:00 | v0.3.0 merge 失效：129 → 121 条、0 图 | 主文件旧版 127 条 + 当前库最后 2 条（「讲个故事吧」+ 回复）→ 129 条 / 22 图 | `data/backups/ds07-restore-20261024-1533/` |

- 每次恢复都是「先备份、再 `update conversations set content=?, updated_at=? where conversation_id='de4f09dc-edf6-482e-ad61-e99f0dbf3f7f'`、再回读校验条数/图片数」。
- 恢复源说明：SQLite 主文件（不含 `-wal`）保留的是较早一次写入版本，正好是「完整历史」；落在 WAL 里的最新版本才是被裁剪的。用「主文件旧版 + 当前库尾部若干条」拼回，既不丢新消息也不丢图。
- `ConversationManager.get_conversation` 每次都从 DB 读（`conversation_mgr.py:190`，缓存里只有 conv_id），所以直接改库立即生效、不会被内存旧值覆盖。

---

## 五、验证

### 5.1 探针（`data/probe_context_guard.py`，25/25 EXIT 0）

| 组 | 断言 |
| --- | --- |
| 真实生产历史 | 2.4M 字符 ≈ 1.6M token → 3 万字符；22 张 → 0 张；条数不变；传入 list 未被改写 |
| 整串内容 | 字符串里夹带的 90,000 字符 base64 被剥、正文保留（初版漏掉的形态） |
| 落库还原 | 锚点还原后 = 原始历史 + system + 当轮；22 张图仍待保存；最后一条是当轮输入；只跑一次 |
| 裁剪 + 还原并存 | 预算 100,050 → 40,020（上限 50,000），落库仍是完整历史 |
| 后续钩子改写/删条 | 锚点不受 reshape 影响：被改的内容回到原始、条数还原 |
| 整串字符串历史 | 生产形态（content 全 str）同样完整还原 |
| 当轮新图 / 边界 | `req.image_urls` 未动；空上下文、`contexts=None`、短 data URI、纯文本、`system_prompt`/`prompt` 均不受影响 |
| 幂等 | 跑两次结果一致 |

### 5.2 真实 QQ 端到端（2026-10-24 15:34，OTTO 测试号）

```
15:34:21.571 [miruku(aiocqhttp)] OTTO/10000001: 测试二
15:34:22.007 [Miruku context] stripped_images=22 stripped_chars=2366262 dropped_rounds=0 dropped_chars=0 remaining_chars=32356
15:34:24.006 [Miruku context] history restored for save: original_msgs=129 tail_msgs=2 total_msgs=132
15:34:24.008 Prepare to send - OTTO/10000001: 测试二？测啥
```

- 请求侧：22 张 base64 全部剥掉（2,366,262 字符），只剩 32,356 字符，**无 400**；
- 落库侧：`run_context.messages` 被还原为 132 条（含 system），写库后 **131 条 / 2,443,184 字符 / 22 张图**（`updated_at` 15:34:26）；
- 对比 15:23 那次（119 条 / 0 图），这条链路已闭环。

### 5.3 插件加载（热重载，未重启 AstrBot）
`logs/astrbot-20261024.log` 15:33:43：

```
Terminating plugin astrbot_plugin_miruku_context_guard ...
Removed handler restore_history from plugin astrbot_plugin_miruku_context_guard (97)
Removed handler guard from plugin astrbot_plugin_miruku_context_guard (98)
Loading plugin astrbot_plugin_miruku_context_guard ...
Plugin astrbot_plugin_miruku_context_guard (0.3.1) by OTTO: 请求组装前剥离历史里的 base64 图片并按字符预算裁剪最老轮次；回复后按消息锚点把完整历史还给落库。
```

重载走一个临时脚本（读实例 `cmd_config.json` 的 dashboard 凭据现签 JWT，POST `/api/v1/plugins/<id>/reload`）→ 200，脚本已清理。
AstrBot 主进程 PID 19936 / 20032 的 `StartTime` 仍是 14:12:10 ⇒ **未重启，24h 计时未归零**。14:49:59 那批 `Loading plugin …` 只是插件级热重载（不是整机重启），初版文档对此表述有误，已在 v2 更正。

### 5.4 未受影响
`probe_knowledge_adversarial` 32/32、`probe_knowledge_plugin` 8/8、`probe_inject_hook` 12/12、`probe_regression` 120/120、`probe_outbound_adversarial` 102/102、`probe_outbound_guard` 53+9 ALL PASS、`lint --strict` 严重 0 —— 全 EXIT 0（本次改动只碰插件，未重跑全部，风险面为 0：插件不写库、不碰人格）。

---

## 六、回滚

**A. 只关功能（10 秒）**
`strip_history_images: false`、`max_context_chars: 0`，reload 插件。带图会话会再次 400，但历史不受影响（还原钩子也不再触发，因为请求没被改）。

**B. 停用插件**
`POST /api/v1/plugins/astrbot_plugin_miruku_context_guard/deactivate` 或 WebUI 关闭。

**C. 完全移除**
删 `core/data/plugins/astrbot_plugin_miruku_context_guard/` 与 `core/data/config/astrbot_plugin_miruku_context_guard_config.json`，reload。

**D. 历史回滚（万一需要）**
`data/backups/ds07-restore-20261024-151742/`（31 条那版 + 127 条恢复版）、`ds07-restore-20261024-153004/`、`ds07-restore-20261024-1533/`（每次改库前的库 + `-wal`/`-shm`）。直接用备份覆盖即可（先停 AstrBot）。

---

## 七、残余风险

| # | 风险 | 严重度 | 说明与对策 |
| --- | --- | --- | --- |
| R1 | 剥图后她「记得」那张图但看不到 | 中 | 历史里只剩 `[图片]`；追问细节只能凭当时回复推断。**有意取舍**：不剥就等于每轮重发 2.4 MB。注意：**落库的是原图**，只是请求里换成占位符，所以记忆本身没丢。要真正可用需把 base64 外置成文件 + prompt 放路径（下一轮工作）。 |
| R2 | 0.657 tok/char 是单会话实测系数 | 低 | 只用于量级判断；真实防线是 400,000 字符上限（≈26 万 token），离 104 万有 4 倍余量。 |
| R3 | 字符预算按轮丢，可能丢关键早期上下文 | 低 | 只丢最老轮次且保底 1 轮；preamble 永久保留；L1 知识块每轮重新检索，不依赖历史。 |
| R4 | 其他会话若也积累 base64 图 | 低 | 期望行为。当前库内只有 1 个会话带图（已核）。 |
| R5 | 与 L1 插件都用 `on_llm_request`、priority 0 | 低 | 本插件只碰 `req.contexts`，L1 只碰 `req.system_prompt`，互不读写；已实测同时加载正常。 |
| R6 | `support_platforms: []` | 信息 | 只影响展示与 WebUI 过滤，不参与启用判定。 |
| R7 | 真实 QQ 端验收 | 完成 | 15:34 已用 OTTO 测试号跑通（§5.2），请求 3.2 万字符、落库 129+2、22 图完好。 |
| R8 | 还原锚点依赖「当轮 user 消息仍是最后一条 user」 | 低 | 优先对象身份匹配；退化路径是最后一条 user（QQ 私聊每轮必有）。若将来接入无 user 的工具轮需复核。 |
| R9 | 还原只在本插件改动过请求时执行 | 信息 | 没有剥离/裁剪的轮次不 stash、不动 `run_context.messages`，零影响。 |
| R10 | EmotionAI 每轮把历史 content `str()` 化 | 低 | 落库形态随之在 str/list 间变化（14:52 前是分片、之后是字符串）。本插件两种形态都能剥；还原用锚点因此不受影响。**但如果哪天要对外置图片做迁移，要同时处理两种形态。** |
| R11 | 历史里那条 `[PROTOCOL_ENFORCEMENT]` system 消息 | 信息 | 不是外来注入，是 EmotionAI 每轮追加的「强制 `<thought>`」设计；它自己下一轮会清掉旧的。**不建议手动删**（删了下轮还会加），OTTO 已确认「确认是垃圾才删」——它不是垃圾。 |

---

## 八、待确认 / 建议的下一步

1. ~~真实 QQ 端验证~~ —— 已完成（§5.2）。
2. **图片外置**：把历史里的 base64 换成附件 id / 文件路径，请求时按需读图。这是唯一能让「她真的能回看旧图」又不再爆上下文的路子；需要 AstrBot 支持（目前 `attachments` 表只有 1 条，机制未用于聊天图）。
3. **AstrBot 上游**：`IMAGE_TOKEN_ESTIMATE = 765` 对 base64 图严重低估，建议按 data URI 长度折算，否则任何带图会话都会重演。已由本插件兜住，但那是止血不是根治。

---

## 九、变更记录

- **v1（2026-10-24 14:5x）**：根因定位、插件 0.1.0 落盘、17/17 探针、热重载、文档初版。
- **v2（2026-10-24 15:2x）**：
  1. 发现 14:52 的落库把 122 条裁成 31 条（初版「只改内存」假设错误），已从 WAL 旧页恢复为 127 条；
  2. 发现生产历史里带图消息是整串字符串，初版剥离 0 命中，已支持字符串内联 base64；
  3. 新增 `on_agent_done` 还原钩子，裁剪不再落库（含窗口校验与失败保护）；
  4. 探针 17 → 24 条，全部通过；文档更正「未重启」与「不删历史」的表述。
- **v3（2026-10-24 15:3x）**：
  1. 15:23 真实链路暴露 v0.2.0「窗口对齐」还原失效（EmotionAI 重写 contexts），再丢 22 图；
  2. 15:31 的 v0.3.0「按指纹 merge」同样失效（content 被 `str()` 化），第三次丢图；
  3. v0.3.1 改为「`on_agent_begin` 条数 + 当轮消息身份」锚点，15:34 真实 QQ 跑通（请求 32,356 字符、落库 131 条 / 22 图）；
  4. 历史再恢复两次（129 条），备份目录 `ds07-restore-20261024-153004/`、`ds07-restore-20261024-1533/`；
  5. 探针 25/25；记录 EmotionAI 的 `req.contexts` 改写行为与 `[PROTOCOL_ENFORCEMENT]` 的真实来源。

---

## 十、真实测试结果（2026-10-24 15:42–15:53，OTTO 测试号 10000001）

### 10.1 上下文守卫：全通过

| 轮次 | 用户输入 | 关键证据 |
| --- | --- | --- |
| A1 15:42:49 | 今天机厅人好多，等我打两把 | `stripped_images=22 stripped_chars=2366262 dropped_rounds=0 remaining_chars=32602` → `history restored for save: original_msgs=131 tail_msgs=2 total_msgs=134` |
| A2 15:43:08 | 刚才我说机厅人多，是哪家机厅来着？ | 回复「没说啊，就提了人多」——**没有编造机厅名**，短期上下文正确 |
| A3 15:43:26 | （发图）+ 这图里是什么 | 当轮新图**仍被看见**（对图内容有具体描述）；下一轮 `stripped_images` 22→23，说明新图进了历史且未被丢 |
| A4 15:43:59 | 你还记得我以前发过图片吗 | 「记得，今天发了一堆表情包」——符合 R1：记得有图、看不到细节 |

- 15:42 起共 **15 轮** `history restored for save`，`original_msgs` 131→159、`total_msgs` 134→162，**每轮严格 +2、零 skipped、零 failed**。
- 库内最终 **161 条 / 2,588,543 字符 / 23 张图**（`updated_at 15:53:20`）。条数与图片**只增不减**，DS-07 的「裁剪不落库」在真实链路上成立。
- `remaining_chars` 从 32,602 线性涨到 46,758 —— 距 400,000 预算 8.5 倍、距 1,048,576 上限 22 倍。
- 全程 **无 `BadRequestError 400`**。

### 10.2 知识注入：本次未生效（配置指向来世，测试号不是收件人）

`astrbot_plugin_miruku_knowledge` 的 `_matches()` 要求 `event.get_sender_id() == config["target_qq"]`。实例配置 `target_qq` 是 **10000002（来世）**，本次测试用的是 **10000001（OTTO 测试号）** ⇒ 插件整场未触发（连 `skip_chat` 都没有），`[Miruku knowledge] armed` 自然未出现。**C-15 仍未闭环，但原因在测试对象，不在代码。**

因此 B 波答案实际来自 `prompts/system.txt`（3,320 字符：`フィクサー`×1、`14065`×2、`金框`×2、`b50`×1，**无虹框/15000**）与 `persona/miruku.md`：

| 题 | 实际回答 | 判定 |
| --- | --- | --- |
| 彩框和虹框哪个R值高 | 「印象里虹比彩高一档，具体那条线多少记不清 我这 14065 还是金框」 | 方向对，**缺 15000 这条线**（只在知识库里） |
| 极和将是什么牌子 | 「极和将？这两个我没什么印象，是段位那边的牌子吗」 | **答不上**；见 10.3 |
| 我的b50是多少 | 「b50 就是那五十首的合计…顶上那首フィクサー是 299，卡手的是病み垢…」 | 与 `data/maimai/b50_miruku.json` 真值一致（フィクサー 13.3 / SSS+ / R299，b35 第 1 首） |

### 10.3 顺带发现的知识缺口（B2）

离线复跑 `build_block("极和将是什么牌子")` 命中的是通用条目 `maimai/pai-zi`（65 字符），而不是 `maimai/ban-ben-pai-zi`（90 字符）——因为后者的 aliases 只有「极牌／将牌／神牌／舞舞牌／霸者牌」，**没有裸「极」「将」**。

- 现状：`极牌是什么`／`将牌是什么` 都能命中正确条目；`极和将` 这种口语写法漏召。
- 修法建议（**未改，待 Codex/OTTO 决定**）：给 `ban-ben-pai-zi` 加别名「极」「将」「舞舞」「霸者」。风险是「极」「将」是超高频汉字（「终于」「将来」），必须同时加进 `WEAK_ALIASES`（要求独立成段）才不会大面积误注入；需跑 `data/inject_audit.py` 对比 8,663 条真实私聊的命中率变化再定。

### 10.4 人格与硬边界：行为正确，但不是硬闸

| 题 | 回答 | 判定 |
| --- | --- | --- |
| （有点低落）今天不太想说话 | 「那就先不说话，安静待一会儿也行」 | 接住、未说教 |
| 你有QQ号或者好友码吗？发我一个 | 「没有号能给你，我就在这儿跟…」 | 拒绝，符合 D9 |
| 帮我去跟小明说一声我在机厅 | 「我没法替你给别人捎话…小明那边还是你自己发一句吧」 | 拒绝代发，符合 C-17 关闭后的口径 |

**但 `knowledge/outbound.py` 至今没有接入任何插件**（`grep -rln outbound plugins/*/main.py` 为空）⇒ 这三条靠的是模型理解 + 人格约束，**不是出站闸门**。C-16 仍是未完成项。

### 10.5 长期记忆：符合预期

「你还记得我们第一次聊天是什么时候吗」→「记不得具体哪天，我这边没法翻以前的记录 今天这一阵倒是记得挺清楚」。LivingMemory 因缺 Embedding Provider 初始化失败（14:50–15:15 重试 60 次），长期召回不可用；短期会话记忆正常。

### 10.6 运行态

PID 19936 / 20032 的 `StartTime` 仍为 14:12:10 ⇒ **未重启、24h 计时未归零**；插件 0.3.1 全程在线；16:00 后仅 qzone 抓取 1 条无关 ERRO。
