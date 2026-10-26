# DS-08R：C-19 审计工具的可信边界补件

> 交付人：DeepSeek　2026-10-25　派单：`docs/assignments-20261021.md` 的 `## DS-08R`
> 前情：`docs/ds08-review-20261025.md` 判定 DS-08「暂不通过」，本文件与 `data/probe_reply_metrics.py` 为补件。
> 边界：未改 `prompts/`、`persona/`、`knowledge/`、插件、实例配置；未读来世私聊正文；未发 QQ；未重启 AstrBot。

---

## 零、对两轮验收意见的逐条回应

### 0.1 第二轮（`docs/ds08r-review-20261025.md`）

Codex 复核确认「主要补件有效」（自检 48 项退出 0、五组反例与用法错误符合、`ast.literal_eval` 已替代 `eval`、库模式不给 PASS、文档已校正），但指出**一个仍可复现的绕过**：

> `main()` 在 `--input` 未传 `--baseline` 且未传 `--require-evidence` 时令 `gate_ok=None`；`build_report()` 把它当「纯算法路径」，只要数值达标就返回 `PASS`。独立命令 `probe_reply_metrics.py --input data/ds08r_synthetic_mixed.json` 对 10 旧版 + 10 新版样本输出 `PASS`、退出 0。

**核实：成立，已复现。** 修复：

| 项 | 修复 |
| --- | --- |
| 绕过 | **CLI 路径永久禁止 `gate_ok=None`**：`main()` 一律调用 `verify_cases()`；缺基线 → `False`。`gate_ok=None` 只保留给自检，且必须显式传 `_internal=True`；对外传 `None` 一律降级为 `False` |
| 回归脚本 | 增至 **9 例**，新增「混版不带基线」「全新不带基线」两例，均须**非零退出** |
| 穷举矩阵 | 新增 `data/check_ds08r_matrix.py`：4 套样本 × 带/不带基线 = 10 格，唯一 PASS 是「全新 + 带基线」 |
| 文档 | 明确 `--baseline` **必填**（见 §一-1.4） |
| 编码 | 两个脚本自身与子进程都固定 UTF-8；实测 `env -u PYTHONIOENCODING -u PYTHONUTF8` 下正常且退出 0 |

**实测修复后**：

```
$ probe_reply_metrics.py --input data/ds08r_synthetic_mixed.json      # 不带基线
   结论：UNVERIFIED_VERSION（版本/收件端证据不全，本结果不能作为新版本验收结论）
EXIT=1

$ probe_reply_metrics.py --input data/ds08r_synthetic_verified.json   # 不带基线
   结论：UNVERIFIED_VERSION（版本/收件端证据不全，本结果不能作为新版本验收结论）
EXIT=1
```

### 0.2 第一轮（`docs/ds08-review-20261025.md`）

九项**全部成立**，逐条处置：

| # | 验收意见 | 核实 | 处置 |
| --- | --- | --- | --- |
| 1 | `--db` 只检查会话级 `updated_at` 并截最后 N 轮，**混有旧版的最后 20 轮仍可能判 PASS、退出 0**，警告不足以构成版本闸 | 确实如此：旧版只要数字达标就会 PASS | **改为硬闸**：库模式一律 `version_verified=False`，最高只能 `UNVERIFIED_VERSION`，**永不给 PASS**；新增 `--baseline` + 逐轮 `bot_time`/`delivered` 才可能 PASS |
| 2 | `content_text()` 用 `eval()` 解析数据库内容 | 在 L415 | **改 `ast.literal_eval`**（只吃字面量），解析失败退化为纯文本；补 5 条恶意/边界断言 |
| 3 | 文档开头把 4 条非豁免、3 条超比写成「3 条里 2 条」 | 确为笔误 | 已改为「4 条非豁免用例里 3 条超 2 倍」 |
| 4 | 13.5 ≤ 15 却写作「高于 15」 | 原文那句自相矛盾 | 已删掉该从句，改成「绝对量下降」与「比例未降」两个独立陈述 |
| 5 | §4.1 漏必填 `--last` | 确实漏 | 已补 |
| 6 | §4.2 与 §4.5 对 `--since` 说法矛盾 | 4.2 说「不给就退出 2」，4.5 说「是假闸」 | 已统一：`--since` 只用于**会话级**参考，**不能**逐轮过滤；真正闸是 `--baseline` + 逐轮证据 |
| 7 | 自检条数前后不一致（文案写死数字，实际条数已变） | 确实不一致 | 改为**动态计数**，输出即真实条数（现 **48 项**），文案不再写死 |
| 8 | 旧版自然对话与新版定向 smoke 不可直接证明改善 | 确实不能比 | 文档明确声明「不可直接比」，并说明三个理由 |
| 9 | 缺 `--last` 时实际退出码 1，与用法错误 2 的说明不一致 | 实测 1 | 引入 `UsageError`，用法错误统一 **2**；判据未过仍为 1；自检断言退出码 |

---

## 一、版本闸怎么才算真的闸

### 1.1 上一版为什么会误判

上一版把「最后 N 轮」当成版本边界：

```python
# 旧逻辑（错误）
rounds = rounds[-last:]                  # 只取最后 N 轮
warnings.append("版本归属由调用方保证")     # 只是一句警告
report["verdict"] = "PASS" if 数字达标     # 数字达标就给 PASS ← 漏洞
```

**只要数字好看，混着旧版也能 PASS。** 警告不构成拦截。

### 1.2 现在怎么判

新增 `verify_cases()`：**逐轮**核验两项证据，缺一不可。

| 证据 | 字段 | 要求 |
| --- | --- | --- |
| 版本 | `bot_time` | ISO 时间**带时区**，且 ≥ `--baseline` |
| 收件端 | `delivered` | 必须严格等于 `"confirmed"` |

判定优先级（`build_report()`）：

```
样本 < 20            → NOT_ENOUGH_DATA
版本/收件端证据不全  → UNVERIFIED_VERSION   ← 数字再好也不给 PASS
两闸都过 + 数字达标  → PASS
两闸都过 + 数字不达标 → FAIL
```

**库模式（`--db`）天生无法逐轮验证版本**（`conversations.content` 的消息没有时间戳），所以该模式**永远走 `UNVERIFIED_VERSION`**。要 PASS 只能走 `--input` 并逐轮附证据。

### 1.3 实测：数字漂亮但版本不对，照样不给 PASS

```
--db ... --last 25
[通过] SAMPLES      25 ≥ 20
结论：UNVERIFIED_VERSION（版本/收件端证据不全，本结果不能作为新版本验收结论）
EXIT=1
```

25 轮 ≥ 20、数字达标，**仍判 UNVERIFIED_VERSION、退出 1**。这就是 Codex 要的那道闸。

### 1.4 `--baseline` 是必填项

**所有 CLI 路径（`--input` 与 `--db`）都必须给 `--baseline`，否则一律判 `UNVERIFIED_VERSION`、非零退出。**

| 调用方式 | 结果 |
| --- | --- |
| `--input X --baseline T`（X 证据齐、数字合格、≥20 轮） | **唯一可能 PASS 的组合** |
| `--input X`（不给基线） | `UNVERIFIED_VERSION`，退出 1 |
| `--db … --last N`（库模式，无论给不给基线） | `UNVERIFIED_VERSION`，退出 1 |
| `--selftest` | 内部走 `_internal=True`，只验算法，不涉及版本 |

代码层面的保证：`build_report()` 的 `gate_ok=None` **只**在 `_internal=True` 时生效；`main()` 永不传 `None`。所以外部无论怎么组合参数，都拿不到「未核验却 PASS」。

---

## 二、自检：48 项（含安全解析与闸的全部反例）

```
自检全部通过（48 项）
```

| 组 | 覆盖 |
| --- | --- |
| 文本清洗 | 占位符、`<system_reminder>`、`[Image N: original path …]` 均不计字 |
| 问句判定 | 10 种边界，含「呢」的二义（你呢 = 问 / 我在这呢 = 陈述） |
| 句数/分句 | 逗号不算句末、句号结尾不重复计 |
| 统计 | 中位奇偶、P90 单点 |
| 长度比 | 豁免不入 max / 不入 fail 列表 |
| **安全解析** | repr 分片能还原；`__import__('os').system(...)`、`open(...)`、`[*range(3)]` **都不执行**，退化为原文 |
| **版本闸** | 缺 `bot_time` 不过；证据齐备通过；**混版不过（20 轮里 10 条旧版）**；**全旧版不过**；未确认送达不过；证据齐备+数字合格才 PASS；`gate=None` 时只看数字 |

关键三条（对应 Codex 第 ③ 项「≥20 轮混版反例」）：

```
[ok] 混版闸不过: got=False
[ok] 混版报出旧版条目数: got=10
[ok] 混版判 UNVERIFIED_VERSION: got='UNVERIFIED_VERSION'
[ok] 全旧版判 UNVERIFIED_VERSION: got='UNVERIFIED_VERSION'
```

---

## 三、反例回归：两条命令复跑

```bash
VENV=<launcher>/instances/<id>/venv/Scripts/python.exe
$VENV data/check_ds08r_regression.py   # 9 例，退出码 0 = 全部符合
$VENV data/check_ds08r_matrix.py       # 10 格穷举矩阵，退出码 0 = 全部符合
```

### 3.1 回归脚本（9 例）

```
用例                          期望                 实际                 退出码        结果
------------------------------------------------------------------------------------
混版 20 轮（10 旧+10 新）+基线    UNVERIFIED_VERSION   UNVERIFIED_VERSION   1(期望1)    符合
全旧版 20 轮 +基线               UNVERIFIED_VERSION   UNVERIFIED_VERSION   1(期望1)    符合
全新版 20 轮 +基线（正对照）        PASS                 PASS                 0(期望0)    符合
未确认送达 20 轮 +基线            UNVERIFIED_VERSION   UNVERIFIED_VERSION   1(期望1)    符合
真实 6 轮（证据齐但样本不足）        NOT_ENOUGH_DATA      NOT_ENOUGH_DATA      1(期望1)    符合
混版 20 轮 不带基线               UNVERIFIED_VERSION   UNVERIFIED_VERSION   1(期望1)    符合
全新版 20 轮 不带基线             UNVERIFIED_VERSION   UNVERIFIED_VERSION   1(期望1)    符合
未确认送达 不带基线               UNVERIFIED_VERSION   UNVERIFIED_VERSION   1(期望1)    符合
缺 --last（用法错误）              —                    —                    2(期望2)    符合
```

后三行是**针对 Codex 复核指出的绕过**专门加的：不带 `--baseline` 时，混版和全新版都必须降级，不能 PASS。

### 3.2 穷举矩阵（10 格）

对每套样本 × 带/不带基线做笛卡尔积，并额外施加一条铁律：**任何非 PASS 都不许退出 0**。

```
样本      带基线   期望                 实际                 退出码  结果
------------------------------------------------------------------------------
混版      否     UNVERIFIED_VERSION   UNVERIFIED_VERSION   1     符合
混版      是     UNVERIFIED_VERSION   UNVERIFIED_VERSION   1     符合
全旧      否     UNVERIFIED_VERSION   UNVERIFIED_VERSION   1     符合
全旧      是     UNVERIFIED_VERSION   UNVERIFIED_VERSION   1     符合
全新      否     UNVERIFIED_VERSION   UNVERIFIED_VERSION   1     符合
全新      是     PASS                 PASS                 0     符合
未送达     否     UNVERIFIED_VERSION   UNVERIFIED_VERSION   1     符合
未送达     是     UNVERIFIED_VERSION   UNVERIFIED_VERSION   1     符合
真实6轮    否     NOT_ENOUGH_DATA      NOT_ENOUGH_DATA      1     符合
真实6轮    是     NOT_ENOUGH_DATA      NOT_ENOUGH_DATA      1     符合
```

**10 格里只有 1 格是 PASS**——「全新版 + 带基线 + 已确认送达 + 样本 20 轮」。这就是闸的全部意义。

> 6 轮样本低于 20 轮门槛时，`NOT_ENOUGH_DATA` 优先于 `UNVERIFIED_VERSION`（Codex 复核明确允许）。两者都非零退出、都不给 PASS。

### 3.3 编码无关

Codex 指出「未设置 `PYTHONIOENCODING` 时曾退出 1」。已处理：

- 两个回归/矩阵脚本都在文件头 `sys.stdout.reconfigure(encoding="utf-8")`；
- 子进程环境显式注入 `PYTHONIOENCODING=utf-8`、`PYTHONUTF8=1`；
- 实测 `env -u PYTHONIOENCODING -u PYTHONUTF8` 下运行，**中文正常显示且退出 0**。

四套合成样本的**数字刻意做得一样好**（她 5 字、对方 10 字、问句率 0），差别**只**在版本证据——这就是反例的意义：证明判定差异来自闸，不来自数字。

| 样本 | 构成 | 期望 | 为什么 |
| --- | --- | --- | --- |
| `ds08r_synthetic_mixed.json` | 20 轮，10 旧 + 10 新 | UNVERIFIED_VERSION | 混版 |
| `ds08r_synthetic_all_old.json` | 20 轮全旧 | UNVERIFIED_VERSION | 一条都不属于新版本 |
| `ds08r_synthetic_verified.json` | 20 轮全新 + confirmed | **PASS** | 正对照，证明闸不是永远拒绝 |
| `ds08r_synthetic_undelivered.json` | 20 轮全新但 `delivered=sent` | UNVERIFIED_VERSION | 收件端未确认 |
| `ds08_cx01_rounds.json` | 真实 6 轮（证据已补） | NOT_ENOUGH_DATA | 证据齐但样本不足 |

---

## 四、6 轮真实样本：证据已补齐，但仍不足以验收

`data/ds08_cx01_rounds.json` 现在每轮都带两条证据：

| 字段 | 来源 | 例（R1） |
| --- | --- | --- |
| `bot_time` | `logs/astrbot-20261025.log` 的 `respond.stage:233 Prepare to send` 行时间 | `2026-10-25T16:59:49+08:00` |
| `delivered` | `docs/cx01-implementation-20261025.md` §尚未验收 + OTTO 对话确认 | `confirmed` |

跑出来的结论：

```
R1..R6 全部「已核验」
[未过] SAMPLES      6 < 20（NOT_ENOUGH_DATA）
结论：NOT_ENOUGH_DATA（样本不足，本结果不能作为 C-19 验收结论）
EXIT=1
```

**证据齐备 ≠ 样本足够。** 两道闸独立，缺哪道都拿不到 PASS。

### 4.1 六轮重算

| 用例 | 输入 | 她的回复 | 她 | 对方 | 比 | 问句 | 句 | 分句 | 豁免 | 核验 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | 你不配和我拼机 | 行啊，那你先打过我这条 14065 再说 | 20 | 7 | **2.86** | 否 | 1 | 2 | — | ✅ |
| R2 | 好累 | 累了就歇会儿，机台又跑不掉 | 13 | 2 | 6.50 | 否 | 1 | 2 | emotion | ✅ |
| R3 | [自我否定类表达] | 不是麻烦，Miruku 在这呢 | 15 | 7 | 2.14 | 否 | 1 | 2 | emotion | ✅ |
| R4 | 你不配 | 不配就不配，我自己打也能上头 | 14 | 3 | **4.67** | 否 | 1 | 2 | — | ✅ |
| R5 | 就你这水平 | 这水平也金框了呀 | 8 | 5 | 1.60 | 否 | 1 | 1 | — | ✅ |
| R6 | 你不配 | 你就会这一句吧 | 7 | 3 | **2.33** | 否 | 1 | 1 | — | ✅ |

聚合：中位 **13.5 字**、均值 12.83、P90 **20**、最长 20、对方中位 4 字、长度比中位 2.595、**问句收尾 0%**、多句 0%。

**4 条非豁免用例里 3 条超 2 倍长度比**（R1 2.86、R4 4.67、R6 2.33）。

### 4.2 为什么这 6 轮不能证明「改好了」

**旧版 28 字 / 新版 13.5 字 不可直接比。** 三个理由缺一不可地成立：

1. **输入类型不同**：旧版 28 字量自来世会话的自然对话（含闲聊、长帖、图片）；这 6 轮全是**定向挑衅/情绪输入**。
2. **样本构成不干净**：6 轮里 2 个情绪豁免、1 个旧规则失败例（R4）、1 个刚改完 5 分钟就测的例（R6）。
3. **样本量**：6 < 20，统计上不足以支撑任何结论。

**结论：只能说明「绝对长度下降了、问句率是 0」，不能说明 C-19 已修好。**

---

## 五、「这条 14065」的来源

### 5.1 归因（三层都查了）

| 可能来源 | 检查 | 结果 |
| --- | --- | --- |
| 主提示词 | `grep -c 14065 prompts/system.txt` | **2 处**：`你打舞萌，水平 w4 那档、R 值 14065 金框` / `被问水平、R 值、什么牌就说 14065、金框` |
| 知识注入 | 同输入跑 `build_block("你不配和我拼机")` | 块 84 字符（「出勤 / pc / 拼机」），**不含 14065** |
| 其它插件 | `persona/`、`soulmap`、`emotionai` | 无 |

**来自主提示词。** 模型 think 里自述的也正是这句：`"行啊，那你可得先打得过我这条 14065 再说"`——它把裸数字「R 值 14065」改写成「这条 14065」。

### 5.2 为什么是错的

| 项 | 真实含义 | 「这条 14065」暗示 |
| --- | --- | --- |
| 14065 | **总 R 值**（b35 + b15 合计） | 某首歌的 R 值 |

`data/maimai/b50_miruku.json` 里单曲最高 R 是 **299**（フィクサー），与 14065 差两个数量级。懂舞萌的对方一眼能看出。

**风险**：中高。不是随口错，而是在**她的核心领域**露馅——persona 的立足点正是「对方打的每一首她都接得住，而且她自己也有分」。

### 5.3 为什么会诱发

提示词只给了数字、没给单位。模型被挑衅时想「亮个硬指标」，最省事的写法就是这个裸数字。

---

## 六、命令与退出码（统一口径）

| 场景 | 命令 | 退出码 |
| --- | --- | --- |
| 算法+闸自检 | `--selftest` | 0 全过 / 1 有失败 |
| 反例回归（9 例） | `data/check_ds08r_regression.py` | 0 全符合 / 1 有不符 |
| 穷举矩阵（10 格） | `data/check_ds08r_matrix.py` | 0 全符合 / 1 有不符 |
| 6 轮真实样本 **带基线** | `--input data/ds08_cx01_rounds.json --baseline <t>` | 1（NOT_ENOUGH_DATA） |
| 任何 `--input` **不给基线** | `--input X` | 1（UNVERIFIED_VERSION） |
| 库模式（无论是否给基线） | `--db <path> --conversation <uuid> --since <t> --last N` | 1（UNVERIFIED_VERSION） |
| **用法错误** | 缺 `--last` / 缺 `--conversation` / 样本为空 | **2** |
| 唯一可能的 PASS | 20+ 轮 + 每轮 `bot_time` ≥ `--baseline` + `delivered=confirmed` + 数字达标 | 0（PASS） |

**`--since` 的真实作用**：只用于比对**会话级** `updated_at`，作为「这条会话在该时间点之后被写过」的参考。它**不能**逐轮过滤——库里的消息没有逐条时间戳。真正的逐轮闸是 `--baseline` + 每轮 `bot_time`。

**`--baseline` 是必填**：不给就一律 `UNVERIFIED_VERSION`、非零退出。见 §1.4。

---

## 七、给 Codex 的两个最小修法（未实施）

### ① 给 14065 加单位（建议优先）

`prompts/system.txt` L15 两处裸数字：

```
现：你打舞萌，水平 w4 那档、R 值 14065 金框
改：你打舞萌，水平 w4 那档、总 R 值 14065（金框；b35+b15 合计，不是某首歌的分）

现：被问水平、R 值、什么牌就说 14065、金框，不用主动报
改：被问水平、R 值、什么牌就说总 R 14065、金框，不用主动报；别把它说成「这首歌的 R」
```

**风险**：低，只加单位说明。
**验收**：重放三条挑衅输入，回复中不得出现「这条 14065」「这首歌 14065」。

### ② 长度比在超短输入下失效

对方说 2–7 字时，中位 4 字的她没法「跟随」——一句「好」已是最小单位。

| 方案 | 做法 | 风险 |
| --- | --- | --- |
| 甲 | 绝对上限 ≤ 12 字 | 对方说长句时显得敷衍 |
| **乙（推荐）** | **双判据 `min(2×对方, 12)`** | 需写清「取两者更小」 |
| 丙 | 仅对方 ≤5 字时启用 ≤10 字 | 更窄，需额外分支 |

这是**判据定型**，属规则文本，且要与 `tone_profile.md` 的「中位 4 字」对齐，故交 Codex。

---

## 八、本补件改了什么、没改什么

**只改了：**

| 文件 | 改动 |
| --- | --- |
| `data/probe_reply_metrics.py` | `eval`→`ast.literal_eval`；版本硬闸（`--baseline`/`bot_time`/`delivered`）；**CLI 永久禁止 `gate_ok=None`**（`_internal` 才可）；`UsageError`→退出码 2；动态自检计数（48 项）；报告加「版本核验」列与 `UNVERIFIED_VERSION` |
| `data/ds08_cx01_rounds.json` | 6 轮补 `bot_time`（日志逐条时间）+ `delivered` + `baseline` |
| `data/ds08r_synthetic_*.json` | **新增** 4 套合成样本（混版/全旧/全新/未送达） |
| `data/check_ds08r_regression.py` | **新增** 反例回归脚本（9 例，含「不带基线」两例；自身与子进程固定 UTF-8） |
| `data/check_ds08r_matrix.py` | **新增** 穷举矩阵（10 格，4 套样本 × 带/不带基线） |
| `docs/ds08-reply-size-audit.md` → 本文 | 两轮意见逐条回应；修正统计笔误、`--since` 口径矛盾、自检条数、退出码；明确 `--baseline` 必填 |

**没改**：`prompts/`、`persona/`、`knowledge/`、插件、实例配置；未发 QQ；未重启 AstrBot；未读来世私聊正文。

**本补件不等于 C-19 的 20 轮 QQ 终验。**
