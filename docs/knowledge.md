# Miruku 知识库

给 Miruku 的「事实底子」：舞萌DX、明日方舟、三国杀、网络热梗、VRChat 小男娘、番剧动画、V 圈、术力口、东方 Project、常聊的其他游戏，以及 Miruku 自身。
和口吻/人格文件分工：`prompts/system.txt` 与 `persona/` 管怎么说，这里管「说什么、说的是不是真的」。

## 文件

| 路径 | 作用 |
| --- | --- |
| `knowledge/src/<topic>.json` | 人工维护的条目源文件，一个文件一个主题 |
| `knowledge/build_knowledge_db.py` | 校验并合并成 SQLite，同时生成 `digest.md` |
| `knowledge/miruku_knowledge.sqlite3` | 查询库（topics / entries / entries_fts） |
| `knowledge/query.py` | 中文友好的查询 CLI（2 字词也能查） |
| `knowledge/inject.py` | 把一条消息转成可直接拼进 prompt 的「可参考的知识」块 |
| `knowledge/lint.py` | 体检：注入路径（title/summary）里有没有内部路径、账号、系统实现词 |
| `knowledge/build_review.py` | 生成单文件审阅页 `knowledge/review.html`（给人看的，不进 prompt） |
| `knowledge/digest.md` | 全部条目的短摘要（排除 sensitive）；当前约 40 KB，整段常驻会明显撑大 prompt，只作调试/降级用 |

## 构建与查询

用系统 Python 3.9 即可（只用标准库）：

```bat
python knowledge\build_knowledge_db.py
python knowledge\query.py 何意味
python knowledge\query.py 源石 搓玉 --topic arknights --limit 3
python knowledge\query.py 夏玛 --full
python knowledge\query.py 三国杀 --json
```

每次改完 `knowledge/src/*.json` 都要重跑构建；构建是「全量重建」，不会留旧条目。

当前规模：12 个主题 560 条（maimai 215 / b50 52 / anime 47 / touhou 42 / vocaloid 40 / vtuber 37 / memes 27 / arknights 24 / self 22 / sanguosha 21 / vrchat 17 / games 16），库约 1.9 MB，digest 约 49 KB。
舞萌 211 条里有 149 条是具体曲目（15 级 3 首、14.7 以上 14 首、13.x–14.x 热门一百多首，含来世会主动讲的 30 首「故事锚点曲」里的 29 首），难度和 BPM 全部取自 lxns 曲库 API 的 `level_value`，不是手写；另有 34 条玩法术语、21 条圈内文化、7 条 KALEIDXSCOPE 解谜条目。

`games` 这 11 条是照着真实聊天频率补的，不是通用游戏百科：来世聊得最多的非音游是街霸6（杰米是他的主玩角色）、三角洲行动的搜打撤（含「大红/爆率/藏宝图/摸回来」这套黑话）、英雄联盟的斗魂竞技场和海克斯大乱斗。这几块原来一条都没有，问到就露馅。同主题下只收「聊到能接住」的深度，不写连招帧数这类会被追问到崩的细节。

`self/平时做什么` 的摘要 2026-10-22 改写过：原来写「没有真人的日程」，是设定说明，被注入后容易让回答变成自我介绍；现在写「Miruku 也有自己的小日子：可能在喝牛奶、在打舞萌，也可能就在发呆」，detail 要求「随口说一件手头的小事，一两句带过，不要写成自我介绍」。

KALEIDXSCOPE 那 7 条（源文件 `data/maimai/kaleidxscope_entries.json`，由 `merge_maimai.py` 合并进 `maimai.json`）覆盖：模式本身、ACID、Ris、7sRef、最终阶段 Gate of Hope、第七道门与蓝屏、最后的希望。ACID 和 7ref 就是这一串解谜里的角色名和世界名——本机 `web_search` 没有 key、萌娘百科 403，内容是从 `silentblue.remywiki.com` 的 KALEIDXSCOPE 词条和 `/Acid LINE chats` 逐段读出来的，剧情以那份英文维基为准。

改完 `knowledge/src/*.json` 后建议按顺序跑：

```bat
python knowledge\lint.py
python knowledge\build_knowledge_db.py
python knowledge\build_review.py
```

## 条目格式

```json
{
  "topic": "maimai",
  "title": "舞萌DX",
  "description": "一句话说明这个主题覆盖什么",
  "entries": [
    {
      "slug": "ji-ting",
      "title": "机厅",
      "aliases": ["街机厅", "打机"],
      "summary": "一句话、≤60 字、口语，能直接拿来接话",
      "detail": "补充事实、边界、常见误解；可以长一点",
      "tags": ["maimai", "日常"],
      "source": "来源 URL 或「聊天记录（10000002）」",
      "confidence": "high",
      "sensitive": false
    }
  ]
}
```

规则：

- `slug` 在同一个 topic 内唯一；`summary` 超过 60 字构建会报错。
- `source` 尽量给；公开设定给链接，聊天里的梗写「聊天记录（10000002）」。
- `confidence`：high=公开设定/反复出现；medium=二手资料或只出现过一两次；low=存疑。
- `sensitive: true` 用于性暗示、身材、真人评价类条目，运行期默认不注入。
- 不写聊天原文，不写来世的个人信息、住址、账号、隐私；知识库只放「Miruku 该知道的事实」。
- `detail` 里写「来世说过 X」是为了接梗，别写成背档案；不要写城市、舍友、账号链接这类私人细节（`knowledge/lint.py` 会提示）。
- 不要在 `title`/`summary` 里出现项目内部路径、QQ 号、AstrBot/NapCat/插件/部署这类词——这两栏会被注入 prompt，模型可能顺着说出来。

### 关于真人条目（V 圈、番剧声优、P 主）

- 只写**公开的、不容易过期的**信息：出道年份、所属、设定、代表曲。**不要写毕业/停止活动的具体月份**，这类变动频繁，写错就是硬伤；宁可用「现在已不在活动名单里」这种模糊说法，或干脆不提。
- 涉及纠纷、争议、公司内部人事时，`sensitive: true`，并且只写「发生过什么」，不评价当事人、不站队。
- 中之人（真人身份）一律不写。开盒类条目只描述现象和「不传播」，不写任何具体姓名、地址。

## 运行期接入（给 Codex）

> **状态（2026-10-24 更新：已接通，只差一条真实消息验证）。**
> - 插件 `plugins/astrbot_plugin_miruku_knowledge/`（`MARK`、`_load_builder`、`_matches`、`add_knowledge`），实例副本与仓库 sha256 一致（`af9aae0d…`），已通过 `POST /plugins/reload` 热重载生效（日志 `09:59:41 Terminating → Removed handler → Loading → 0.1.0 by OTTO`）。
> - 实例配置：`platform_id=miruku`、`target_qq=10000002`、`knowledge_root=C:\Users\OTTO\Desktop\来世\knowledge`。
> - 2026-10-24 对抗审计（`docs/ds06-knowledge-injection-audit.md`）找出 F1–F9，**F1–F7 已全部修完**：三首 b50 曲子转正、`b50_block.txt` 移除、六项跳过计数与 `armed` 日志、`db_path` 与校验路径同源、空 root 报错、`RuntimeError` 替代 `SystemExit`、连接 `finally` 关闭。
> - **仍未验证的一环**：日志里还没有 `[Miruku knowledge] armed: platform=miruku` —— 它只在第一条**命中**的真实私聊上打一次。需要一条真实消息（OTTO 的测试号即可）。
>
> **以下 2026-10-22 的核实记录保留作历史**（当时确实没接通，b50 在实例里等于不存在）：
> - 实例 `core/data/plugins` 下 grep 不到 `inject` / `build_block`；实例数据目录 grep `14065` = **0 条**。
> - 实机问「KING 你多少分」答"KING 那首没刷过"，而库里 KING 是 13.0 / SSS / R280——证明请求里从来没有这张表。
> - 现在只有离线脚本在调 `build_block`（`data/inject_audit.py`、`data/probe_regression.py`、`data/diff_hits.py`）。
>
> **落点（都已在实例源码里核实，照抄 soulmap 即可）**
> - 钩子调用点：`core/astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py:307` → `call_event_hook(event, EventType.OnLLMRequestEvent, req)`
> - 注册器：`core/astrbot/core/star/register/star_handler.py:433`，其 docstring 给的写法就是 `req.system_prompt += "..."`
> - **现成范例**：`core/data/plugins/astrbot_plugin_soulmap/main.py:211` 已在用 `@filter.on_llm_request()`，签名 `(self, event: AstrMessageEvent, req: ProviderRequest)`
> - 可写字段：`ProviderRequest.system_prompt`（`core/astrbot/core/provider/entities.py:113`）、`extra_user_content_parts`
>
> **实现草案（已在本机模拟验证，`data/probe_inject_hook.py` 12/12 通过）**
>
> 前提：实例 venv 里 `sys.path.insert(0, <项目>/knowledge)` 后 `import inject` 可用（实测通过）。项目根路径**不能写死**，加一个配置项：
>
> `_conf_schema.json` 增 `knowledge_dir`（string，默认 `C:/Users/OTTO/Desktop/来世/knowledge`，留空 = 关闭注入）。
> 这样迁移机器、或想临时关掉注入时不用改代码。
>
> ```py
> # 顶部
> import os, sys
> from astrbot.api.provider import ProviderRequest     # 与 soulmap main.py:9 同一条 import
>
> MARK = "<!-- miruku-knowledge -->"   # 去重标记：重试/多 provider 时防止块被叠两遍
>
> # class 内
> def _load_inject(self):
>     path = str(self.config.get("knowledge_dir", "")).strip()
>     if not path or not os.path.isdir(path):
>         return None
>     if path not in sys.path:
>         sys.path.insert(0, path)
>     import inject
>     return inject
>
> @filter.on_llm_request()
> async def inject_knowledge(self, event: AstrMessageEvent, req: ProviderRequest):
>     if not self._matches(event) or not event.is_private_chat():
>         return                                    # 只管目标号私聊，群聊不注入
>     if MARK in (req.system_prompt or ""):
>         return                                     # 幂等
>     inject = self._load_inject()
>     if inject is None:
>         return
>     block = await asyncio.to_thread(inject.build_block, event.message_str)
>     if not block:
>         return                                     # 0 命中：一个字都不加，别塞空标题
>     req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n" + MARK
> ```
>
> 两个必须遵守的边界：① **只对目标号私聊生效**（`_matches` 已判 platform + sender，但 sender 命中不等于私聊——他在群里说话 sender 也是这个号，所以 `is_private_chat()` 不能省）；② 命中 0 条时**不要**追加空块或标题行。
>
> 三条已验证的行为（`data/probe_inject_hook.py`）：
> - 私聊问「KING 你多少分」→ 注入「曲子背景 + 真实成绩」两条；
> - 「今天好累」「晚安」→ 一个字不加；
> - 同一 req 连调两次 → 只加一个 `MARK`，不重复。
>
> **新增护栏（`inject.py:SCORE_GUARD`，本次补）**：问成绩但块里没有按曲目写死的成绩时（如「ロキ多少分」——只命中曲子背景 16.5 分，而「b50 之外的歌不要报数字」那条只有 1.0–1.8 分、永远过不了阈值），自动补一行「b50 只记最好的 50 首：上面没写成绩的歌就说没怎么刷过，不要报数字」。**一句话：最需要这条规则的时刻，恰恰是它自己不会被注入的时刻。**
>
> **接通后要收尾的两件事（2026-10-24 已做完）**：① `b50/work/gen_b50_block.py --off` 已执行，`prompts/b50_block.txt` → `prompts/b50_block.txt.bak`，重部署后 persona **4643 → 3320 字符**（回到纯 `system.txt`）；② `data/probe_regression.py` 仍 120/120，50 首逐首问「歌名 多少分」**50/50 命中**（改前 47/50，缺的三首由 F1 修复补上）。**现在 b50 只有一个来源**：`knowledge/src/b50.json`。回滚：`mv prompts/b50_block.txt.bak prompts/b50_block.txt && <venv python> deploy_miruku.py`。

推荐 **A：预检索注入**，和现有消息管线改动最小。

1. 收到消息后，用消息文本调 `knowledge/inject.py "<消息文本>"`（或直接 import `query.search` + `inject.build_block`）。
2. 它已经做了三件事：只取 score ≥ 10 的条目（弱相关不注入）、默认过滤 `sensitive`、总长控制在 600 字内。有命中会输出一段：

   ```
   可参考的知识（只在相关时自然用上，不要逐条复述，不要说“知识库”）：
   - 夏玛：Miruku 憧憬的偶像……
   ```

3. 作为 system 之外的临时上下文注入本次请求；**stdout 为空就表示没命中，不注入，别硬塞**。
4. 命中 0 条时不要编，按人设说「不知道」「没打过」。

### 阈值是怎么定的（别随手调低）

`inject.build_block` 的 `min_score=10.0` 是拿真实聊天记录标出来的，不是拍的。用 400 条真实私聊消息跑 `data/inject_sample.py`：

- `min_score=8` → 命中 17%，但里面全是误命中（「看你忙一天」命中一首叫《忙シー日》的曲子、「学校对面的」命中别名带「学校」的 Panopticon），等于每 6 条消息就塞一次不相干的知识。
- `min_score=10` → 命中 1.8%，剩下的基本是「出勤」「改模」「何意味」这种真的在聊该主题的消息。
- `min_score=12` → 命中 1.2%，但「这个谱面鸟了」这种短句会被漏掉。

调低到 8 以下会让模型**看起来什么都知道**，代价是它开始在闲聊里莫名提一首歌——比不知道更出戏。

另外 `query.normalize` 会先剥掉 `[图片:...]`、`[表情:...]` 这类占位符再取 n-gram。不剥的话占位符里的十六进制串会被当成检索词（「39」命中初音未来的别名），每张表情包都会注入一条不相干的知识。

其他方案：

- **B 工具调用**：注册 `lookup_knowledge` 让模型自己查。最灵活，但当前有 DSML 工具调用泄漏 bug（见 `docs/tone-tuning-20261020.md`），不建议现在上。
- **C 静态摘要**：把 `digest.md` 整段追加到 system prompt。最简单，但当前 560 条约 49 KB，每轮都带会明显膨胀，不建议；条目很少或做临时演示时才用。
- **D AstrBot 知识库/RAG**：需要 embedding provider；当前 livingmemory 的 Embedding Provider 没配好，工程量最大，暂不做。

## 与聊天数据库的分工

- `data/chat_content.sqlite3`：历史聊天原文，只读、私密，**不进 prompt**；用来查「以前说过什么」、做校准。
- `knowledge/miruku_knowledge.sqlite3`：结构化知识条目，可以按需注入；用来保证「说的是对的」。

## 维护

### 加一条 / 改一条知识：用 `knowledge/add.py`

```bash
PY="C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe"

$PY knowledge/add.py --list-topics                       # 看有哪些主题、各多少条

# 新增（--test 是真实会出现的问法，必须写）
$PY knowledge/add.py --topic maimai --slug xin-qu-ming \
    --title "新曲名" --aliases "新曲,简称" \
    --summary "定数 13.2，她打过。" --test "你怎么看新曲名"

# 改已有条目（成绩刷新走这条；只覆盖你给的字段）
$PY knowledge/add.py --topic b50 --update wo-de-b50 \
    --summary "总 R 14200，金框……" --test "你R值多少"

# 只预演，不落盘
（上面任何一条加 --dry-run）

# 排查「她为什么不知道这首」
$PY knowledge/add.py --topic maimai --check <slug> --test "问法"
```

### 为什么必须带 `--test`

注入阈值是 `inject.py:46` 的 `min_score=10.0`。**低于 10 分的条目永远不会进上下文，而且不报错**——库里有、聊天时不出现，你只会觉得「她怎么不知道」。

b50 那轮踩过：单曲条目只 **3.2 分**，把曲名插成第一条别名才到 **20.0**。

`add.py` 用 `query.score()` 预算分数。它是**纯函数**（不依赖 idf／全局统计），所以预演分数与运行期分数**完全一致**——`data/probe_add_knowledge.py` 的第 1 项断言就是这条。分数不够它**拒绝落盘**，并告诉你该补哪些别名；确实只想放背景知识才用 `--allow-weak`。

### 落盘后要不要重启？不用

- `query.py:383`：每次 `load_entries` 都新开 `sqlite3.connect`；`search()`（`:739`）无结果缓存。
- 实测一轮注入 **24–30ms**（548 条时测得；560 条同量级，全表加载 8.5ms），每轮 LLM 请求重算，代价可忽略。

所以重建之后**下一个请求就读到新库**，不必重启 AstrBot。

### 一个限制：重建时若有进程在读，会**失败**（这是故意的）

Windows 上 `os.replace` 只要目标文件被打开就抛 `WinError 5`——实测 sqlite 连接持有、普通 `open` 持有都会失败。旧代码在这种情况下**降级为覆盖写**，而覆盖写会先把目标截成 0 字节；运行中的进程若正好在读，就读到半截库（`no such table`），表现是**她突然不说话**。

2026-10-23 改为：**重试 6 次（约 4 秒）→ 仍失败就抛错，绝不覆盖写**（`build_knowledge_db.py:183` 重试循环、`:194` 抛错）。
`add.py` 收到失败会回滚 JSON，所以**重跑不会重复添加**。代价是偶尔要重跑一次；换来的是构建动作不会毁掉一次真实对话。

### 两条不许忘

1. **b50 现在只有一个来源（2026-10-24 起）。** 原来的 `prompts/b50_block.txt`（1322 字，`deploy_miruku.py:17–19` 拼进 `system_prompt`）已改为 `.bak` 不再部署，真值只剩 `knowledge/src/b50.json` 一份。**改成绩只改 `knowledge/src/b50.json` 一处**，改完重建库即可；若哪天要回滚到 block 兜底，先 `mv prompts/b50_block.txt.bak prompts/b50_block.txt` 再 `deploy_miruku.py`，但那样两份数据又会并存，别忘了改两处。
2. **敏感条目**：`--sensitive` 的条目运行期默认不注入（`search(include_sensitive=False)`），只供人工查阅。

### 其它

- 新增主题：加一个 `knowledge/src/<topic>.json`（格式见上），`add.py --list-topics` 应能看到它。
- 发现答错：先用 `--check` 区分两种原因——**没被检索到**（分数低，补别名）还是**检索到了但摘要写得不对**（改 summary）。修法完全不同。
- 隐私：`data/` 与 `knowledge/*.sqlite3` 已被 `.gitignore` 排除；`knowledge/src/*.json` 只放知识条目，不放聊天原文和来世的个人信息，不要外发。
