# 主动消息未回复分级追问（2026-11-10）

## 一、现状与证据

### 1.1 问题

不回复 08:30 的第一条主动消息时，第 2、3 条和第 1 条没有区别，全是换着花样打招呼。
以 2026-11-10 为例（`platform_message_history`，未回复次数 0/1/2）：

| 未回复次数 | 实际发出 | 字数 |
|---|---|---|
| 0 | `早，熬过周一了，今天总算没那么难顶` | 16 |
| 1 | `早，今天总算没那么难顶了吧` | 14 |
| 2 | `早，今天风有点凉，出门记得加件外套` | 17 |

三条都以「早」开头、各自换话题，**没有一句提到对方没回**。

### 1.2 三层根因

**第 1 层：代码里没有按次数分支。**
`core/services/llm_service.py` 的 `generate_llm_response` 只有两行相关逻辑：

```python
motivation_template = session_config.get("proactive_prompt", "") or ""      # L151
final_user_simulation_prompt = motivation_template.replace(
    "{{unanswered_count}}", str(unanswered_count)                           # L153
).replace("{{current_time}}", now_str)
```

`{{unanswered_count}}` 只是把数字塞进正文，模板一个字不变。模型对 1/2/3 看到的是同一段指令。

**第 2 层：主提示词明文禁止。**
`friend_settings.proactive_prompt`（432 字）第 3 段：「不编造现实经历，不猜对方心情，不说自己一直在等或因未回复而失落，**不催回复**。」

**第 3 层：上下文提示词还要求"更轻更短"。**
`context_settings.platform_history_prompt`（632 字）第 3 条：
「如果未回复次数已经大于 0，这一条要**比平时更轻、更短**。**不提对方没回**，不表达等待、想念或失落，**不追问，也不要求回应**；只放一个不需要立刻接话的轻话题。」

2 和 3 合起来把"催"彻底禁掉——与本次需求正相反。

### 1.3 为什么不用"只改文案"

模型已经拿到 `{{unanswered_count}}` 这个数字却从不按它分支，说明它不是缺信息，而是缺**指令层的强制力**。
在 432 字里再加一段 if-else，得到的仍是"软建议"，实测（第 1 项报告 1.7 节的 A/B/C 三分类）已经证明
提示词长度约束被删掉后模型立刻退化——反过来也成立：软约束不可靠。

## 二、结论

采用**方案 B：代码按次数选模板**。

关键前提是计数语义刚好对得上，一行计数逻辑都不用改：
`gating_feature.py` 传给生成阶段的 `unanswered_count` 是"上一条之前累计的未回复次数"，
所以本次是第 `unanswered_count + 1` 条。`max_unanswered_times=3` 会把 ≥3 挡在 GATE，
永远不会走到第 4 条。

| `unanswered_count` | 今天第几条 | 用哪段模板 |
|---|---|---|
| 0 | 1 | `proactive_prompt`（432 字，不动） |
| 1 | 2 | `escalation_settings.prompt_2` |
| 2 | 3 | `escalation_settings.prompt_3` |
| ≥3 | 被 GATE 挡掉 | 不发 |

## 三、最小方案（已实施）

### 3.1 `core/services/llm_service.py`

新增模块级纯函数（放 `class LlmService` 之前，便于单测）：

```python
ESCALATION_MAX_LEVEL = 3


def pick_proactive_prompt(
    session_config: dict, unanswered_count: int
) -> tuple[str, int]:
    """按未回复次数选主提示词，返回 (模板, 等级)。"""
    base = session_config.get("proactive_prompt", "") or ""
    esc = session_config.get("escalation_settings") or {}
    if not isinstance(esc, dict) or not esc.get("enable", False):
        return base, 1
    try:
        level = min(max(int(unanswered_count or 0) + 1, 1), ESCALATION_MAX_LEVEL)
    except (TypeError, ValueError):
        return base, 1
    if level <= 1:
        return base, 1
    text = str(esc.get(f"prompt_{level}") or "").strip()
    if not text:
        return base, 1
    return text, level
```

`generate_llm_response` 两处替换：

```python
motivation_template, prompt_level = pick_proactive_prompt(
    session_config, unanswered_count
)
...
logger.info(f"[主动消息] 主动消息等级={prompt_level}")
```

**缺文案时回退第 1 条**：配置里 `prompt_2`/`prompt_3` 被清空不会导致不发，只是退回旧行为。

### 3.2 `_conf_schema.json`

`friend_settings.items` 里 `proactive_prompt` 之后新增 `escalation_settings`：
`enable`（bool，**默认 false**）、`prompt_2`（text）、`prompt_3`（text）。
默认 false 意味着装完不翻开关就完全是旧行为，方便回滚。

### 3.3 线上配置

- `friend_settings.escalation_settings` = `{enable: true, prompt_2: …, prompt_3: …}`
- `context_settings.platform_history_prompt` 第 3 条改为让位版：
  > 3. 如果未回复次数已经大于 0，语气一律按主提示词的分级口径处理，不要自行判断轻重，也不要自己决定提不提对方没回。

**不改这条会打架**：旧文案明确禁止提"没回"，与第 2/3 条提示词直接冲突，模型会取更保守的那一边。

### 3.4 人格（`prompts/system.txt`）

L27 那句「对方沉默、说「算了」「没事」「不知道」时，不评价沉默，不追问原因。」后补半句：

> 但由系统发起的主动消息不受本条限制——那几条的措辞由专门的主动消息提示词决定。

**不改人格分级会被压住**：L19 还写着「不去猜他为什么这么说」，两处合起来让模型不敢问"为什么不回"。
`server/deploy-persona.py` 的 `PROBES` 同步加了这条（共 10 条）。

## 四、文案

按 OTTO 要求：**不带半通牒**（不写「今天不找你了」）、**不用「来世」这类直接称呼**（统一用「你」）。

**第 2 条 `prompt_2`（327 字）**：半开玩笑的质问。
要点：不是打招呼、不问在干嘛、不聊天气、不用「早」开头、不重复上一条；
直接问为什么没回（没看到/在忙/把号忘了）；十到十五字、最多一个问句、不加句号。
语感示例：`?人呢` / `没看到吗` / `消息是被吞了吗`。

**第 3 条 `prompt_3`（297 字）**：更硬一档，要一个回应。
要点：说清是第三条也是最后一条；要求给回应，说声在忙也行；
十二到二十字、**不再问问题**、直接给要求。
硬禁止：难过到不行、一直在等、道歉、卖惨、威胁自伤或消失、以后不找他了。
语感示例：`今天三次都没回，说句话` / `忙就说一声，别当没看见`。

### 三条护栏

1. **首句固定**「你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。」
   —— `astrbot_plugin_miruku_metrics/main.py:33` 的 `PROACTIVE_MARK`、`data/probe_metrics.py:80`、
   导出脚本的 `is_proactive` 全靠它认主动消息，换了统计全断。脚本里有断言。
2. **仍然只发一条、有字数上限、不加句号**——升级的是内容强度，不是长度和条数。
3. **不发多条、不翻旧账**。

群聊（`group_settings`）不做：群里追问"怎么没人理我"很糟，而且有第三方在场。

## 五、验证

### 5.1 单测（`patch_escalation.py` 自带，6/6 通过）

| 用例 | 期望 | 结果 |
|---|---|---|
| 开关关 | level=1，用 base | OK |
| 0→1 | level=1，用 base | OK |
| 1→2 | level=2，用 prompt_2 | OK |
| 2→3 | level=3，用 prompt_3 | OK |
| 5→封顶 | level=3 | OK |
| prompt_2 为空 | 回退 level=1 | OK |

外加首句护栏 + 「来世」不出现 + 第 3 条让位，全部断言通过。
脚本幂等：第二次跑输出 `already`。

### 5.2 线上实跑（`set_count.py` 改 `session_data.json` + 重启）

**第 2 条**（`unanswered_count=1`，16:30:48 触发）：

```
[主动消息] 开始生成第 2 次主动消息喵，当前未回复次数: 1 次喵。
[services.llm_service:187] [主动消息] 主动消息等级=2
[主动消息] LLM 已生成文本喵，长度: 9。
```

实际发出：**`你是不打算理我了吗`**（10 字、质问语气、无直呼、无半通牒）。

**第 3 条**（`unanswered_count=2`，16:34:03 触发）：

```
[主动消息] 开始生成第 3 次主动消息喵，当前未回复次数: 2 次喵。
[services.llm_service:187] [主动消息] 主动消息等级=3
[主动消息] LLM 已生成文本喵，长度: 14。
```

实际发出：**`今天还没动静，回一句在忙也行`**（14 字、不再问句、直接要回应、无威胁）。

两条都在字数上限内、无句号、无表情、以「你/今天」起头（没有直呼）。

### 5.3 回归

- `session_data.json` 计数链路正常：第 2 条发出后 `unanswered_count` 3→2，第 3 条后 →3，
  然后 `flow_orchestrator` 排下一次。
- 第 1 项建立的 `proactive` 识别（`is_proactive`）未受影响——首句保留。
- 测试后已把 `3043128845` 复位为 `unanswered_count=0`、`next_trigger_time` 17:05:33
  （`3529676294` 未动，仍 11-11 08:30）。

## 六、回滚

把 `escalation_settings.enable` 改成 `false` 即可，代码路径完全不变（`pick_proactive_prompt`
第 3 行就返回 base）。schema 与代码留着不影响其他功能。

## 七、遗留

- **观感是第一风险**：第 2 条已经是质问，第 3 条更硬。你之前定的人格基调是"不烦人"，
  这两条是在同一基调上开的例外口子。建议先听两天。
- 配置可能被 AstrBot 运行期回写，次日应复查 `friend_settings.escalation_settings` 是否还在。
- 群聊分级没做，如果以后要做，`group_settings` 需要单独一套文案（场合不同，措辞不能照搬）。

## 八、产物

- `server/patches/20261110-proactive-escalation/patch_escalation.py`（改动 + 单测 + 幂等）
- `server/patches/20261110-proactive-escalation/verify_online.py`（线上回读校验）
- `server/patches/20261110-proactive-escalation/README.md`（部署命令与四个坑）
- `prompts/system.txt` / `server/deploy-persona.py`（人格例外句 + 第 10 条探针）
