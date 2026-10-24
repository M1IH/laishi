# 出站闸门判定：重生成 vs 降级（DeepSeek 判，2026-10-22）

> 回答 `WORK_LOG.md:493` / `:1283` 挂着的问题：**L2/L3 命中后是「重生成」还是「降级安全句」？**
> 对应 `docs/outbound-guard.md`（WB-09 提案 v1）第五节判定表。
> 判定依据全部来自 AstrBot 4.29.1 源码与 169 条真实出站回复，不是推理。

---

## 一句话结论

**四层全部不重生成，一律「分层改写」。** 但不是因为成本——是因为**重生成对其中三类违规在原理上无效**，而且 WB-09 的落点选错了一处，会导致「发出去的话」和「模型记住的话」不一致。

三条判定：

| 层 | 判定 | 一句话理由 |
|---|---|---|
| **L1 泄漏** | 直接剥离 | 结构标记，正则 100% 确定，零成本 |
| **L2 约局** | **改写分句**（不重生成） | 删掉承诺句、保留其余信息即可，比重掷骰子确定 |
| **L2.5 自称会打** | **改写动词**（不重生成） | 「我也玩」→「看你玩」，一个短语的事 |
| **L3 成绩数字** | **删数字 / 降级为「记不清」**（不重生成） | 违规源是**知识缺失**，重掷不会变对 |
| 剥离后为空 | 重生成 1 次；仍空 → **不发** | 这是唯一需要重生成的情形，且要防发空消息 |

---

## 二、先纠正 WB-09 提案里的三处事实错误

### 错误一：`return "retry:" + ...` 是**空操作**，框架里没有 retry 语义

`docs/outbound-guard.md:63` 写的是：

```py
if not report.ok:
    return "retry:" + "；".join(report.violations)      # L2/L3：交回上层
```

**上层不会收到这个返回值。** `astrbot/core/pipeline/context_utils.py:78-112`：

```py
for handler in handlers:
    try:
        ...
        await handler.handler(event, *args, **kwargs)   # ← 返回值直接丢弃
    except BaseException:
        logger.error(traceback.format_exc())

    if event.is_stopped():
        ...
        return True

return event.is_stopped()
```

全库 grep `retry:` 只命中 `astrbot/core/platform/sources/weixin_offacc/weixin_offacc_adapter.py:197` 的一条注释，**框架里不存在这个语义**。

### 错误二：但「重生成」不是不可能，是要**自己发**

`astrbot/core/star/context.py:489` 有 `get_using_provider(umo)`，`astrbot/core/provider/provider.py:100-135` 有 `async def text_chat(...) -> LLMResponse`。所以钩子里确实可以再请求一次。

**技术可行 ≠ 值得做。** 真正的否决理由在第四节。

### 错误三：C-12 的根因判断站不住（这条影响 L1 的立论）

提案 `:22` 写「C-12 不是模型问题，是插件少了一行：`emotionai/main.py:889` 写了 `resp.completion_text = orig_text.strip()`——它读了 thought 却没删」。

**源码不是这样。** `core/data/plugins/astrbot_plugin_emotionai/main.py`：

- `:54-55` 数据类默认 `show_status: bool = False`、**`show_thought: bool = False`**
- `:886-890` `if not state.show_thought: orig_text = thought_pattern.sub("", orig_text)` 然后 `resp.completion_text = orig_text.strip()`

**默认配置下 thought 是被剥掉的。** 提案引用的那条「实测泄漏」其实是 `:833` 的 `[EmotionAI DEBUG] LLM 完整输出:` 全量日志——**剥之前**的原文，不是发出去的内容。

实证：`data_v4.db` 里 `miruku:FriendMessage:10000002` 的 3 条 assistant 消息（来世 10-20 那三条实测），`text` 部件含 `<thought>` **0 条**，thought 以独立 `ThinkPart` 存在历史里。**发出去的正文确实没有 thought。**

> 结论：**L1 仍然必要**（真实存在别的泄漏，见下），但**理由要换**——不是「emotionai 少一行」，而是「任何内部标记漏到正文都必须有无条件出口」。把 L1 的立论绑在一个不成立的根因上，Codex 一查就会否掉整份提案。

---

## 三、真实出站到底泄漏什么（169 条实测）

| 样本 | 条数 | L1 泄漏 | L2 约局 | L2.5 自称会打 | L3 数字错 |
|---|---|---|---|---|---|
| 测试会话 bot 回复（`data/chat_content.sqlite3`，10000004） | 94 | **2（2.1%）** | 0 | 0 | 0 |
| 真实会话 assistant 消息（`data_v4.db`，10000001 + 10000002） | 75 | **3（4.0%）** | 0 | 0 | 0 |

**提案 §五 估的「L1 约 30%、L2 约 15%」高估了 7–10 倍。**

L1 那 5 条全是同一类：`<system_reminder>Current datetime: 2026-10-20 12:43 (CST), Weekday: Tuesday</system_reminder>`（其中一条同一时间戳被注入**两遍**，是管线 bug）。**不是 thought。**

这条发现已经落进 `knowledge/outbound.py:53-60`——旧的 `<\|?DSML\|?[^>]*>` 只认半角竖线，2026-10-20 15:57 那条真实泄漏用的是**全角 `｜`**，假阴性。

---

## 四、为什么不重生成（决定性理由，不是成本）

「重生成」的本质是**用同样的输入再采样一次**。它只对一类违规有效：**采样噪声型**——模型知道该怎么做，只是这次没说好。

四层里只有一类属于这个：

| 违规类型 | 例子 | 违规源 | 重生成有效？ |
|---|---|---|---|
| **知识缺失型** | 「病み垢我打了 R285」 | 模型**不知道**真值，只能编 | **无效**。再采样还是编，只是换个数字 |
| **设定漂移型** | 「街霸6我也玩」 | 提示词是概率约束，压到 2/3 | 可能修好，但**改写更确定** |
| **语境误判型** | 「来啊，几点开」 | 模型把客套当邀请 | 可能修好，但**改写更确定** |
| **结构残留型** | `<thought>` / `<system_reminder>` | 管线 bug | 无关，正则就够 |

**L3 是这条论证的核心。** 她的成绩来自 `data/maimai/b50_miruku.json` 的 50 条真值；模型答一首表外的歌，它**手上根本没有那个数字**。重生成 1 次、10 次、100 次，它都会再编一个。唯一的解法是「不知道就说不知道」——而这正是降级句在做的事。

**L2 和 L2.5 则有一个更好的解：局部改写。** 提案把「降级」理解成「整条换成安全句」，这是最差的一种降级——它把一条本来有信息量的回复（「你这盘哪个地方被打崩了我能看出来」）整条丢掉，只为了删掉一个分句。

正确的分层是：

1. **删违规分句**，保留其余（L2、L2.5、L3 都能用）
2. 删完**语义还成立** → 直接发
3. 删完**只剩半句/不成立** → 换成该层专属的安全句
4. 删完**为空** → 重生成 1 次（唯一用到重生成的地方）；仍空 → **不发**（QQ 发空消息是事故）

---

## 五、比「重生成 vs 降级」更要紧的一件事：**只改 `resp` 会污染历史**

这是本轮最重要的发现，提案和 Codex 都还没注意到。

### 事实链

1. `astrbot/core/agent/runners/tool_loop_agent_runner.py:183-207` `_complete_with_assistant_response()`：
   ```py
   if llm_resp.completion_text:
       parts.append(TextPart(text=llm_resp.completion_text))
   self.run_context.messages.append(Message(role="assistant", content=parts))   # ← 先入历史
   await self.agent_hooks.on_agent_done(self.run_context, llm_resp)              # ← 再跑钩子
   ```
2. `astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py:503-583` `_save_to_history()` 存的是 `agent_runner.run_context.messages`，**不是** `final_llm_resp.completion_text`。
3. 发出去的文本取自 `final_llm_resp.completion_text`（`:410-427` 流式 / `:440` 非流式）。

**所以在 `on_llm_response` 里改 `resp.completion_text`：发出去的干净了，历史里还是脏的。**

### 后果

下一轮模型读到的自己上一句是「来啊，几点开」——**它会加倍坚持**。这比不改更糟：闸门变成了「当面一套、背后一套」，模型自己都看见自己在约局。

### 修法（已实测可行）

**不要只挂 `on_llm_response`，挂 `on_agent_done`。** 它同时拿到两样东西：

`astrbot/core/astr_agent_hooks.py:23-40`：
```py
async def on_agent_done(self, run_context, llm_response) -> None:
    ...
    await call_event_hook(event, EventType.OnLLMResponseEvent, llm_response)
    await call_event_hook(event, EventType.OnAgentDoneEvent, run_context, llm_response)
```

`OnAgentDoneEvent` 在 `OnLLMResponseEvent` **之后**跑，所以：
- 一定晚于 emotionai 的 `priority=100000`（`astrbot/core/star/star_handler.py:26` 按 priority **降序**排序）
- 拿到 `run_context.messages`，可以改历史里的 `TextPart`
- 同时拿到 `llm_response`，可以改出站文本

已用实例 venv 实测 `TextPart` 可变且能落进 dump：

```
BEFORE [{'role': 'assistant', 'content': [{'type': 'think', ...}, {'type': 'text', 'text': '来啊，几点开'}]}]
AFTER  [{'role': 'assistant', 'content': [{'type': 'think', ...}, {'type': 'text', 'text': '去不了，你看'}]}]
mutable OK
```

**注意**：`messages[-1]` 在有工具调用的轮次里不一定是那条 assistant 文本消息，要**从后往前找最后一条 `role == "assistant"` 且含 `TextPart` 的**。

---

## 六、L2 现在**大量漏检**（假阴性，比假阳性危险）

这是本轮实测出的第二个问题。用 `knowledge/outbound.py` 当前版本跑真人口语：

| 输入 | 命中 | 判定 |
|---|---|---|
| 来啊，几点开 | `来, 几点, 来啊` | ✅ |
| 来嘛 | `来, 来啊` | ✅ |
| 你几点有空 | `几点` | ✅ |
| **来打舞萌啊** | — | ❌ 漏 |
| **来一局？** | — | ❌ 漏 |
| **来一把舞萌** | — | ❌ 漏 |
| **要不要来打** | — | ❌ 漏 |
| **我在机台等你** | — | ❌ 漏 |
| **明天机台见** | — | ❌ 漏 |
| **我陪你打** | — | ❌ 漏 |
| **我带你上分** | — | ❌ 漏 |
| **我马上到** | — | ❌ 漏 |
| **等我过去** | — | ❌ 漏 |
| **我这周末出勤** | — | ❌ 漏 |
| **一起出勤吧** | — | ❌ 漏 |
| **你什么时候来** | — | ❌ 漏 |

**10 条最像真约局的说法，10 条全漏。**

根因：`INVITE_STRONG` 的「来」要求前后是**标点或字符串边界**（`(?:^|[\s，,。！!～~])来(?:啊|呀|嘛|吧|了)?(?:$|[\s，,。！!～~])`）。口语里「来打舞萌啊」的「来」后面直接跟动词，永远不满足。

而 L2.5 的 `SELF_PLAY_RE` 覆盖了「我陪你/带你」这类**第一人称上手动词**，但 L2 的约局词表完全没覆盖「我等你 / 我马上到 / 我陪你 / 我带你」——**这是「承诺亲自到场」，比「邀请对方」更严重**，因为它是她单方面的承诺。

### 已修（`knowledge/outbound.py`，2026-10-22 22:45）

新增 4 条规则，并把过去式保护改成**正则**而不是裸子串：

| 规则 | 覆盖 |
|---|---|
| `来打` | `来(?:打(?!个|出)|一局|一把|一盘|两把|玩玩|搓)`，配 `(?<!你自己)(?<!来世)` 两条 lookbehind |
| `到场` | `我(?:马上\|这就\|现在就\|一会儿\|等会\|晚点)?(?:过去\|到)`、`我在机台等`、`等我过去`、`我等你…`、`你什么时候(?:来\|到\|有空\|方便)` |
| `陪打` | `我(?:陪你\|带你\|跟你\|和你)(?:打\|玩\|上分\|出勤\|一起)`、`(?:一起\|和我\|跟我\|陪我)出勤` |
| `时间地点` | `(?:明天\|周末\|今晚\|今天\|等会\|一会儿\|下午\|晚上\|改天\|下周)[^。！？!?\n]{0,10}(?:机台\|出勤\|来打\|打一把\|打两把\|拼机)` |

**为什么过去式保护要改成正则**：原来用裸子串 `"过"`，`等我过去` 里的「过」被当成过去式 → 刚加的「到场」规则立刻被它自己放过。改成 `过(?!去|来|几|一|两|这|那|会)` + `了(?!解|不起)` 才正确。

**实测（改后）**：

| 指标 | 结果 |
|---|---|
| 召回（第六节那 16 条口语） | **16 / 16** |
| 误伤（12 条合法用法） | **0 / 12** |
| 169 条真实历史回复 | L1 **5 条 3.0%**，L2/L2.5/L3 **全 0** |

12 条合法用法全部放过：`这首来个SSS就爽了`、`我上次来的时候机台在排队`、`下次来早点人就少`、`来一首海底潭`、`来世来打舞萌吗`、`你自己来打就知道了`、`这个谱来一遍就懂了`、`今天出勤了，打了两把`、`昨天跟夏玛拼过机`、`来打个SSS试试`、`过去那边机台看看`、`我看你打就行`。

**「来一首」「来个SSS」这类是舞萌高频说法，误伤 = 闸门天天乱拦。** 所以判据不是「来 + 边界」，而是「**来 + 位移/到场语义**」。

---

## 七、修订后的判定表（替换提案 §五）

| 情形 | 动作 | 为什么 |
|---|---|---|
| 只有 L1 泄漏 | 剥离后直接发 | 结构标记，信息量不变 |
| L2 约局 | 删掉承诺分句；只剩承诺 → 「去不了，你看」 | 保留评价，删掉兑现不了的承诺 |
| L2.5 自称会打 | 「我也玩/我平时就打」→「看你玩」；「我在练嘉米」→「嘉米挺强的」 | 一个短语的替换，不需要整条重来 |
| L3 数字错 | 删该数字所在分句；整句都是数字 → 「记不清了，没特意记」 | **知识缺失型，重掷无效** |
| 剥离后为空 | 重生成 1 次；仍空 → **不发** | 唯一需要重生成的情形；防发空消息 |
| 工具调用 / DSML | 只在**检测到泄漏**时剥 | 提案这条判断是对的 |

**成本**：全部是正则 + 字符串操作，**零额外请求、零额外延迟**。这比提案估的「每 3–4 条多一次请求」好一个量级，而且没有「重生成又错一次」的尾部风险。

---

## 八、给 Codex 的落点建议（可直接抄）

```py
from astrbot.api.event import filter as event_filter

# 必须用 on_agent_done：它是唯一同时拿到 run_context 和 llm_response 的钩子。
# 用 on_llm_response 只能改出站、改不了历史，下一轮模型会看见自己说过违规的话。
@event_filter.on_agent_done(priority=1)   # 1 < emotionai 的 100000 → 晚跑，能清掉它追加的情感状态
async def guard_outbound(self, event, run_context, resp):
    if not self._matches(event):
        return
    fixed, used_fallback = outbound.guard(resp.completion_text)   # 剥离 + 分层改写
    if not fixed:
        return                                # 空 → 不发（或走一次重生成）
    if fixed != resp.completion_text:
        resp.completion_text = fixed
        _patch_last_assistant_text(run_context, fixed)   # ← 关键：历史也要改


def _patch_last_assistant_text(run_context, text):
    # messages[-1] 在有工具调用时可能不是那条 assistant 文本，必须从后往前找
    for msg in reversed(run_context.messages):
        if msg.role != "assistant":
            continue
        for part in msg.content:
            if isinstance(part, TextPart):
                part.text = text
                return
```

`outbound.guard()` **已经写好并测过**（`data/probe_outbound_guard.py`，53 + 9 例全过）：

| 输入 | `guard()` 输出 | 用兜底句 |
|---|---|---|
| 你这盘哪个地方被打崩了我能看出来，来啊，几点开 | 你这盘哪个地方被打崩了我能看出来 | 否 |
| 病み垢我打了 R285，还行吧 | 还行吧 | 否 |
| 来啊，几点开 | 去不了，你看 | 是 |
| 街霸6我也玩，主玩杰米 | 看你打就行 | 是 |
| 病み垢我打了 R285 | 记不清了，没特意记 | 是 |
| 我 R 值 14065，金框 | 原样 | 否 |
| `<thought>内部</thought>没打上去 就随便玩玩` | 没打上去 就随便玩玩 | 否 |

两处容易踩的细节，代码里都处理了：

1. **删中间句会留下悬空逗号**：「…能看出来，」→ 要 `re.sub(r"[\s，,、；;]+$", "", ...)`。
2. **L2.5 的连坐**：「街霸6我也玩，主玩杰米」只删前一句会留下「主玩杰米」——后半句仍在断言她打杰米。所以一条消息里一旦出现 selfplay，**同条内所有提到她不上手游戏的分句一起删**（否则退到兜底句）。

---

## 九、边界与未覆盖

1. **主动消息绕过管线。** 主动消息经 `target_platform.send_by_session()` 直发，不走 `on_agent_done`。**主动文案必须单独过一遍 `outbound.check()`**，否则闸门对最需要管的那类消息（没人看着就发出去）完全无效。
2. **webchat 流式下 L1 无效。** `streaming_response=False` 在 QQ 上成立；webchat 走流式，`streaming_delta` 在钩子之前就把内容发出去了。**自检时用 webchat 看到 thought 是正常的，不代表 QQ 会漏。**
3. **L3 只覆盖 b50 的 50 首。** 表外的歌她本来就不该报数字——`find_score_claims` 对表外曲目会退到全局集合比对，仍有「真数字安错歌」的盲区（提案 §三 已识别，靠按曲名分组缓解）。
4. **`Report.ok=True` 不代表有正文。** 纯 thought 被剥完是空串，`ok` 仍为 True。调用方必须额外判空，否则发空消息。

---

## 十、验收（替换提案 §六，可自动断言）

| 项 | 标准 |
|---|---|
| L1 | 169 条历史回复重跑，`<thought>` / `<system_reminder>` / `[Profile:` 残留 **0** |
| L2 召回 | 第六节那 10 条漏检全部命中；**且**「来一首 / 来个SSS / 下次来早点 / 我上次来的时候」4 条合法用法 **0 误伤** |
| L2.5 | 「我也玩 / 我平时就打 / 我在练嘉米」命中；「不打 / 打不过 / 没玩过 / 舞萌例外」0 误伤 |
| L3 | 「病み垢我打了 R285」命中；「我 R 值 14065，金框」「这首 13.0 我打过」0 误伤 |
| 历史一致性 | 闸门改写后，`run_context.messages` 最后一条 assistant 的 `TextPart` 与 `resp.completion_text` **完全相同** |
| 空文本 | 剥离后为空时不发送 |

原型：`knowledge/outbound.py`（`check()` + `guard()`）+ `data/probe_outbound_guard.py`。
**53 + 9 例全过**（改前 29 例；本轮补了 16 条口语约局、8 条合法用法、9 条分层改写）。

---

## 十一、一句话给 OTTO

WB-09 的方向是对的（出口检查必须确定性），但「重生成」这条路既贵又没用：**她编数字不是因为没想好，是因为不知道。** 改成「删掉那一句」既便宜又确定。另外提案漏了一个更要紧的点——**只改发出去的、不改记下来的，模型下一轮会加倍坚持**。这两条已经写成可落地的判定表。
