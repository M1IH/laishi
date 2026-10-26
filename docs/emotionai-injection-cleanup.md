# EmotionAI 注入落库污染：定位、清污与根因修复

- **日期**：2026-10-26
- **执行**：DeepSeek
- **触发**：OTTO 在来世会话里看到一句可疑消息，要求判断是否为注入垃圾，确认则删
- **结论**：是。来源是 `astrbot_plugin_emotionai` 的 <thought> 格式样例注入被 AstrBot 原样写进真实历史。已清理 3 个会话、修根因（context_guard v0.4.0）、探针全绿、生产管线实测生效。

---

## 一、先说结论：来世其实什么都没看见

先排除了一个方向——**对方看到的"乱码"不是 `<thought>`**：

| 事实 | 证据 |
|---|---|
| `<thought>` 从未发到 QQ | `respond.stage:233 Prepare to send - 来世/10000002:` 三行日志，`<thought>` 命中 **0** 条 |
| 来世 11:39 只发了两句 | `core.event_bus:116`：`otto？`(11:39:23)、`何意味`(11:39:41) |
| `那堆乱码不用理，聊点别的` 是 **Miruku 自己发的** | `Prepare to send - 来世/10000002:` (11:39:44) |

EmotionAI 在 `process_emotional_update` 里先 `thought_pattern.sub("", orig_text)` 再赋 `resp.completion_text`，所以出站文本是干净的。

**真正的问题是：干净的是"发出去的那条"，脏的是"存进历史的那条"。** 下一轮模型读历史时会看到它们。

---

## 二、根因

`…\core\data\plugins\astrbot_plugin_emotionai\main.py:648-745`
`@event_filter.on_llm_request(priority=100000) async def inject_emotional_context`

每轮往 `req.contexts` 末尾 append 三条**伪造消息**：

| 行号 | role | 内容 |
|---|---|---|
| `:724-727` | `user` | `（系统自检：请报告当前情感状态）`（常量 `FAKE_USER_MSG`，定义在 `:655`） |
| `:729-739` | `assistant` | `<thought>…[感知] 收到系统自检指令…</thought>当前状态正常。` |
| `:742-745` | `system` | `FORCE_MSG`，含 `[PROTOCOL_ENFORCEMENT]` / `REQUIRED ACTION: Generate XML block.`（`:658-675`） |

插件的假设是"这只是当轮的临时上下文"。**但 AstrBot 落库存的是整段 `run_context.messages`**：

```
astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py:515-527
  → 只跳过第一条 system，其余全部 JSON 序列化写进 conversations.content
```

于是每轮都写一组进去。下一轮进来时，EmotionAI 顶部的清洗循环（`:679-718`）把**旧的**三条删掉、再 append **新的**三条 ⇒ 历史里永远稳定残留一组，永远不会自己消失。

配套的清洗正则 `history_clean_pattern`（`:541-544`）：

```python
r"(?:```(?:xml|text)?\s*)?<(?:thought|thinking)>[\s\S]*?</(?:thought|thinking)>(?:\s*```)?|(?:\n*\s*【当前情感状态】[\s\S]*$)"
```

---

## 三、污染范围（清理前全库扫描）

| 会话 | 条数 | 命中位置 |
|---|---|---|
| `miruku:FriendMessage:10000002`（来世） | 37 | `[32]` 伪 user、`[33]` 伪 assistant、`[34]` 伪 system；`[36]` 还带着 `<thought>` 前缀 + 正文「那堆乱码不用理，聊点别的」 |
| `miruku:FriendMessage:10000001`（测试号） | 187 | `[182][183][184]` |
| `webchat:FriendMessage:webchat!OTTO!35afd1b8-…` | 6 | `[0][1][2]`（伪造样本含「报告前辈，星绘的情感核心运转正常」）+ `[4]` |

**`[36]` 那条就是 OTTO 看到的可疑消息，但成因和「残留」不一样——这条必须写清楚。**

它是这一轮她自己生成的，`text` 部分原样是：

```
<thought>
1. 感知：对方又问"何意味"，大概是刚才那串看不懂的东西。
2. 评估：不用解释那些，轻轻带过就好。
3. 代谢：无所谓，平静。
4. 决策：一句短话带过。
5. 更新：joy:1, trust:1
</thought>
那堆乱码不用理，聊点别的
```

`think` 部分（模型自己的 reasoning）里还在盘算「别管那些，我刚才抽风了」——和 `text` 里的五段式毫无关系。

**所以 `<thought>` 不是「上一条残留串进这一条」，是模型被 `[PROTOCOL_ENFORCEMENT]` 那句 `REQUIRED ACTION: Generate XML block.` 直接要求写出来的，且写进了可见的 `text`。** 出站之所以干净，只因为 EmotionAI 的 `process_emotional_update` 在发送前 `thought_pattern.sub("")` 了一遍——**这是唯一的拦截点**。

意义完全不同：这不再是"历史脏"，而是**「只要 EmotionAI 那条剥离路径失效/被禁用/改版，`<thought>` 就会原样发到 QQ」**。C-12 一直没真正解决，只是被一个人的补丁挡着。

---

## 四、修复

### 4.1 历史清污（一次性，已执行）

脚本 `data/clean_emotionai_injection.py`：

- `--dry-run` 只报不写；`--apply` 才写库
- `classify(content, role) -> drop | strip | keep`
  - `drop`：user 含 `（系统自检：请报告当前情感状态）` / system 含 `[PROTOCOL_ENFORCEMENT]` / assistant 含 `收到系统自检指令` 且含 `<thought>`
  - `strip`：其他消息里内联的 `<thought>…</thought>`（含 ```xml 围栏）
- 写库用 `begin immediate` + 异常 rollback
- **先备份**：`data/backups/emotionai-injection-clean-20261026-193706/data_v4.db`（SQLite backup API）

结果：**删除 9 条、剥离 2 条**

| 会话 | 变化 |
|---|---|
| 测试号 | 187 → 184 |
| 来世 | 37 → 34（`[36]` 从 `<thought>\n1. 感知：…` 剥成 `那堆乱码不用理，聊点别的`） |
| webchat OTTO | 6 → 3（`[4]` 剥成 `今晚去不了，我这边上不了线`） |

复核脚本 `data/_scan_garbage.py`：全部会话 `命中 0`。

### 4.2 根因修复：context_guard v0.4.0

**为什么放在 context_guard 而不是改 emotionai**：emotionai 是第三方插件（`author` 非本项目），改它会在下次更新时被覆盖；而且"不让伪造消息落库"本质上是**写库前的最后一道闸**，本来就该由已经接管 `on_agent_done` 的 context_guard 负责。

`plugins/astrbot_plugin_miruku_context_guard/`，v0.3.1 → **v0.4.0**
`main.py` sha256 `224a1de68c2b2e1b7da4e3118f102661f651debc647a396fc740da6e87743597`

**新增常量**

```python
_FAKE_SELFCHECK   = "（系统自检：请报告当前情感状态）"
_PROTOCOL_MARK    = "[PROTOCOL_ENFORCEMENT]"
_FAKE_SAMPLE_HINT = "收到系统自检指令"
_THOUGHT_BLOCK_RE = re.compile(
    r"(?:```(?:xml|text)?\s*)?<(?:thought|thinking)>[\s\S]*?</(?:thought|thinking)>(?:\s*```)?",
    re.IGNORECASE,
)
```

**新增函数**

- `_content_text(content)`：兼容 `str` / `list[dict]` / `list[MessagePart]`，取出纯文本
- `_is_synthetic(msg)`：三项识别（伪 user / 伪 assistant / 伪 system）
- `_strip_thought_inline(msg)`：剥掉内联 thought，剥空返回 `None`

**`restore_history` 重写**

```
1. 取 state / begin 并【无条件】清 extra（原来只在有 original_msgs 时清，会漏）
2. original_msgs 为空 → _scrub_into(run_context, messages)   ← 未裁剪的轮次也清污
3. 否则求尾部锚点，条件新增 `not _is_synthetic(msg)`         ← 关键
4. 拼 head + original_msgs + tail → _scrub_into(..., report=True)
```

第 3 步的 `not _is_synthetic(msg)` 是**这次最关键的一行**。EmotionAI 的伪 user 是列表里**最后一条 user**，如果尾部锚点照旧取"最后一条 user"，`tail_start` 会落在假轮上，把整块注入原样保留回来。

**`_scrub_into(self, run_context, messages, *, original_count=0, tail_count=0, report=False)`**

按配置清污后 `run_context.messages = kept`，日志新增 `scrubbed_dropped=%d scrubbed_stripped=%d`。

`_conf_schema.json` 新增 `scrub_injected_turns`（bool，default `true`）。

### 4.3 时序为什么成立

```
tool_loop_agent_runner.py:204   on_agent_done(self.run_context, llm_resp)
    ↑ 在 :196 self.run_context.messages.append(Message(role="assistant", content=parts)) 之后
internal.py:463                 _save_to_history 读 agent_runner.run_context.messages
```

⇒ **清污确实早于落库**。

---

## 五、验证

### 5.1 离线探针（全绿）

| 脚本 | 结果 | 覆盖 |
|---|---|---|
| `data/probe_context_guard_scrub.py` | **12/12** | T5 还原后无残留、T6 本轮真实问答保留、T7 开关关闭不清污、T8 条数正确、T9 未裁剪轮次也清、**T10 原始历史自带残留也被清**、T11 历史正文不误删、T12 条数 1+5+2 |
| `data/probe_scrub_real_types.py` | **7/7** | 用真实 `Message / TextPart / ThinkPart` 构造，验证生产类型路径；`model_copy` 后仍是 `Message` |
| `data/probe_context_guard.py` | **25/25** | 原 v0.3.1 全部用例，无回归 |

T10 是专门为生产场景加的：`guard()` 跑在 EmotionAI **之前**，所以它 stash 的 `original_msgs` 本身就已经带上轮残留——如果只清 tail 不清 original，等于没修。

探针踩过两个坑，记下来免得下次重踩：

1. `sys.path.insert(PLUGIN)` + `import main` 会加载到错的对象（同名模块冲突）→ 改用 `importlib.util.spec_from_file_location("miruku_context_guard_under_test", PLUGIN/"main.py")`
2. 把 `FakeStar` 当 `self` 传会 `AttributeError` → 改 `object.__new__(guard.MirukuContextGuard)` 直接调 `restore_history`

### 5.2 生产管线实测（未打扰来世）

```
POST http://127.0.0.1:6185/api/v1/chat
  Authorization: Bearer <dashboard JWT>
  {"message": "...", "session_id": "scrub-test-001", "enable_streaming": false}
```

- **必须带 `session_id`**，否则 `{"status":"error","message":"Missing key: session_id or conversation_id"}`
- 走的是 dashboard webchat 路径，**同一套 EmotionAI + context_guard + 落库管线**，不经过 QQ

日志：

```
[Miruku context] history restored for save:
  original_msgs=0 tail_msgs=0 total_msgs=3
  scrubbed_dropped=3 scrubbed_stripped=2
```

落库结构核对（会话 `webchat:FriendMessage:webchat!OTTO!scrub-test-001`）：

| idx | role | 内容 |
|---|---|---|
| 0 | user | `测试清污，回一句就行<system_reminder>…` |
| 1 | assistant | parts = `think`（模型 reasoning）+ `text`（`行，收到`） |
| 2 | `_checkpoint` | `{'id': '064463a7-…'}` |

`think` part 是模型自己的 reasoning 字段，**本来就该在历史里**，不是注入，保留正确。**无 `[PROTOCOL_ENFORCEMENT]`、无 `<thought>` 字面量。**

测试会话已 `delete from conversations where user_id like '%scrub-test%'`（1 行）。

来世会话复验 `data/verify_no_injection.py`：

```
总条数: 34
注入残留: 0
残留 <thought> 的消息: 0
```

### 5.3 部署

- 三文件 `cp` 到实例 `…\core\data\plugins\astrbot_plugin_miruku_context_guard\`，两侧 sha256 一致
- 热重载脚本 `data/reload_context_guard.py`：读 `data/cmd_config.json`（**必须 `utf-8-sig`**，否则 `Unexpected UTF-8 BOM`）的 `dashboard.jwt_secret` 现签 HS256 → `POST /api/v1/plugins/…/reload` → `[200] {"status":"ok","message":"重载成功。"}`
- 日志确认卸旧载新：`Removed handler guard (122)` / `remember_begin (121)` / `restore_history (120)` → `Plugin astrbot_plugin_miruku_context_guard (0.4.0)`

---

## 六、边界与遗留

- **只修了"落库"这一侧**。EmotionAI 仍会往 `req.contexts` 里 append 三条伪造消息——那是它给模型看 `<thought>` 格式样例的**设计意图**，模型侧需要它。真正错的是"以为那是临时的"。所以正确做法就是让它照旧注入、写库前摘掉，而不是禁止它注入。
- **v0.4.0 依赖 `on_agent_done` 一定会触发**。若某轮走的是"无 assistant 回复"的异常路径（`_complete_with_assistant_response` 不执行），则清污不会发生，那轮的三条仍会落库。目前没有观察到这种情况，**但这是残余风险**，无法在 guard 内部兜底。
- **历史里可能还有更早的污染**。本次只清了当前的 3 个会话；归档/备份里的旧库没动（那些不参与运行）。
- **C-20 的根因同一处**：伪造样本里「报告前辈，星绘的情感核心运转正常」在 `webchat!OTTO!35afd1b8-…` 的 `[0]` 已被清掉。CX-01 已把样本改成「当前状态正常。」（`c373649`），但**结构仍在**（`<thought>` 五段式 + 伪造 user + system 强制令），将来若再改样本仍可能引入新的模仿源。

---

## 七、复现 / 复核命令

```bash
# 全库扫描注入残留
python data/_scan_garbage.py

# 干跑（不写库）
python data/clean_emotionai_injection.py --dry-run

# 来世会话专项复核
python data/verify_no_injection.py

# 三个探针
python data/probe_context_guard_scrub.py     # 12/12
python data/probe_scrub_real_types.py        # 7/7
python data/probe_context_guard.py           # 25/25

# 生产链路（会真的跑一轮 LLM）
python data/webchat_ping.py "测试清污" "scrub-test-001"
```
