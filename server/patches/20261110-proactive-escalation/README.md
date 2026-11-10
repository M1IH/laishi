# 主动消息未回复分级追问（20261110）

## 为什么

线上三条主动消息里，第 2、3 条和第 1 条完全一样：都是「早，……」换着花样打招呼，
一句都不提「你没回我」。根因是三层叠加：

1. `core/services/llm_service.py` 的 `generate_llm_response` 只有
   `motivation_template.replace("{{unanswered_count}}", str(n))` ——
   数字进了正文，但**没有任何按次数分支**，模型对 1/2/3 看到的是同一段指令。
2. 主提示词 `friend_settings.proactive_prompt`（432 字）明文写着「不催回复」。
3. `context_settings.platform_history_prompt` 第 3 条写着「不提对方没回……不追问，也不要求回应；
   只放一个不需要立刻接话的轻话题」。

2 和 3 合起来把「催」彻底禁掉，与「第 2 条要问为什么不回」正相反。

## 改了什么

### 1. `core/services/llm_service.py`

新增模块级纯函数 `pick_proactive_prompt(session_config, unanswered_count) -> (模板, 等级)`：

```python
ESCALATION_MAX_LEVEL = 3

def pick_proactive_prompt(session_config, unanswered_count):
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

`generate_llm_response` 里两行：

```python
-        motivation_template = session_config.get("proactive_prompt", "") or ""
+        motivation_template, prompt_level = pick_proactive_prompt(
+            session_config, unanswered_count
+        )
...
-        logger.debug("[主动消息] 已生成包含动机和时间的 Prompt 喵。")
+        logger.info(f"[主动消息] 主动消息等级={prompt_level}")
```

**计数语义不需要改**：`gating_feature.py` 传进来的 `unanswered_count` 是「上一条之前累计的未回复次数」，
所以本次是第 `unanswered_count + 1` 条 —— 0 → 第 1 条，1 → 第 2 条，2 → 第 3 条。
`max_unanswered_times=3` 会把 ≥3 挡在 GATE，所以永远不会用到第 4 条。

### 2. `_conf_schema.json`

`friend_settings.items` 里 `proactive_prompt` 之后新增 `escalation_settings`：
`enable`(bool, **默认 false**)、`prompt_2`(text)、`prompt_3`(text)。
默认 false 意味着装完不翻开关就完全是旧行为。

### 3. `data/config/astrbot_plugin_proactive_chat_config.json`

- 新增 `friend_settings.escalation_settings` = `{enable: true, prompt_2: …, prompt_3: …}`
- `context_settings.platform_history_prompt` 第 3 条改为让位版：
  > 3. 如果未回复次数已经大于 0，语气一律按主提示词的分级口径处理，
  > 不要自行判断轻重，也不要自己决定提不提对方没回。

### 4. `prompts/system.txt`（人格，走 `server/deploy-persona.py`）

L27 那句「不追问原因」后补半句：

> 但由系统发起的主动消息不受本条限制——那几条的措辞由专门的主动消息提示词决定。

不加这句，人格会压住提示词，模型要么不敢问、要么问得很别扭。
`server/deploy-persona.py` 的 `PROBES` 同步加了「由系统发起的主动消息不受本条限制」。

## 文案

`prompt_2`（327 字，半开玩笑的质问）与 `prompt_3`（297 字，更硬一档要回应）全文见
`patch_escalation.py` 里的 `PROMPT_2` / `PROMPT_3`。三条护栏：

1. 首句固定「你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。」
   —— `astrbot_plugin_miruku_metrics/main.py:33` 的 `PROACTIVE_MARK`、`data/probe_metrics.py:80`、
   导出脚本的 `is_proactive` 全靠它认主动消息，换了统计就断。
2. 仍然只发一条、有字数上限（10~15 / 12~20 字）、不加句号。
3. 硬禁止：威胁、自伤暗示、冷暴力、卖惨、以后不找他了。

按 OTTO 要求：**不带半通牒**（不说「今天不找你了」）、**不用「来世」这类直接称呼**（用「你」）。

## 部署

```bash
scp patch_escalation.py root@<host>:/tmp/
ssh root@<host> "docker cp /tmp/patch_escalation.py astrbot:/tmp/ && \
  docker exec astrbot python3 /tmp/patch_escalation.py \
    /AstrBot/data/plugins/astrbot_plugin_proactive_chat \
    /AstrBot/data/config/astrbot_plugin_proactive_chat_config.json"
docker restart astrbot
```

脚本幂等：第二次跑全是 `already`。三处改动各自先备份成 `*.bak.esc-<时间戳>`。

## 验证

脚本自带 6 组单测（开关关 / 0→1 / 1→2 / 2→3 / 5→封顶3 / 缺文案回退）+ 首句护栏断言。
线上实跑用 `set_count.py`：

```bash
docker exec astrbot python3 /tmp/set_count.py 1 240   # count=1 排在 240 秒后
docker restart astrbot
```

然后 `docker logs astrbot | grep 主动消息等级`，应为 `=2`。

## 坑

- `docker exec -i astrbot sh -c '...'` 单引号外层 `$P` 不展开；`python -c "多行代码"` 从 PowerShell
  传会被拆参数 —— **一律写 `.py` 文件再 scp + docker cp**。
- 配置有 BOM，必须 `encoding="utf-8-sig"` 读写，否则 `json.load` 报 `Unexpected UTF-8 BOM`。
- `set_count.py` 改完 `session_data.json` 必须 `docker restart astrbot`，否则调度器还拿着旧的
  `next_trigger_time`（内存里已经算好 job）。
- 重启后日志会出现「跳过自动触发器设置以避免冲突喵」，这是正常的（已有持久化任务）。
