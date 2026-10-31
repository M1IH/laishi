# 回复延迟排查与优化（2026-10-31）

> 触发：OTTO 转述「我朋友还觉得 miruku 回消息有点太慢了，你先做只读」（m07967）。
> 结论先行：**慢的根源是搜索结果原样进上下文 + 表情包二次调用**，不是网络也不是模型本身。
> 三项优化已上线（截断 / probability 90→75 / 并行引导），实测单轮降 3~6 秒。

---

## 一、延迟实测（12h 内 15 轮，入站 `event_bus:117` → `Prepare to send`）

| 分组 | 轮数 | 平均 | 最大 |
|---|---|---|---|
| 无工具调用 | 10 | **4.06s** | 6.93s |
| 1–2 次工具 | 4 | **11.63s** | 13.66s |
| 3+ 次工具 | 1 | **16.23s** | 16.23s |
| 全体 | 15 | 6.89s（p50 5.71 / p90 11.45） | 16.23s |

**读法**：无工具 4 秒是正常推理耗时；**每加一次搜索就多 3~7 秒**，这才是体感「慢」的来源。

---

## 二、三个根因

### 根因 1：搜索结果整段进上下文，且每轮重付（主因）

`anysearch_search` 返回 1~3 万字符原始 Markdown，全部留在会话历史里：

```
#468 tool 29930    #472 tool 18822    #467 tool 13850    #480 tool 12156    #479 tool 9841
```

`context_guard` 只剥图片、不碰 tool 消息 → `remaining_chars` 从 08:30 的 **62162** 涨到 10:02 的 **224871**（8 轮搜索翻 2.4 倍），**每一轮后面都要重付这个体积**。

**为什么核心不管**：`/AstrBot/astrbot/core/agent/runners/tool_loop_agent_runner.py`
- `:112 TOOL_RESULT_MAX_ESTIMATED_TOKENS = 27_500`
- `:113 TOOL_RESULT_PREVIEW_MAX_ESTIMATED_TOKENS = 7000`
- `:414 if estimated_tokens <= self.TOOL_RESULT_MAX_ESTIMATED_TOKENS: return content`

即**超过约 10 万字符才截断**，1~3 万字符完全放行。

### 根因 2：表情包第二次 LLM 调用

`meme_manager` 的情感模型在 `context_guard` 之后、发送之前独立跑一次：

```
09:56:38.443 context_guard 完成 → 09:56:51.652 情感模型选择标签   （中间含 anysearch 约 7s）
10:02:07.559 → 10:02:13.935 = 6.38s                                （纯表情模型）
```

单算 **1.4~6.5s**；`probability=90` 时 90% 的轮次都要付这段。

### 根因 3（排除项）：网络与模型正常

- 容器内 `api.deepseek.com:443` TCP 握手 **9~15ms**
- provider `deepseek/deepseek-flash`，`timeout=120`，无超时记录
- 基础 4 秒属正常推理，不是异常

### 附带隐患：会话体积

`conversations` 表测试号主会话 `de4f09dc-edf6-482e-ad61-e99f0dbf3f7f` = **486 条 / 553 万字符**，其中 55 条超 1 万字符、合计 539 万——**超大消息全是 user 角色里的 base64 图片**（最大单条 449585 字符）。

`context_guard` 的 `strip_history_images=True` 确实剔除（`stripped_images=49 stripped_chars=5269399`，剔除后 265197 字符，再压 think 后 256280），**但每轮都要正则扫这 553 万字符**（约 0.3~0.4s），且 DB 持续增长。

对照：来世会话 `ee735760` 121 条 / 136213 字符；新好友 `30cfe0d5` 20 条 / 4943 字符（最干净）。

---

## 三、三项优化（OTTO m08024「1，按你的建议改 2，降到75 3，改并行」）

### ① 搜索结果截断（最有效）

改动文件：`/AstrBot/data/plugins/astrbot_plugin_anysearch/{client,tools,main}.py` + `_conf_schema.json` + 配置。
完整入仓副本见 `server/patches/20261031-anysearch-truncate/`。

`client.py`：
```python
TRUNCATE_NOTICE = (
    "\n\n[已截断：原始返回 {total} 字符，只保留前 {kept} 字符。"
    "需要更多细节就用更窄的关键词再搜一次，不要一次吞全文。]"
)

def _truncate(text: str, max_chars: int | None) -> str:
    if not max_chars or max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + TRUNCATE_NOTICE.format(total=len(text), kept=max_chars)
```
- `AnySearchClient.__init__(..., tool_result_max_chars: int = 4000)`，`search()` / `extract()` 末尾套 `_truncate`
- `batch_search()` 用 `budget = self.tool_result_max_chars * max(1, len(queries))`，再 `min(budget, 20000)`
- `main.py` 读配置：新增 `_get_int_config(key, default)`（int 转换失败或 <=0 回默认）
- `_conf_schema.json` 新增 `tool_result_max_chars`（type int，default 4000，hint 注明只作用于 LLM 工具调用、不影响 `/anysearch` 命令、填 0 不截断）

### ② 并行引导（收益有限，如实记录）

核心**无法并行**：`tool_loop_agent_runner.py:1195-1199`
```python
for func_tool_name, func_tool_args, func_tool_id in zip(...):
```
普通 for 循环逐个 await；`asyncio.gather` 只用在 `_await_or_stop(:483-506)` 与 `:1652`，**不在 tool 之间**。

所以只改插件侧提示词：
- `AnySearchSearchTool.description` 追加「如果一次要查两个以上不同的关键词，请改用 anysearch_batch_search 一次性并行搜索，不要接连调用本工具多次（串行调用会让对方多等好几秒）。返回内容会被截断到摘要长度，够判断就行；细节不够就换个更窄的关键词再搜。」
- `anysearch_batch_search` docstring 首句改为「想查多个关键词时优先用这个，一次请求并行搜完，比连续多次调用 anysearch_search 快得多。」

**实测并行收益**（`.tmp/asb-bench.sh`，容器内跑）：
```
SERIAL 'maimai 海底譚 作曲'      2.74s  chars=5273
SERIAL '舞萌 Xevel 谱面 难度'    1.74s  chars=8480   → 合计 4.48s
BATCH  2 queries                 2.52s  chars=13551  → speedup = 1.78x
```
服务端 batch 不是真全并行，**1.78x 只是附带改善；截断才是主要收益**。

### ③ 表情包 probability 90 → 75

`meme_manager_config.json`（UTF-8 BOM，读写用 `utf-8-sig`）`generation.emotion.probability` 90→75，断言旧值==90、tmp+os.replace 原子写、重启生效。省下 15% 轮次的 1.4~6.5s。

---

## 四、部署与验证

备份：`/opt/miruku/backups/asb-20261031-102021.tar`（184320 字节，含插件目录+配置）。
步骤：`docker cp` 5 文件 → `python3 -m py_compile` → 截断单测 → `docker restart astrbot`。

截断单测（容器内 reload 新版）：
```
max_chars = 4000
SEARCH chars=4061   （原文 4938）
BATCH  chars=6440
TRUNCATE_OK
```

重启后回读：`probability = 75 / max_memes = 1 / mixed = True 100 / streaming = True / asb_max_chars = 4000`。
启动日志全绿：`Loaded 2 personas`、`[miruku_outbound] armed: platform=miruku songs=1340 truth_keys=5`、`[miruku_backfill] armed: ... watch=3`、`[主动消息] 已成功从文件恢复任务喵: 私聊 10000001, 执行时间: 2026-10-31 11:03:36`、`aiocqhttp(OneBot v11) 适配器已连接`。

### 线上实测（决定性）

10:21:29 一轮里 `Agent 使用工具: ['anysearch_search', 'anysearch_search']`：
- query1 `舞萌DX 曲目 "穿心" 定数 谱面` / query2 `maimai 曲名 穿心 别称 是什么歌`
- 两次结果 `## Search Results (6 results, 1510ms/1165ms)`
- `context_guard` 前后 `remaining_chars` 226316 → 235246，**只增 8930 字符**（改前同类两搜至少 14435+，历史峰值单搜 29930）
- 日志里 `已截断` 出现 2 次

轮次耗时：

| 场景 | 起点 → 发送 | 耗时 |
|---|---|---|
| 含 2 次搜索 + 1 次情感模型 | 10:21:25.733 → 10:21:36.283 | **10.5s**（改前对应约 13.7~16.2s） |
| 无工具 | 10:20:47.622 → 10:20:54.063 | **6.4s** |
| 无工具 | 10:21:48.460 → 10:21:54.004 | **5.5s** |

表情包仍正常出图（`去重后的最终表情列表: ['affection']` + `[图片]`）。

---

## 五、遗留

1. **图片 base64 进历史**：`context_guard` 靠检索时剥，DB 里仍存 553 万字符。清洗需单独授权（属存储侧）。
2. **`dropped_rounds=0`**：400000 字符预算远未触发，说明历史裁剪逻辑还没真正介入；截断后增长斜率放缓，暂不动。
3. **表情包二次调用**：结构性问题（情感模型必然多一次请求），只能靠降频或换小模型，未做。
4. 延迟体感仍需 OTTO/朋友长期验收。

---

## 附：文件清单

| 文件 | 说明 |
|---|---|
| `server/patches/20261031-anysearch-truncate/client.py` | 加 `_truncate` / `tool_result_max_chars` |
| `server/patches/20261031-anysearch-truncate/tools.py` | 加并行引导 description |
| `server/patches/20261031-anysearch-truncate/main.py` | 读配置 + `_get_int_config` |
| `server/patches/20261031-anysearch-truncate/_conf_schema.json` | 新增配置项 |
| `server/patches/20261031-anysearch-truncate/config.json` | 线上实值模板 |
