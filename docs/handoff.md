# Miruku 项目交接文档

> ⚠️ **【历史快照｜已降级，不再是权威事实来源】** 本文写于 2026-10-20，之后大量设定与状态已变化（例如 2026-10-22 起来世的舞萌水平、出勤经历、b50 数据、知识库规模；2026-10-24 的 D1–D12 决议；C-01…C-17 缺陷状态）。**现行口径请以以下为准**：`WORK_LOG.md` 顶部「当前状态」、`docs/otto-decisions-20261024.md`（OTTO 决议）、`docs/collaboration-roles.md`（分工）。本文仅作背景参考，**不得据此下事实判断**。

> 目的：给一个新的会话窗口提供零上下文的完整认知，使其能够理解项目全貌、
> 当前已知问题、已完成的改动，并自主规划下一步。
> 更新时间：2026-10-20

---

## 一、项目是什么

这是一个 **Windows 本地运行的 QQ AI 陪伴机器人**。

- **人物形象**：采用《maimai》系列的 **Miruku（みるく/咪璐库）**，猫娘，憧憬偶像夏玛，想成为成熟偶像。
- **服务对象**：OTTO（项目主）指定的一个真实联系人 —— "来世"（QQ 号 10000002，即聊天记录导出里的 peer）。
- **核心目标**：让 Miruku 以**低压力、口语化、不冒犯**的方式陪伴对方。所有工程努力都收敛在"陪伴质量"这一个维度上。

### 技术底座（五层解耦）

| 层 | 组件 | 职责 |
|---|---|---|
| 协议端 | NapCatQQ | QQ 登录、收发消息、图片消息（OneBot v11） |
| 消息框架 | AstrBot | 消息管线、模型调用、插件生命周期、WebUI API |
| 模型 | DeepSeek | OpenAI 兼容 API |
| 主动调度 | astrbot_plugin_proactive_chat | 沉默计时、免打扰、分段发送 |
| 存储 | SQLite（AstrBot 自带 data_v4.db） | 本地消息、会话 |

**架构铁律（必须遵守）**：不重写 AstrBot 消息管线，不自己造主动调度器，直接复用现成件。Miruku 只做业务规则（人格、口吻、画像、危机兜底）。

---

## 二、当前状态

### 阶段 0 真实 QQ 验收与 2026-10-20 续验收

以下 6 项完成条件均已有运行证据；另有整机重启恢复待验：

1. ✅ AstrBot + NapCatQQ + proactive_chat 可同时运行（AstrBot 4.29.1，插件 v1.2.6）
2. ✅ QQ 小号能收发文字消息
3. ✅ DeepSeek 完成 OpenAI 兼容调用
4. ✅ 机器人能发送项目图片（`images/stage0-test.png`）
5. ✅ 主动消息插件能创建私聊沉默任务（3–6 小时随机调度、1–8 点免打扰、最多 1 次未回复后停发）
6. ✅ 当时的 216 条 WebUI 日志缓存未见 DeepSeek Key；2026-10-20 00:08:58 主动任务到点执行，OTTO 确认测试 QQ 收到消息，未回复计数由 0 变为 1。00:11 通过 AstrBot 官方 API 重启核心后，插件恢复 1 个持久化任务，NapCat 与 6199 端口重新建立连接。**Windows 整机重启后的 Launcher/NapCat 自动启动与登录仍待验证。**

2026-10-20 P2 进展：`plugins/astrbot_plugin_miruku_observer/` 已装入当前实例并启用，仅对配置的目标私聊记录消息方向、UTC 观察时间与首次回复间隔，不存正文或原始 QQ。2026-10-20 12:17–12:24 事件库已记录 7 条真实目标私聊事件（4 入站、3 出站、2 条首次回复间隔），来世本人受 OTTO 邀请实测三条并收到回复，普通私聊链路已验收。低落/危机模式在现有提示词机制中没有结构化触发信号，标记保持 `NULL`（未知）；详见 `docs/observability.md`。不要把插件已加载误记成事件链路已验收。

同日后续进展：目标 QQ 普通私聊现已有 4 条入站、3 条出站元数据及 2 条首次回复间隔。WorkBuddy 指出主动消息绕过 `after_message_sent`；Codex 已让观察插件只读查询 AstrBot 平台流水补记主动出站，本地合成流水验证通过，真实目标主动消息仍待验收。Windows 用户登录任务已启动 AstrBot，OTTO 确认测试 QQ 收到开机恢复检查；NapCat 快速登录态失效时确实要重新扫码，扫码后 OneBot 恢复。WebUI 的账号密码是管理界面登录，与核心自动启动无关。详见 `docs/prelaunch-checklist.md`。

### 运行实例位置

```
AstrBot Launcher 实例：
C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\core
```

- 实例路径现在由本机 `.env` 的 `ASTRBOT_CORE` 提供（环境变量可覆盖，模板见 `.env.example`）；缺失或无效时明确报错。
- WebUI 本地端口是**动态发现**的（脚本用 psutil 扫进程）。
- 运行脚本必须用**该实例的 Python 环境**，不是系统 Python（系统 Python 缺少 `jwt`/`psutil` 等依赖）。

---

## 三、目录结构

```
来世/
├── README.md                 # 项目入口说明（已存在，可作权威）
├── miruku_client.py          # ★ 新增：公共客户端模块（本次重构产物）
├── deploy_miruku.py          # 同步人格到 AstrBot + --probe 口吻检查
├── setup_stage0.py           # 安装主动消息插件压缩包
├── configure_proactive.py    # 为最近私聊配置低打扰主动消息
├── verify_stage0.py          # 向最近私聊发测试图片
├── prompts/
│   └── system.txt            # ★ 已定稿的系统提示词（人格+三档模式+危机兜底）
├── persona/
│   ├── miruku.md             # 人设（身份/立场/性格/模式切换）
│   └── tone_profile.md       # 口吻档案（短句/无句号/禁语/发送检查）
├── profiling/
│   ├── dimensions.md         # 画像 12 维度
│   ├── profile.json          # 已用真实聊天记录校准的首版画像
│   ├── analyze_chat.py       # 聊天记录统计分析脚本
│   └── script.md             # 画像采集话术规则
├── docs/
│   ├── architecture.md       # 架构与组件边界
│   ├── deployment-matrix.md  # 阶段 0 部署兼容矩阵 + 验收记录
│   ├── github-precedents.md  # 复用的开源先例与边界
│   └── active-message-ideas.md # 主动消息方向与 OTTO 已选定的 Oshama 示例
├── data/                     # 运行时数据（含插件 zip、AstrBot 数据库）
├── images/                   # 图片素材（目前仅 stage0-test.png）
├── 聊天记录/                 # QQ 私聊导出 JSON（17.9MB，用于口吻校准）
└── deepseek_markdown_20261019_ceab20.md  # 一份历史记录（用途待确认）
```

---

## 四、已发现的问题（按严重度排序）

### 高优先级（工程债）

1. **【已修复】JWT/token 逻辑四处重复** —— 原四个脚本各自重复"读 cmd_config.json → 签 JWT → 拼 header"十几行。**本次已通过抽取 `miruku_client.py` 解决**（见第六节）。

2. **【已修复】INSTANCE 路径硬编码** —— 2026-10-20 已改为环境变量 / 本机 `.env` 读取，并验证实例 API 可连接；缺失或无效路径会直接报错，不再静默回退到旧实例。

3. **AstrBot 内部数据库 schema 依赖已收敛并加防护** —— `configure_proactive.py` 和 `verify_stage0.py` 通过 `latest_private_session()` 查询。2026-10-20 加入只读打开、表字段检查和时间戳格式检查；升级造成结构变化时会明确报错。底层查询仍依赖 AstrBot 的 `conversations` 表，版本升级后需要重新验证。

### 中优先级（稳定性和度量）

4. **阶段 0 尚有整机恢复项**：主动消息已到点送达测试 QQ，AstrBot 核心重启后任务与 NapCat 连接已恢复；整机重启后的自动启动和登录仍未验证。2026-10-20 只读检查未在 Windows 计划任务、系统启动项或当前用户启动文件夹发现 AstrBot/NapCat/Miruku 的常规启动项；不能据此断言不存在其他启动机制。

5. **零可观测性**：没有任何指标能衡量"陪伴质量"（回复率、会话时长、中途沉默、危机触发次数）。没有度量，画像调优都是盲调。

### 低优先级

6. `analyze_chat.py` 目前是"打印统计"而非"产出可复用画像"，与阶段 0"不做画像提取"一致，暂不动。

---

## 五、核心设计决策（需新窗口理解，不要推翻）

1. **短句口语化是最高优先级**：聊天记录校准显示，目标方中位 4 字、约 98% 不超过 15 字、句号率仅 0.1%。所以 Miruku 的回复要"比初稿更短、更口语、几乎不加句号"。

2. **三档模式切换**（写死在 `prompts/system.txt`）：
   - 普通陪伴模式：短句、偶尔口头禅、可发图片
   - 情绪低落模式：停用刀子嘴/口头禅，先接住再给具体建议
   - 严肃/危机模式：自伤意图 → 只问一次"你现在安全吗？"，给行动建议，不追问方法细节、不诊断、不承诺治愈

3. **复用不重造**：主动调度直接用 proactive_chat 插件，长期记忆参考 mem0/langmem 但第一版只用 SQLite + 摘要 + profile.json。

4. **隐私边界**：聊天记录只借鉴口吻，不复制隐私；API Key / jwt_secret 永不打印；`data/`、`images/`、`logs/` 不提交代码仓库。

---

## 六、本次已完成的改动（重构）

**目标**：在不改变任何功能行为的前提下，消除工程债。

**新增文件** `miruku_client.py`，提供统一接口：

| 接口 | 作用 |
|---|---|
| `INSTANCE` / `instance_path()` | 路径，支持 `ASTRBOT_CORE` 环境变量和本机 `.env`；无效配置明确报错 |
| `BASE` / `dashboard_url()` | 动态端口发现 + `ASTRBOT_DASHBOARD` 覆盖 |
| `get_token()` | 签 5 分钟 HS256 JWT |
| `auth_headers()` | 仅 Authorization（供 requests 的 files=/json= 用） |
| `json_headers()` | Authorization + Content-Type（供 urllib 裸 body 用） |
| `api()` | 统一请求封装 |
| `latest_private_session(qq, max_age_minutes=30)` | 收敛 data_v4.db schema 与 30 分钟窗口 |

**重写文件**：`deploy_miruku.py`、`setup_stage0.py`、`configure_proactive.py`、`verify_stage0.py` —— 全部改为 `from miruku_client import ...`，删除重复实现。

**关键细节（新窗口注意）**：
- `setup_stage0.py` / `verify_stage0.py` 用 `requests` 的 `files=`/`json=`，header **只能含 Authorization**（加 Content-Type 会干扰 multipart 边界）；`deploy_miruku.py --probe` 用 `urllib` 裸 body，**需要** Content-Type。因此拆成两个函数。
- 系统 Python 缺 `jwt`/`psutil`，import 会失败是**预期**，脚本只能在 AstrBot 实例 Python 环境跑。

**验证状态**：`py_compile` + AST 解析通过；2026-10-20 已用 Launcher 实例 Python 执行 `deploy_miruku.py --probe`，人格同步和四类本地回复均成功。口吻探针暴露出身份措辞过于工程化、普通/低落回复偏长且使用句号等质量偏差；核心提示词已定稿，后续是否调整需先与用户讨论。

WorkBuddy 在 2026-10-20 加入“主动袒露时接住、不分析不追问”规则后，Codex 再次用同一实例 Python 运行本地探针：身份、普通、低落、危机四类均有回复；额外测试“[自我否定类表达]”“[欲言又止类表达]”和游戏语境中的“难受死了”。前两类回复简短且没有追问，游戏玩梗没有被误判成危机。仍见日常回复偏长、使用句号及猜测对方状态的倾向，尚未调整定稿提示词。该次复核时 AstrBot 原本已停止；临时启动实例测试后已恢复停止状态，未向 QQ 发送测试消息。

---

## 七、下一步该做什么（供新窗口自主规划）

> 以下方向已结合用户 2026-10-19 晚的最新决策更新，新窗口据此推进，无需再向用户追问这三件事。

### 已确认的项目前提（用户拍板，不要再问）

1. **规模假设 —— 已确认**：最终只服务那一个特定的人（QQ 10000002）。
   但用户明确表示：**"过度设计无所谓，我不希望出岔子"**。
   → 含义：**不砍复杂度**。画像库、主动调度、插件化都要保留并做扎实，
     优先级是"稳、不出岔子"，而非"极简、省事"。上一窗口此前"服务 1 人应砍复杂度"的判断作废。

2. **成功度量 —— 未定，但已明确必须补**：用户尚未想清楚"如何判断陪伴效果好"，
   但已认同下述判断，故度量问题**不再搁置，而是作为待落地项**：
   → 判断：**没有度量，"出岔子"本身无法被及时发现**。Miruku 说错话、冷场、过度追问、
     在对方低落时用错语气，都不会主动报错，只会静默发生，直到对方不再回复——
     到那时已无数据可回溯。这与用户"不出岔子"的诉求直接冲突。
   → 落地方式（最低成本、最高回溯价值）：先只记录少量原始字段，不做分析——
     - 每次会话的消息条数
     - 对方（peer）的回复间隔
     - 是否触发危机模式（以及触发时的上下文标记）
     - 是否触发情绪低落模式
     现在多存几个字段几乎零成本，换来"出岔子时可回溯"的能力。
   → 注意：具体度量方案仍需先和用户确认，不要擅自拍板；但"先记录原始字段"这条
     可直接纳入 P2 规划，不必等用户想清楚完整的"效果指标"。

3. **稳定性 vs 优化 —— 委托 Codex 判断**：用户表示"不清楚最优解，交给 Codex 判断，
   大部分项目文件都是 Codex 生成的"。
   → 含义：后续技术决策**优先由 Codex 主导**，但 Codex 需向用户解释理由后执行。

### 建议的下一步候选（按优先级，Codex 可自行调整并说明理由）

- **P0 冒烟验证（已完成）**：2026-10-20 使用 Launcher 实例 Python 执行 `deploy_miruku.py --probe`，四类本地回复均成功。
- **P1 稳定性闭环（核心路径已完成）**：主动消息到点送达测试 QQ，AstrBot 核心重启后任务恢复、NapCat 重连；整机重启后的自动启动和登录另行验证。
- **P2 可观测性**：先落地"最小原始字段记录"（会话消息数、peer 回复间隔、危机/低落模式触发标记），
  这是"不出岔子可回溯"的基础，成本极低、可直接做；完整的"效果指标"方案再与用户确认。
- **P3 剩余重构（当前已处理）**：实例路径已 `.env` 化；`data_v4.db` 查询已只读、校验 schema 与时间戳。后续 AstrBot 升级时仍需复核兼容性。

### 明确的边界（不要做）

- 不导入原始 QQ 聊天记录进每轮 Prompt（只做离线校准）
- 不填真实危机电话（OTTO 尚未提供）
- 不实现 Miruku 画像自动提取（阶段 0 明确不做）
- 不自定义主动调度器、不把 Docker 作为第一版运行方式
- 不因"只服务 1 人"就砍掉画像/主动调度/插件化（用户明确要保留并做扎实）

---

## 八、给新窗口的快速上手命令

```bash
# 语法/AST 检查（系统 Python 即可）
python -m py_compile miruku_client.py deploy_miruku.py setup_stage0.py configure_proactive.py verify_stage0.py

# 真机冒烟（必须用 AstrBot 实例的 Python 环境，且实例运行中）
python deploy_miruku.py --probe        # 完整口吻检查（四类场景）
python deploy_miruku.py --probe --probe-crisis  # 仅危机场景
```

---

## 附：关键文件清单速查

| 文件 | 一句话说明 |
|---|---|
| `prompts/system.txt` | 人格+口吻+危机兜底的**权威提示词**，改它影响最终聊天 |
| `persona/tone_profile.md` | 口吻校准结论（中位 4 字、句号 0.1%） |
| `profiling/profile.json` | 已校准的首版用户画像 |
| `docs/deployment-matrix.md` | 阶段 0 验收的唯一权威记录 |
| `miruku_client.py` | 本次重构新增的公共模块 |
