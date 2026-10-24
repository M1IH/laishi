# DS-06 知识注入独立对抗审计

**审计对象**：`plugins/astrbot_plugin_miruku_knowledge/`（路线 A：预检索注入）+ `knowledge/inject.py` + `knowledge/query.py`
**审计方式**：离线。直接 import 生产插件 handler 与生产 `build_block`，用假 event / req 走完整判定路径；不重载插件、不发 QQ、不改生产文件。
**交付**：本文件 + `data/probe_knowledge_adversarial.py`（25 条用例 + 4 项专项）
**结论**：**注入链路本身是通的、会话边界是对的、敏感条目确实进不去**；首轮审计发现 1 个漏注入（3/50 首 b50 曲子自然问法静默不注入）与 1 个阻断移除 `b50_block.txt` 的覆盖缺口，**已于 2026-10-24 修复并验证**（见 F1/F2 与 §四）。其余为可观测性/健壮性问题，交 Codex 按优先级处理。**C-15 的运行终验仍归 Codex**（本审计只到离线层）。

---

## 一、怎么跑

```bash
PYTHONIOENCODING=utf-8 \
"C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe" \
data/probe_knowledge_adversarial.py
```

| 命令 | 退出码 | 含义 |
| --- | --- | --- |
| 无参数 | **0**（F1 修完后） | 全过。首轮审计时是 1（3 条已登记缺陷）。 |
| `--allow-known` | 0 | 放过已登记缺陷；未登记的仍然 1 |
| `--verbose` | — | 逐条打印 PASS 与子进程场景详情 |

`KNOWN_BUGS` 现已清空（F1 三条销账）。留着这个开关是为了下一批缺陷：**登记了就必须让默认跑退 1，不许把已知故障伪装成全过**。

**别用 `| tail` 取退出码**——拿到的是 `tail` 的退出码。这条在 DS-04 已经踩过一次。

---

## 二、验证通过的部分（有正负对照，不是「MARK 在就算过」）

| 维度 | 用例 | 结果 |
| --- | --- | --- |
| 指定私聊 | `private-target` | 注入，且块以 MARK 结尾、含表头 |
| 非指定私聊 | `private-other`（sender=10001） | 不注入，`system_prompt` **一字未改** |
| 群聊（同一个人） | `group-target`（`is_private_chat()=False`） | 不注入 |
| 平台不符 | `platform-other`（platform=webchat） | 不注入 |
| 空 / 纯空白 / 纯表情占位 | `empty` / `blank` / `sticker-only` | 不注入 |
| 普通闲聊 | `today好累` / `在吗` | 不注入 |
| 精确曲名 | `song-title`（KING） | 注入，含 `280`（真值） |
| 别名 / 术语 | `song-alias`（鸟加）、`machine`（洗衣机） | 注入正确条目 |
| 低于阈值沉默 | `below-threshold` | 不注入 |
| 表内成绩 | `b50-real` | 报真数字，**不带**兜底护栏 |
| 表外曲目 | `out-of-b50`（ロキ） | 注入背景 + `只记最好的 50 首…不要报数字` 护栏，且**不含** `单曲 R`/`定数` 数字 |
| 表外但不问成绩 | `out-of-b50-noguard` | 只注入背景，不硬塞护栏 |
| 街霸6 口径 | `sf6-knows-not-plays` | 注入「不打但懂，问打不打就说我不打」 |
| 舞萌自身口径 | `maimai-self` | 注入 `R 14065 / 金框`（无 `w4` 旧口径残留） |
| 敏感条目不进上下文 | `sensitive-kaohe` / `sensitive-yanshang` / `sensitive-weipi` | 三条全不注入；同层对照 `vtuber-ok`（hololive）**注入**，证明不是「一律不注入」也能过 |
| 幂等（同 req 调两次） | 专项 1 | 只加一次，MARK 与表头各 1 处 |
| `target_qq` 留空 | 专项 2 | 不注入 |
| 长输入上界 | 专项 3 | 4000 字输入下注入块仍 ≤ 640 字符 |
| 库缺失 / 损坏 / 空库 / 运行中删库 | 专项 4（子进程） | 四种全部 fail-closed：不注入、不逃逸异常 |
| 泄漏检查 | 全部注入用例 | 块正文无 `knowledge/src`、`.sqlite3`、`b50.json`、`Traceback`、裸 `<!--` |

**运行态同步**：实例插件与仓库源码 sha256 一致（`e2f23603fea5af67…`）；日志 `logs/astrbot-20261024.log:95-97` 显示 `2026-10-24 08:24:29.776` 已加载该插件；实例配置 `core/data/config/astrbot_plugin_miruku_knowledge_config.json` 为 `platform_id=miruku`、`target_qq=10000002`、`knowledge_root=C:\Users\OTTO\Desktop\来世\knowledge`。**证据等级：已验证（文件哈希 + 加载日志 + 配置内容三处互证）。**

---

## 三、发现

### F1（P1，漏注入）b50 里真实有成绩的 3 首，自然问法静默不注入 —— **已修复（2026-10-24）**

**修复后**：`QUEEN 多少分` → 14.17、`Cthugha 多少分` → 14.12、`不思議の国のクリスマス 多少分` → 22.09，三条都注入到正确条目；b50 五十首「歌名 多少分 / 你多少分 / 什么评级」三问法 **50/50 全覆盖**（修复前 47/50）。

**修法（`knowledge/query.py`，不动 `clean_query`、不动阈值）**：新增 `loose_query()`——比 clean 形式更宽松，**只摘多字疑问词和「多少分 / 什么评级 / 多少r」，单字停用词一个不删**。别名在 clean 形式匹配不上时用它兜底，条件是「别名 ≥3 字，且 clean 之后仍有 ≥3 字」。

- 为什么不动 `clean_query`：它被 120 条回归用例依赖，改它等于重标定整条链路。实测第一版想直接放宽单字删词，立刻把「真的假的」重新注入《会赢的》（clean 后只剩「真/假」），所以兜底路径必须带长度门槛。
- 为什么 `QUEEN` 要优先用宽松形式算覆盖：clean 形式是 `queen多少分`（「多少分」不在停用词里），别名只能拿 5/8 打折 = 8.75；宽松形式摘掉「多少分」后正好是整段 `queen`，该给满分。所以 `base` 的选择是「宽松形式里独立成段就用它，否则用 clean 形式」。
- 副作用核验：全量 8,663 条真实私聊命中 **389 → 391 条（4.49%→4.51%）**，净增 2 条且都是这三首的真命中；`学校的猫`、`监狱里那个`、`什么意思`、`有格调`、`忙了一天` 仍全部 EMPTY。

<details><summary>修复前的现场记录（保留，便于 Codex 复核改动动机）</summary>

复现（生产 `build_block`）：

```
build_block("QUEEN 多少分")                 -> ""      （QUEEN 12.8 SSS R277 在 b50 里）
build_block("Cthugha 多少分")               -> ""      （Cthugha 12.5 SSS+ R281 在 b50 里）
build_block("不思議の国のクリスマス 多少分") -> ""      （MASTER 13.3 SSS R288 在 b50 里）
```

得分（`query.score` 对 `b50-*` 条目取最大）：`QUEEN 9.97`、`Cthugha 9.92`、`不思議の国のクリスマス 7.00`——全都 < `min_score=10.0`，于是 `build_block` 在 `knowledge/inject.py:67-68` 直接 `return ""`。

两个不同根因：

1. **ASCII 标题的别名覆盖率打折卡在阈值线上**（QUEEN / Cthugha）。
   `QUEEN 多少分` → `clean_query` 得 `queen多少分`（**「多少分」不是停用词，没被删**），别名 `queen` 靠包含命中，但覆盖率打折 `14 * max(0.7, len(an)/len(qn)) = 9.8`，加上少量 n-gram 才到 9.97。
   同一句换成 `QUEEN` 单独问 → 20.0+ 注入。**差一个「多少分」就翻面。**
2. **单字停用词从标题中间删字**（不思議の国のクリスマス）。
   `clean_query` 把 `不` 当停用词删掉 → `思議の国のクリスマス多少分`，别名匹配失效，只剩 n-gram 7.0。
   同理，任何含 `不 / 没 / 着 / 过 / 这 / 那` 的曲名或条目名都会被清成残形。

**影响**：这三首她**真有成绩**。不注入时不仅答不出，还会因为「没有块 → 不挂 `SCORE_GUARD`」（见 F2 相关盲区）而说出「没刷过」或自己编一个数字。对一个「R 14065 金框」的人设，这是最伤的一类错误：**不是不知道，是知道自己有却说没有。**

**最小修法（两处，都不改阈值）**：
- `knowledge/query.py` 的 `STOP_PHRASES` 里，**单字停用词只允许在句首/句尾/被分隔符包围的位置删除**，不允许从词中间删（或干脆把 `不/没/着/过` 这类只保留多字组合形式，如「不是」「没有」）。
- `knowledge/query.py` 的别名覆盖率打分：当别名长度 ≥ 4 且 `an in qn` 时，不要用 `len(an)/len(qn)` 打折到 0.7 这条地板（改为「长别名给满权重」）。

**判定**：已验证（可复跑）。修复前三条在探针里登记为 KNOWN。

</details>

最终采用的修法见本节开头。上面两条是当时的初版建议——**第二条（长别名给满权重）没有采用**：它会把「学校」「监狱」这类别名在长句里的权重一起抬高。实际用的是「另开一条宽松形式做兜底」，改动面更小，120 条回归零退化。

### F2（P1，阻断移除 b50_block）`prompts/b50_block.txt` 的覆盖缺口 —— **已解除（2026-10-24）**

F1 修完后覆盖 **50/50**，按 §四四条门槛执行移除：`prompts/b50_block.txt` 改名为 `prompts/b50_block.txt.bak`，重跑 `deploy_miruku.py`，线上 persona **4643 → 3320 字符**（回到纯 `system.txt`）。同曲不再出现「persona 旧定数 + 知识条目新定数」两份，也不再重复注入。
回滚一行：`mv prompts/b50_block.txt.bak prompts/b50_block.txt && "<实例 venv>/Scripts/python.exe" deploy_miruku.py`。

注：`deploy_miruku.py` 会**保留运行时的分段开关**（本次跑完打印 `Segmented reply enabled: True`，说明它此前已被打开，不是本次改动——脚本注释也写明「deployment only selects persona」）。

<details><summary>移除前的现场记录</summary>

实测线上 persona：`system.txt` 3320 字符 + `b50_block.txt` 1322 字符 = **4643 字符**（`GET /personas/by-id?persona_id=miruku`），也就是那 50 首成绩**每轮都在 system prompt 里**。

把 block 里 50 首逐条拿去问「歌名 多少分」：**47/50 命中，3 首缺失**（就是 F1 那三首）。
也就是说：**当时移除 `b50_block.txt`，这三首会立刻从「答得准」退化成「不知道」**，而 `SCORE_GUARD` 只在她已有块时补护栏（`knowledge/inject.py:81-85`，且 `:67-68` 早已 return），这一轮连护栏都不会挂。

另外两处不一致（移除前要一起处理）：
- **定数版本**：persona block 写的是 2026/02 那版定数（さよならプリンセス 13.1、ザムザ 12.9、LOSTPHANTASIA 12.7、にっこり 12.8），知识条目按 lxns 现行为准并在 detail 里补了档位；两边并存时同一首歌会出现两个「定数」。
- **重复注入**：block 在 persona 里常驻，命中时再加一遍同曲条目——一轮里同一首歌的事实出现两次，且 block 那份**没有档位信息**（会把 EXPERT 的 13.0 当 MASTER 报）。

**判定**：已验证（覆盖 47/50、persona 长度 4643、两处数字对照）。

</details>

### F3（P2，不可观测）跳过时不打任何日志、不留计数 —— **已修复（2026-10-24）**

`main.py:55-59` 的三条早退（不匹配会话 / MARK 已存在 / 空消息）**完全静默**；只有异常分支 `:65` 打一行 `logger.error(type(exc).__name__)`。
后果：`target_qq` 打错一位、`platform_id` 与平台实际 id 不一致、`knowledge_root` 写错目录——**全都会永远静默不注入，没有任何信号**。C-15 接通后「到底注没注入」只能靠猜。

**已修**：`_bump(key)` 计数（`hit` / `skip_chat` / `skip_duplicate` / `skip_empty` / `skip_no_block` / `error` 六项）+ 首次注入成功时打**一条** INFO `[Miruku knowledge] armed: platform=miruku, injections=1`，无命中打 DEBUG。**不打消息正文、不打 QQ 号、不打 target_qq。** 计数用 `getattr` 兜住 `object.__new__` 构造（探针就是那样建的）。

**判定**：已验证（源码通读，无任何非异常日志）。

### F4（P2，健壮性）`load_entries` 抛 `SystemExit`，插件的 `except Exception` 接不住 —— **已修复（2026-10-24）**

`knowledge/query.py:381-382`：

```python
if not os.path.exists(db_path):
    raise SystemExit(f"数据库不存在：{db_path}（先跑 knowledge/build_knowledge_db.py）")
```

`SystemExit` 是 `BaseException`，而插件 `main.py:62-66` 是 `except Exception`。**在探针第一版里，这条真的把整个 python 进程结束了**（`数据库不存在：…` 直接打到 stderr、后续断言全部没跑）。

生产上要触发需要「`_load_builder` 的 `is_file()` 检查通过、随后文件消失」（TOCTOU），或者 F5 的路径错位。窄，但代价是**整条事件循环被带走**，不是一条消息丢了。

**已修**：`load_entries` 改抛 `RuntimeError`，插件侧保持 `except Exception`（不动 `except` 是刻意的——改成 `BaseException` 会把 `KeyboardInterrupt` 一起吞掉）。探针里原来的「记录不判红」改成断言：抛 `SystemExit` 即判红。

**判定**：已验证异常类型（可直接调用复现）；触发路径为**推测**（未构造出稳定 TOCTOU）。

### F5（P2，路径没固定）校验的是 `root/miruku_knowledge.sqlite3`，读的是 `query.DEFAULT_DB` —— **已修复（2026-10-24）**

`main.py:28` 校验 `root / "miruku_knowledge.sqlite3"` 存在；`main.py:61` 调 `self._load_builder()(message)`——**没有传 `db_path`**，于是 `inject.build_block` 用默认参数 `db_path=DEFAULT_DB`（`knowledge/inject.py:46-47`），而 `DEFAULT_DB` 是 `query.py` 按**自己所在目录**算出来的常量。

单个 root 下两者恒等，没问题。但 `inject.py` 会 `sys.path.insert(0, HERE)` 再 `from query import …`——一旦 `query` 已经在 `sys.modules` 里（换 `knowledge_root` 后重载插件、或同进程里跑过别的 root），就会**用旧目录的 `DEFAULT_DB`**：校验的是新库，读的是旧库。探针第一版就是这么撞上的（换个 root 仍注入了上一个 root 的数据），现在四种库异常场景改成子进程隔离才测准。

**已修**：`build_block(message, db_path=str(self._root / "miruku_knowledge.sqlite3"))`——把校验过的那个路径显式传下去。

**判定**：已验证（探针可稳定复现「换 root 仍注入旧库」）。

### F6（P3，配置脚枪）`knowledge_root` 留空会退化成当前目录 —— **已修复（2026-10-24）**

`main.py:27` `Path(str(self.config.get("knowledge_root", "")).strip())`：空串 → `Path("")` → `.`，`is_dir()` 为真，接着找 `./miruku_knowledge.sqlite3`。CWD 恰好有同名库时就会读错库；没有则 FileNotFoundError（fail-closed，尚可）。
**已修**：`raw = str(...).strip()`，为空直接 `raise FileNotFoundError("knowledge_root is empty")`，不再退化成 `.`。

**判定**：已验证（源码路径推演 + 空配置实测不注入）。

### F7（P3，资源）损坏库会让连接泄漏 —— **已修复（2026-10-24）**

`knowledge/query.py:383-391`：`con = sqlite3.connect(...)` 之后若 `con.execute` 抛错，`con.close()` 走不到。探针在 Windows 上表现为临时目录删不掉（`PermissionError: [WinError 32]` 文件被占用）——**库损坏期间每个请求漏一个连接/文件句柄**。
**已修**：`con = sqlite3.connect(...)` 之后整体包进 `try/finally: con.close()`。

**判定**：已验证（复现为文件锁 + 代码路径清晰）。

### F8（信息，已排除）钩子互相干扰

- `emotionai`：`@event_filter.on_llm_request(priority=100000)`（`astrbot_plugin_emotionai/main.py:648`）→ **先于**我们执行，它的追加不会被我们覆盖（我们是 append）。
- `group_chat_plus`：`@filter.on_llm_request(priority=-1)`（`.../group_chat_plus/main.py:10674`）会**整体重写** `req.system_prompt`（`:10974`），但 `:10705-10707` 在 `PLUGIN_REQUEST_MARKER` 缺失时直接 `return`——普通用户消息不会走到重写。**未发现干扰。**
- `livingmemory`：`@filter.on_llm_request()`（`.../livingmemory/main.py:332`），同优先级 0，只做记忆召回，不整体替换 system_prompt。

**判定**：已验证（源码行号 + 早退条件）。

### F9（信息，设计盲区，不判红）`SCORE_GUARD` 只在已有检索块时生效

`build_block("ミクマリ多少分")` → `''`（库里没有这首）。没有块 → 兜底护栏也不挂 → 模型对「完全没收录的曲子」既没事实也没「不要报数字」的约束。
这是「阈值 + 护栏」耦合的结构性盲区，不属于 L1 部署 bug，但**移除 `b50_block.txt` 前要知道**：移除后表外曲目的唯一护栏就是这条必须依附于命中的规则。
**建议**：把「问成绩但没命中任何条目」单独识别出来，只注入那一行护栏（`SCORE_GUARD`），不注入任何事实。改动很小，且不碰判定。

**2026-10-24 追加实测（这条建议不能照做）**：拿全量真实私聊（`data/chat_content.sqlite3`，来世 12,685 条，4–80 字）扫 `SCORE_INTENT`，命中只有 **3 条**：

| 原文 | 实际语境（前后各 3 分钟） | 是不是「问成绩」 |
| --- | --- | --- |
| `就上了几分` | 前一句 `退勤了` | 是（maimai 的 R 分） |
| `你平常都是打多少` | 前文在聊「今天吃了八百万 / 九百万 / 没吃到大红」 | **不是**——这是三角洲的收益，不是 b50 |
| `直接看之前的b50就知道了` | — | 是，且本来就有块 |

也就是说：**`SCORE_GUARD` 那句「b50 只记最好的 50 首」只对舞萌成立，一旦按建议无条件挂到「问成绩但没命中」上，三角洲聊收益的场景会被塞一句 b50 规则**——比不说更出戏。要做得对，得先判「这句问的是哪个游戏」，那是另一个判定问题，不该塞进 `inject.py` 的一个 if 里。

**结论**：F9 保持不修，理由从「行为变更风险」升级为「无条件挂护栏会误伤非舞萌语境，实测 1/3 命中会误伤」。真要修，前置条件是「成绩问句的游戏归属识别」，属于检索层的独立议题。

---

## 四、`b50_block.txt` 移除前门槛（任务第 3 项）

**门槛（四条全绿才允许移除）**：

1. **覆盖 50/50**：`prompts/b50_block.txt` 里每一首，用「歌名 多少分」「歌名 你多少分」「歌名 什么评级」三种自然问法都能注入到 `我的成绩：<该曲>`。**已达标：50/50**（修复前 47/50）。复跑：
   ```bash
   PYTHONIOENCODING=utf-8 "<实例 venv>/Scripts/python.exe" data/probe_knowledge_adversarial.py
   ```
   （`b50-queen` / `b50-cthugha` / `b50-fushigi` 三条已转绿并按普通正例断言。）
2. **数字与档位一致**：移除后只剩知识库一个来源，条目自带档位（EXPERT/MASTER/Re:MASTER）且定数按 lxns 现行值——本条随移除自动满足。
3. **无重复注入**：移除后同一次请求里同一首歌只能出现一次。**已满足。**
4. **回归不退化**：`data/probe_regression.py` 120/120、`data/probe_inject_hook.py` 12/12、`data/probe_knowledge_plugin.py` 8/8、`knowledge/lint.py --strict` 严重 0。**已复跑，全部保持。**

**怎么移除（已执行 2026-10-24）**：`deploy_miruku.py:15-17` 是「文件存在就追加」——把 `prompts/b50_block.txt` 改名为 `.bak` 再跑一次 `deploy_miruku.py`，persona 从 4643 回到 **3320 字符**。注意脚本注释里写的 `--off` **并未实现**（`sys.argv` 只处理 `--probe` / `--probe-crisis`），别信注释。

**移除后的四问怎么答**（终验清单，Codex 运行态复核用）：
- 「你 b50 最高是哪首」→ 总述条目（`wo-de-b50`）必中；
- 「KING 多少分」→ `b50-*` 逐曲条目必中且数字 = 280；
- 「ロキ多少分」→ 背景 + 兜底护栏，且**不含**数字；
- 「QUEEN 多少分」→ 逐曲条目（F1 已修，现在是 MASTER 12.8 / SSS / R277）。

**`12/12`、`120/120` 怎么复跑**：前者指 `data/probe_inject_hook.py`（12 例，含护栏与幂等）；后者指 `data/probe_regression.py`（120 条检索回归）。两条都不依赖 b50_block，移除后已原样通过。

---

## 五、证据等级

| 结论 | 等级 |
| --- | --- |
| 插件与仓库源码一致、已加载、配置正确 | 已验证（sha256 + 加载日志 + 配置） |
| 会话边界、敏感过滤、幂等、库异常 fail-closed | 已验证（探针可复跑） |
| F1 三首漏注入（已修）、F2 覆盖 47/50（已解除）、F5 路径错位 | 已验证（可复跑） |
| F4 的**触发路径** | 推测（异常类型已验证） |
| 端到端（真实 QQ 消息 → 模型确实用上块） | **运行态未能验证**：探针只到 `req.system_prompt`；AstrBot 侧的顺序已读源码确认（`internal.py:307` 在 `reset_coro` 之前，`astr_main_agent.py:2004/2043` + `tool_loop_agent_runner.py:324-327` 表明 reset 时才把 `system_prompt` 拼成 messages），但**没有一条真实出站能证明模型读了它**。C-16 接上后可用 `[Miruku knowledge]` 日志 + 一次真实问答终验。 |

---

## 六、测试盲区

- 只测到「`req.system_prompt` 被改写」这一层，不测模型是否真的采信。
- 不测并发：两个请求同时首调 `_load_builder` 会各加载一次模块（幂等，但未压测）。
- 不测真实 QQ 分段/重试路径下的重复注入（C-16 的 regenerate 若新建 `ProviderRequest`，会重新注入一次，行为正确但未实测）。
- 不测 `event.message_str` 带引用前缀（引用回复）时的检索偏移。
- 子进程场景用临时目录，不覆盖「真实库正在被 `build_knowledge_db.py` 原子替换」的瞬时窗口（已知 fail-closed，未实测）。

---

## 七、修复状态（原「给 Codex 的最小修复清单」）

**F1–F7 全部已修（2026-10-24，OTTO 授权，Codex 无额度期间由 DeepSeek 自行完成）。** 剩下 F8 是已排除项、F9 是设计盲区（不属 L1 部署 bug）。

| 项 | 状态 | 改动位置 |
| --- | --- | --- |
| F1 三首 b50 曲子漏注入 | ✅ 已修 | `knowledge/query.py` 新增 `loose_query()` + 别名兜底分支 |
| F2 `b50_block.txt` 阻断移除 | ✅ 已解除 | 文件改名 `.bak` + 重部署，persona 4643→3320 |
| F3 静默跳过 | ✅ 已修 | `main.py` `_bump()` 六项计数 + 首次 INFO |
| F4 `SystemExit` 逃逸 | ✅ 已修 | `query.py` `load_entries` 改抛 `RuntimeError` |
| F5 校验 A 路径读 B 路径 | ✅ 已修 | `main.py` 显式传 `db_path` |
| F6 空 root 退化 CWD | ✅ 已修 | `main.py` 空串直接 `FileNotFoundError` |
| F7 损坏库漏句柄 | ✅ 已修 | `query.py` `try/finally` 关连接 |
| F9 `SCORE_GUARD` 只在有块时生效 | ⬜ 不修（2026-10-24 实测后决定，理由见第三节 F9 末尾） | — |

**F9 为什么没顺手做**：它要改的是「没命中任何条目时也注入一行护栏」，属于行为变更而不是 bug 修复——一旦对「完全无关的闲聊」也塞护栏，等于每轮都多一段提示，风险大于收益。建议先看运行期真实数据再决定。

**验证（全部已跑）**：
- `data/probe_knowledge_adversarial.py` → **28 条用例 + 4 项专项，通过 32 / 失败 0，EXIT 0**（新增 3 条宽松兜底的负对照：`真的假的` / `学校的猫` / `监狱里那个`）
- `data/probe_knowledge_plugin.py` → 8/8，EXIT 0
- `data/probe_inject_hook.py` → 12/12，EXIT 0
- `data/probe_regression.py` → 120/120，EXIT 0
- `knowledge/lint.py --strict` → 548 条，严重 0 / 提示 21，EXIT 0
- 仓库与实例插件 sha256 **一致**（`af9aae0d…`）

**热重载（2026-10-24 10:2x，已做）**：实例副本原为旧版（`e2f23603…`），先备份再覆盖为仓库版，然后 `POST /plugins/reload`（body `{"plugin_id": "astrbot_plugin_miruku_knowledge"}`；`{"name": ...}` 会 422）。日志 `09:59:41.212 Terminating` → `Removed handler add_knowledge … (96)` → `09:59:41.431 Loading` → `09:59:41.470 Plugin … (0.1.0) by OTTO`；`GET /plugins` 回读 `activated: true`（注意该接口返回 **list** 不是 dict）。

**仍未验证的一环**：钩子是否真的被触发。日志里还没有 `[Miruku knowledge] armed: platform=miruku` 那行——它只在**第一条命中的真实私聊**上打一次。这是 C-15 终验的最后一步，需要一条真实消息（OTTO 的测试号即可），审计侧不代发。

---

## 八、变更记录

- 2026-10-24：首次审计。探针 25 条用例 + 4 项专项；发现 F1–F9；`b50_block.txt` 覆盖 47/50；默认退出码 1（3 条已登记）。
- 2026-10-24（同日，OTTO 直接授权）：**修 F1 + 解除 F2**。
  - `knowledge/query.py` 新增 `loose_query()`（保留单字停用词、只摘「多少分 / 什么评级 / 多少r」）与 `add(hay=)`、别名兜底分支（≥3 字且 clean 后仍 ≥3 字）。
  - 三条 b50 曲子转正；覆盖 47/50 → **50/50**；全量审计 389 → **391 条（4.51%）**，净增 2 条均属真命中。
  - `prompts/b50_block.txt` → `.bak`，重部署后 persona **4643 → 3320 字符**。
  - 回归：`probe_regression` 120/120、`probe_inject_hook` 12/12、`probe_knowledge_adversarial` 29/29（`KNOWN_BUGS` 清空，默认退 0）、`lint` 严重 0/提示 21。负例复查：`真的假的`、`学校的猫`、`监狱里那个`、`什么意思`、`有格调`、`忙了一天` 全部仍 EMPTY。
  - 未动：`clean_query`、`min_score=10.0`、persona/tone_profile。
- 2026-10-24（同日，Codex 无额度，OTTO 授权 DeepSeek 自行修）：**F3–F7 全部修完**。
  - `plugins/astrbot_plugin_miruku_knowledge/main.py`：`_bump()` 六项计数、首次 INFO「armed」、空 root 直接报错、显式传 `db_path`；已同步到实例（sha256 一致 `af9aae0d…`）。
  - `knowledge/query.py`：`load_entries` 改抛 `RuntimeError`；连接改 `try/finally` 关闭。
  - 探针：F4 从「记录不判红」改成断言（抛 `SystemExit` 即红）；新增 3 条宽松兜底负对照。28 条用例 + 4 项专项 → **通过 32 / 失败 0**。
  - 其余三个探针与 lint 全部 EXIT 0；120/120 不退化。
- 2026-10-24 10:2x（同日）：**实例热重载完成**。实例副本从旧版 `e2f23603…` 覆盖为仓库版 `af9aae0d…`（覆盖前已备份），`POST /plugins/reload` 生效，日志四行确认（Terminating → Removed handler → Loading → 0.1.0 by OTTO），`GET /plugins` 回读 `activated: true`。**F3–F7 现在真的在跑，不再是「改了没加载」**。仍未验证：`armed` 日志需要一条真实命中消息才会出现。
- 2026-10-24 10:2x（同日）：**全库规模数字同步**。`docs/knowledge.md`（11→12 主题、494→548 条、1.8→1.9 MB、digest 43→48 KB）、`docs/knowledge-regression.md`（库行加注 DS-02 时点说明、lint 548 条、全量审计补 391 条 4.51% 复跑行、confidence high 498/medium 48/low 2）、`docs/collaboration-roles.md`（493→548）、`WORK_LOG.md` 当前状态段。
