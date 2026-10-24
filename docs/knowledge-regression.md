# 知识检索回归（DS-02，2026-10-21 至 10-22）

**任务单**：`docs/assignments-20261021.md` DS-02
**解释器**：`C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\venv\Scripts\python.exe`（Python 3.12.15，AstrBot Launcher 实例环境，**不用系统 Python 3.9**）
**库**：`knowledge/miruku_knowledge.sqlite3`，12 主题 560 条（本文件写于 DS-02 时点为 11 主题 494 条；b50 主题 52 条于 2026-10-22 晚合入，2026-10-24 又补 games/touhou/vocaloid 等与「退勤」「彩框」等条目，增至 560）
**用例**：`data/regression_cases.json`（v4，120 条：正例 27 / 正例·排名边界 34 / 负例 50 / 敏感 9）
**用例生成器**：`data/build_regression_cases.py`（`json.dump` 生成，不手拼字符串）
**探针**：`data/probe_regression.py`（自动断言，退出码 0/1/2）
**断言自检**：`data/check_probe_asserts.py`（故意破坏三种情况，验证真的会非零退出）
**全量审计**：`data/inject_audit.py`（跑真实语料，`--dump` 写 `data/inject_audit.txt`）

复跑：

```bat
set PYTHONIOENCODING=utf-8
"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\venv\Scripts\python.exe" data\probe_regression.py
"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\venv\Scripts\python.exe" knowledge\lint.py
"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\venv\Scripts\python.exe" data\check_probe_asserts.py
```

> `PYTHONIOENCODING=utf-8` 不能省。Windows 控制台默认 cp936，中文输出会乱码。

`inject.build_block` 阈值 `min_score=10.0` **全程未下调**（任务单硬约束）。所有降噪都做在评分侧，没有靠抬阈值。

---

## 一、结论

| 组别 | 用例 | 通过 | 说明 |
| --- | --- | --- | --- |
| 正例 | 27 | 27 | 期望条目命中，默认要求第一名 |
| 正例·排名边界 | 34 | 34 | 指定 slug 的要求第一名；只指定主题的允许前 3 名 |
| 负例 | 50 | 50 | `build_block` 返回空串 |
| 敏感条目不得注入 | 9 | 9 | 空串，且附加 `not_slug` 断言 |
| **合计** | **120** | **120** | **退出码 0** |

> 本文主体写于 DS-02 交付时（93 条）。DS-03 又加了 27 条：8 条弱词正例 + 6 条弱词负例 +
> 3 条「天爆」动作词正例 + 3 条「大红/爆率」与「你在干什么」正例 +
> 4 条「别名 clean 命中」正例（`你打舞萌吗` 等）+ 3 条同类负例（`什么意思` 等），现为 120 条。
> 弱词规则与新增条目的来龙去脉见 `docs/knowledge-residual-audit.md` 第五、七、十四、十五节。

`knowledge/lint.py`：扫描 560 条（2026-10-24 复跑），**严重 0 处**，提示 21 处（全是 `detail`/`source` 里的路径与数字，不进 prompt）。

全量真实语料审计：**8,663 条私聊命中 252 条 = 2.91%**。DS-02 开始时是 325 条 3.75%。
> 2026-10-24 复跑：**391 条 = 4.51%**。增量主要来自 `self/平时做什么` 的别名扩容（「在干嘛呢」一族 184 次真实问候，改前全不命中）与 F1 的宽松兜底修复（`QUEEN 多少分` 等 3 首），均为真命中；逐条复核见 `docs/ds06-knowledge-injection-audit.md`。
**这个口径含测试号会话，不要对外引用**——真实会话是 232/8,581 = 2.70%，见 `docs/knowledge-residual-audit.md` 第二节。

### 关于「全部命中正确条目且排第一」——上一版这句话是不实的

DS-01 文档第 23 行写「应命中 28 / 28，全部命中正确条目且排第一」。实际当时就有反例：**「小男娘音怎么练」的第一名是「小男娘」（60.48），该答的「男娘音」只有 38.08 排第二**。这句话已删除。

现在这条用例的实测是：

| 输入 | 第一名 | 第二名 |
| --- | --- | --- |
| 小男娘音怎么练 | 男娘音 (vrchat, 19.4) | 小男娘 (vrchat, 19.3) |

19.4 与 19.3 只差 0.1，属于**并列**，不是稳定领先。原因是这两个词在这句话里都只有一次出现机会（`_pick_non_overlapping` 生效后），靠中文中心词后置的 0.5 分平局规则把「男娘音」抬到前面。用例只断言「男娘音排第一」，是因为它确实是这句话想问的东西；如果将来某次改动让它掉到第二，而「小男娘」顶上来，语义仍然成立（两条都在注入块里，见第二节）。**这条用例的价值是防止它俩被别的条目挤下去，不是保证这 0.1 的稳定。**

### 知识库用例通过 ≠ 模型回复质量通过

必须写清楚：93/93 只证明**检索层**在这批输入上给出了期望的条目、没有泄漏、没有超长。它不证明：

- 模型拿到知识后会自然使用（可能逐条复述，可能完全不提）；
- 模型的回复口吻像 Miruku（那是 `prompts/system.txt` 与 `persona/` 的职责，本任务未改）；
- 知识本身正确（第 6 节列了 49 条单源或中等可信条目）；
- 真实 QQ 会话里的效果（本轮未部署、未向 QQ 发消息）。

---

## 二、修掉的问题（按严重度）

### 1. `SEP` 分隔符：同时问两个词反而一个都不注入（严重）

`clean_query()` 原来删掉停用词后把两侧**直接粘起来**：

```
7ref 和 KALEIDXSCOPE 有关系吗  →  「7refkaleidxscope」
```

于是「7ref」右侧紧贴 `k`、「kaleidxscope」左侧紧贴 `f`，两边都过不了 ASCII 词边界检查，**整条查询返回空**。而这两个名字恰恰是 KALEIDXSCOPE 解谜里最常一起被问到的。

**修法**（`knowledge/query.py:184`）：用 `SEP = "\u0001"` 顶替被删掉的位置。它既不是 ASCII 字母数字（词边界因此成立），也不属于任何标题/别名（不会误命中）。

```python
SEP = "\u0001"

def clean_query(q: str) -> str:
    text = normalize(q)
    for phrase in STOP_PHRASES:
        text = text.replace(phrase, SEP)
    while SEP + SEP in text:
        text = text.replace(SEP + SEP, SEP)
    text = text.strip(SEP)          # 两端不能残留
    if not text:
        return ""
    return text if len(text) >= 2 else normalize(q)
```

三个容易踩的点：

- `strip(SEP)` 必须有。两端残留会让「整句就等于这个别名」的判断全部失效（「你喜欢什么」→「喜欢」就走不通了）。
- 新增 `qlen = len(qn.replace(SEP, ""))`，**所有长度比（覆盖率、中心词平局）必须用 `qlen`**，不能用 `len(qn)`。否则「墓守\x01歌\x01样」算 6 字，覆盖率从 2/4 掉到 2/6，真话题反而不注入。
- `short = qlen < 2` 同理。

### 2. 别名整段命中给满分（严重，与上一条配套）

```python
if an in qn.split(SEP):
    value = 14.0
else:
    value = 14 * max(0.7, len(an) / qlen)
```

理由：`clean_query` 用 `SEP` 隔开后，「整段等于别名」比「出现在查询里」更精确，它排除了「别名只是长句里的一截」。没有这条，`7ref 和 KALEIDXSCOPE 有关系吗` 两个词各只得 9.8 分，双双卡在 10.0 下面。

修复后：`7sRef` 14.0 + `KALEIDXSCOPE（万花筒）` 14.0，两条都注入。

### 3. 整句等于 3 字以上 tag 给独立证据（中）

回归用例「英雄联盟」期望注入，但库里**没有「英雄联盟」条目**，只有 `dou-hun-jing-ji-chang`（斗魂竞技场）和 `hai-ke-si-da-luan-dou`（海克斯大乱斗），两者 `tags` 都是「英雄联盟」。它只能靠 n-gram 命中 tags，被 `NGRAM_ONLY_CAP` 封到 7.0 后变空。

**修法**（`knowledge/query.py:567` 附近）：

```python
tag_names = {normalize(t) for t in entry["tags"]}
if len(q_raw) >= 3 and q_raw in tag_names:
    bonuses.append((8.0, 0, len(qn)))
    strong_hit = True
```

门槛取 3 字是有依据的：2 字 tag（「街霸」「关系」「评价」）在真实语料里是日常词；全量 8,663 条私聊里，整句等于 3 字以上 tag 的只有「三角洲」两条，都是真命中。

修复后「英雄联盟」→ 斗魂竞技场 25.6 + 海克斯大乱斗 25.6。

### 4. `NGRAM_ONLY_CAP`：纯字面相似不能单独触发注入（中）

全量审计剩下 3 条**纯 n-gram** 误命中：

```
那我平时也不玩了  →《平时做什么》11.0（gram「平时」撞标题+别名+summary）
会了就容易了      →《夜に駆ける（容易混淆）》10.0（gram「容易」）
我也是这么说      →《说话方式》11.0（gram「么说」撞别名「你怎么说话」）
```

**修法**：`NGRAM_ONLY_CAP = 7.0`（低于阈值），在**所有乘数之后**封顶。

第一次写成 `total = min(total, NGRAM_ONLY_CAP)` 放在 `total += bonus_total` 紧后面，结果「在干嘛」→《平时做什么》先被封到 7.0、再乘 `TOPIC_BOOST["self"]=2.2` 变成 11.0，照样注入。所以改成先记 `ngram_only` 标记，等 `TOPIC_BOOST`/`TOPIC_HINT_BOOST` 都乘完再封。`GENERIC_CAP` 同理。

### 5. `clean_query()` 删空后回落原文（中）

原来整句都是疑问词时回落到 `normalize(q)`，于是「为什么？」（3 字）被当检索词，命中《春日影 / 为什么要演奏春日影》**12.0**——对方只是在问为什么。

**修法**：`if not text: return ""`，`score()` 拿空 grams 直接返回 0.0。

### 6. 「查询只是标题的一截」分支缺覆盖率门槛（中）

原来固定给 8.0，加上 n-gram 就过阈值。现在 `cover = qlen / len(title_n)`，`cover >= 0.5` 才给 8.0。修掉：

| 输入 | 修复前 | 修复后 |
| --- | --- | --- |
| 没关系的 | 《和 OTTO 的关系》14.0 | 空 |
| 没体力了 | 《谱面属性（物量·技巧·体力）》16.0 | 空 |
| 会了就容易了 | 《夜に駆ける（容易混淆）》10.0 | 空 |

**已知副作用**：「没体力了」「会了就容易了」现在是空。这两句在真实聊天里都是日常义，这个取舍是对的。

### 7. 占位符白名单补 18 个标签 + 兜底正则（中）

`[闪照]请使用新版手机QQ查看闪照。` 在语料里出现 8 次，**全部**命中《QuiQ》（靠别名 `qq`）。新增：

```python
PLACEHOLDER_ASCII = re.compile(r"\[[^\]\u4e00-\u9fff]*\]")
```

摘掉任何方括号内无汉字的令牌（`[CQ:image,file=xxx]`、`[abc.jpg]`、`[123456]`）。`_normalize_cached` 里先跑两个 `PLACEHOLDER` 再 `PUNCT.sub`。

### 8. 日常词门禁从「只挡别名」扩到「也挡 n-gram」（中）

原来只挡别名路径，同一个日常词换条路照样进来：「怎么操作都不知道」靠 tags 里的「操作」拿 **16.0**、「没关系的」靠标题里的「关系」拿 14.0。

```python
generic_gram_ok = _generic_alias_ok(q_raw)
if not generic_gram_ok and gram in GENERIC_ALIASES:
    continue
```

判断 gram 是否**等于**日常词（不是包含），避免误伤「出勤迟到」。

### 9. 别名覆盖率下限 0.7 无条件给（中，一次改错又改回）

中途试过「覆盖不足 1/3 就不给下限」，结果「闲鱼买模型靠谱吗」（闲鱼覆盖 2/7）和「今天忙一天了，晚上想打舞萌」（舞萌覆盖 2/11）被压到阈值下，**真话题反而不注入**。

结论：下限 0.7 **必须无条件给**。低覆盖的日常词由 `GENERIC_ALIASES` 挡，不靠折扣。代码里留了注释防止再改错。

### 10. 两字符纯 ASCII 别名与 gram 只认整句（中）

```python
if an.isascii() and len(an) < 3 and qn != an:
    continue
```

修掉：`上VR？`→《VirtuaReal》10.13、`白xx要上了`→《Xaleid◆scopiX》10.63（别名 `xx`）、`ap狗头`→《AP / FC》10.83。

### 11. 标题「A / B」分段分支补门禁（中）

原代码 `if len(pn) >= 2 and pn in qn: add(10.0, pn)`，两个门禁都没有 → 「ap狗头」「还有ap小炮」→《AP / FC》10.0（AP 是英雄联盟的 AP 出装）。现在 `len(pn) < 2` 跳过、2 字符 ASCII 且非整句跳过、日常词且无语境词跳过，最后用 `_contains`（带词边界）代替 `in`。

### 12. 整句就是日常词（中）

「我也喜欢你」`clean_query` 后只剩「喜欢」，靠《喜欢什么》的标题拿 8.0，再乘 `TOPIC_BOOST["self"]=2.2` = **17.6** 直接注入。

```python
if qn in GENERIC_ALIASES and not _generic_alias_ok(q_raw):
    raw_names = {normalize(entry["title"])}
    raw_names.update(normalize(a) for a in entry["aliases"])
    if q_raw not in raw_names:
        return 0.0
```

例外是必须的：`q_raw` 整句等于该条自己的标题/别名时照常算（「你喜欢什么」clean 后也是「喜欢」，但它本来就是别名）。修复后「我也喜欢你」「我不喜欢这样」「没关系的」「你不说话」→ 空；「你喜欢什么」→17.6、「你什么性格」→74.8、「说话方式」→25.83 正常。

### 13. `_pick_non_overlapping`：同一段文字只计一次分（重要）

起因：「小男娘音怎么练」里「小男娘」条目的 title、别名「小男娘」、别名「男娘」三段**全落在同一段文字上**，叠了三次分（60.48），把该答的「男娘音」（38.08）压到第二。

**修法**：按分值从高到低贪心取、区间不重叠的才累加。真正分开提到的两个词（「方舟」和「源石」）仍然各自计分。

### 14. 其它

| 问题 | 修法 | 效果 |
| --- | --- | --- |
| `normalize` 没清装饰符号，`Xaleid◆scopiX` 的 `◆` 让标题永远匹配不上 | 新增 `NON_WORD` 正则 | 「Xaleid scopiX」可检索 |
| 标题单字（`[X]`、`行`）走包含分支 | `len(title_n) >= 2` 门槛 | 「行」→ 空（原来同时命中三角洲行动/砂之行星/西行寺幽幽子） |
| 纯数字查询（`13`、`88`）命中数字别名 | `qn.isdigit() and len(qn) <= 3` → 0.0 | 全空；带文字的「300井」「88boy」「135秒」不受影响 |
| 标题命中 10.0 低于别名上限 14.0 | 提到 **15.0** | 「小男娘」不再靠主题加权压过真正的标题 |
| 2 字 n-gram（`lo`/`ol`）钻进英文词 | gram 也守词边界 | `我在lol`→ 空（原来 hololive 20.0 + hololive English 24.0） |
| `normalize` 每次重算，全语料跑不完（>8 分钟被迫 kill） | `@lru_cache(maxsize=8192)` | 50 轮 × 486 条 = 0.39s |

---

## 三、`GENERIC_ALIASES`：约 52 个日常高频词

一个日常词**永远不该单靠自己触发注入**，它只能帮已在话题内的条目排序。所以：

- 命中日常词别名 → 要求查询里同时有语境词（`CONTEXT_WORDS` = 音乐 + 游戏 + VRChat 三组）；
- 即使有语境词陪着，该别名**也封顶 7.0**（`GENERIC_CAP`，低于 10.0）。

每个词都有真实语料证据（`data/chat_content.sqlite3`，26,661 条纯文本），且逐条看过上下文确认以日常义为主：

| 词 | 频次 | 典型误命中 |
| --- | --- | --- |
| 老师 | 54 | 老师这关怎么打 |
| 一天 | 47 | 看你忙一天了 |
| 衣服 | 39 | 刚去洗衣服了 →《洗衣机》13.13 +《衣服材质贴图》11.58 |
| 学校 | 33 | 学校对面的那家店 →《Panopticon》 |
| 早八 | 20 | 明天早八 |
| 监狱 | 16 | 监狱里的人都这样 →《Panopticon》20.0 |
| 起床 | 13 | 准备起床 →《ずんだもんの朝食》10.47 |
| 操作 | 12 | 怎么操作都不知道 →《现代操作与经典操作》24.0 |
| 米饭 | 4 | 米饭免费续 →《ATLAS RUSH》10.91 |
| 距离 | 2 | 口吻距离 miruku 还是相差甚远 →《装备牌》10.0 |

第二批（游戏/系统通用词）：操作、角色、主线、活动、体力、排位、单挑、警察、同步、消失、手游、喝酒、新手、上头、急了、最强、打架、无限、推特、空格、武器、防具、坐骑。

第三批（第三轮审计新增）：关系、说话、最后、逆天、热死了、呼吸、排球、双子、猫猫、井盖、大哥、93、qq、能力、长相、喜欢、热死、彩虹、下落、四块钱、断网、联机、阴间、无名、啤酒、等级、赌场、挂机、bug。

**不删别名**：「忙日」「龙之日」不是自然汉语短语，只可能是曲名俗称，查询它们仍然可用。

---

## 四、回归表

### 正例（27/27）

| 输入 | 期望 | 实际（分数） |
| --- | --- | --- |
| 你是谁 | 我是谁 | 我是谁 (self, 46.2) |
| ACID是谁啊 | ACID（解谜角色） | ACID（解谜角色）(maimai, 15.33) |
| 7ref是啥 | 7sRef | 7sRef (maimai, 14.0) |
| 7sRef到底是个什么世界 | 7sRef | 7sRef (15.9) |
| KALEIDXSCOPE怎么开 | KALEIDXSCOPE | KALEIDXSCOPE（万花筒）(14.0) |
| 我昨天打到第七道门了 | 第七道门与蓝屏 | 第七道门与蓝屏（Phase #???）(13.86) |
| Xaleid scopiX好难 | Xaleid◆scopiX | Xaleid◆scopiX (15.43) |
| 夏玛是谁 | 夏玛 | 夏玛 (self, 20.67) / しゃま（夏玛）(maimai, 19.0) |
| 何意味 | 何意味 | 何意味 (memes, 36.0) |
| 鸟加那个谱面好难 | 鸟加 | 鸟加 (16.5) |
| 墓守这歌怎么样 | 躯樹の墓守 | 躯樹の墓守 (16.0) |
| 万花筒解谜到哪了 | KALEIDXSCOPE | KALEIDXSCOPE（万花筒）(12.87) / Xaleid◆scopiX (10.8) |
| 洗衣机出勤 | 为什么叫"洗衣机" | 为什么叫"洗衣机" (30.93) / 机台与基础玩法 (27.2) / 出勤·pc·拼机 (25.07) |
| 300井是什么 | 300 井 / 吃井 | 300 井 / 吃井 (arknights, 13.67) |
| 初音未来的歌你听过吗 | 初音未来 | 初音未来 (30.13) |
| 少女乐队最近在听什么 | 少女乐队 | 少女乐队 (anime, 20.35) |
| 方舟源石怎么攒 | 源石 | 源石 (27.48) / 明日方舟 (24.36) |
| 三国杀OL还有人玩吗 | 三国杀 | 三国杀 (27.5) |
| 街霸6杰米怎么玩 | 街霸6 | 街霸6 (29.2) / 杰米 (28.67) |
| 三角洲跑刀怎么打 | 三角洲行动 | 三角洲行动 (28.4) / 跑刀 (26.67) |
| 英雄联盟海斗 | 海克斯大乱斗 | 海克斯大乱斗 (29.6) |
| VRChat改模要多久 | 改模 | 改模 (25.44) / VRChat 是什么 (22.8) |
| 小男娘是啥意思 | 小男娘 | 小男娘 (18.25) |
| 闲鱼买模型靠谱吗 | 闲鱼买模型和预制件的坑 | 闲鱼买模型和预制件的坑 (14.47) / avatar 模型 (10.6) |
| hololive最近有什么事 | hololive | hololive (24.89) |
| 东方幻想乡有什么好玩的 | 幻想乡 | 幻想乡 (28.94) / 东方Project是什么 (23.68) |
| 术力口最近有什么新曲 | 术力口 / ボカロ 这个叫法 | 术力口 / ボカロ 这个叫法 (27.52) / 翻唱·术力口·原创曲 (12.4) |

### 正例·排名边界（16/16）

只指定主题的用例允许前 3 名，因为知识库里同一主题下有多条都该被提到（「街霸和三角洲哪个难」两条都答是对的）。

| 输入 | 断言 | 实际 |
| --- | --- | --- |
| 小男娘音怎么练 | nanniang-yin 第一 | 男娘音 (19.4) / 小男娘 (19.3) |
| 男娘音 | nanniang-yin 第一 | 男娘音 (32.0) / 小男娘 (13.8) |
| 英雄联盟 | games 前 3 | 斗魂竞技场 (25.6) / 海克斯大乱斗 (25.6) |
| 街霸和三角洲哪个难 | games 前 3 | 三角洲行动 (27.2) / 街霸6 (23.89) |
| 粥 | zhou 第一 | 粥 (arknights, 32.0) |
| 鸟 | niao 第一 | 鸟 (maimai, 20.0) |
| 今天忙一天了，晚上想打舞萌 | maimai 前 3，**不得含 busy-day** | 机台与基础玩法 (16.98) / 高松灯打舞萌 (11.58) |
| 7ref 和 KALEIDXSCOPE 有关系吗 | maimai 前 3 | 7sRef (14.0) / KALEIDXSCOPE（万花筒）(14.0) |
| `[图片:abc.jpg]` 墓守这歌好听吗 | qu-shu-mu-shou 第一 | 躯樹の墓守 (15.33) |
| 我今天出勤了，打了一下午墓守 | chu-qin-pc 第一 | 出勤·pc·拼机 (23.73) / 机厅与社群文化 (23.2) / 躯樹の墓守 (16.75) |
| 衣服买好了，明天出勤穿 | chu-qin-pc 第一，**不得含 yifu-caizhi** | 出勤·pc·拼机 (23.54) / 机厅与社群文化 (23.09) |
| 起床了，等会打舞萌 | maimai 前 3 | 机台与基础玩法 (25.33) / 高松灯打舞萌 (18.0) |
| 这个操作在街霸里叫啥 | jie-ba-6 第一，**不得含现代操作** | 街霸6 (23.89) |
| 你是AI吗 | ai-shen-fen 第一 | 我是 AI (self, 52.8) |
| 英雄联盟和三国杀哪个好玩 | sanguosha 前 3 | 三国杀 (27.04) |
| 夏玛和 shama 是一个人吗 | self 前 3 | しゃま (29.9) / 夏玛 (29.87) |

「今天忙一天了，晚上想打舞萌」这条最值得看：它同时有「忙一天」（曲目别名）和「舞萌」（语境词），门禁会放行，全靠 `GENERIC_CAP` 把「忙一天」封在 7.0 才没注入一首歌。

### 负例（41/41，全部为空）

日常寒暄 10：今天天气不错、早上好、我去睡了、在干嘛、吃了吗、好的、嗯、哈哈哈哈、那我先忙了、晚点再说
占位符 2：`[图片:0392a1b4c7.jpg]`、`[表情:abc123]`
日常 17：你吃饭了吗、外面下雨了、我有点困、这个怎么弄、随便聊聊、我回来了、笑死、这件衣服挺好看、我起床了、这个操作有点难、你玩什么游戏、我和朋友去吃饭了、今天下雨了，衣服还没收、他住在学校旁边、这个软件挺好用、明天早八、他好像有点急
其它 12：`[图片:abc] 这歌好听吗`、学校对面的那家店（not_slug panopticon）、看你忙一天了（not_slug busy-day）、监狱里的人都这样、lol、13、88、行、我手机快没电了，等会再说、我今天打了一整天、我在楼下等你、你昨天几点睡的

占位符那几条是重点：`PLACEHOLDER` 正则把 `[图片:...]` 整段清掉，占位符里的十六进制串不会变成检索词（此前「39」会命中初音未来别名）。`[图片:abc] 这歌好听吗` 更严：清掉占位符后只剩「这歌好听吗」，仍要求为空——因为「这歌」不是任何条目的名字。

### 敏感条目不得注入（9/9，全部为空）

开盒是什么意思、炎上是怎么起来的、卫批这个词、雌小鬼是啥、女装去漫展、A-SOUL现在怎么样了、VShojo解散了吗、你叫什么名字、你家住哪。

`search(..., include_sensitive=False)` 在**评分前**过滤掉 `sensitive=true` 的 7 条：`arknights/wei-pi`、`memes/ci-xiao-gui`、`memes/nv-zhuang`、`vtuber/vshojo`、`vtuber/a-soul`、`vtuber/kai-he`、`vtuber/yan-shang`。**这是过滤，不是降权**，即使查询完全等于标题也不会注入。

---

## 五、自动断言是怎么做的

`data/probe_regression.py` 的退出码：**0** 全过 / **1** 有用例失败或 lint 严重项 / **2** 环境问题（库或用例文件缺失、JSON 坏）。

断言内容：

1. **期望条目**：`expect=hit` 时按 `rank`（默认 1）查名次，给了 `max_rank` 则只要求不差于该名次；`expect=miss` 要求 `build_block` 返回**空字符串**。
2. **`not_slug`**：命中的候选里不得出现指定条目（要求「命中且 block 非空」才判失败，避免空 block 时误报通过）。
3. **隐私词**：`LEAK_PATTERNS` 9 条正则——Windows/Unix 绝对路径、`Desktop|.astrbot_launcher`、`.py|.sqlite3|.json`、`api_key|jwt|secret|token`、6–12 位长数字（疑似 QQ 号）、`prompts/|persona/|个性化语言`、`部署|提示词|知识库文件`。
4. **长度上限**：`MAX_CHARS = 600`。
5. **lint 严重项**：`lint_severe()` 直接复用 `lint_mod.SRC.glob("*.json")` + `lint_mod.INJECTED` + `lint_mod.scan_text`，**不调用 `lint.main()`**——因为它默认退出码 0，只有 `--strict` 才返 1，直接调用会把严重项吞掉。

参数：`-v/--verbose`（逐条打印）、`--json`（机器可读）、`--cases`（换用例文件）、`--no-lint`。

### 故意破坏的验证（Codex 验收要求）

`data/check_probe_asserts.py` 自动跑四种情况：

```
[基线] 不改任何东西            -> 退出码 0  OK
[破坏一] 负例改成 expect=hit    -> 退出码 1  OK
[破坏二] lint 报一个严重项      -> 退出码 1  OK
[破坏三] 期望名次从 1 改成 3     -> 退出码 1  OK
```

「破坏二」的具体做法是把 `knowledge/src/games.json` 第一条 summary 临时改成 `见 prompts/system.txt 里的部署说明`，探针仍 93/93 通过但会打印：

```
lint 严重项 2 处（注入路径不干净）
[games/jie-ba-6] summary 里出现项目内部提示词路径：prompts/system.txt
[games/jie-ba-6] summary 里出现系统实现词：部署
```

> 注意：bash 里 `cmd | tail` 之后 `$?` 是 `tail` 的退出码。要看真实退出码必须 `cmd >/dev/null 2>&1; echo $?`。这个坑我踩过一次，差点误判成「断言没生效」。

---

## 六、全量真实语料审计

`data/inject_audit.py`：从 `data/chat_content.sqlite3` 的 `v_text_messages` 取 `direction='peer' AND length(text) BETWEEN 4 AND 60`，共 **8,663 条**真实私聊，逐条跑 `inject.build_block`。

| 阶段 | 命中 | 比例 |
| --- | --- | --- |
| DS-01 抽样（3,000 条） | 215 | 7.17% |
| DS-02 起点（全量） | 325 | 3.75% |
| 修完覆盖率与 ASCII 别名 | 282 | 3.26% |
| 扩 `GENERIC_ALIASES` + 收紧语境词 | 258 | 2.98% |
| 标题分段门禁 + 整句日常词门禁 | 248 | 2.86% |
| `NGRAM_ONLY_CAP` | 245 | 2.83% |
| 最终（加 tags/SEP/整段别名后 +4 条真命中） | **249** | **2.87%** |
| DS-03 修订（弱词 + 大红/爆率条目 + 别名 clean 命中） | **252** | **2.91%** |

最后 +4 条全部是真命中：`7ref 是哪儿的`→7sRef、`之前弄得vrcfacetracking不是在Steam下的`→面部追踪 15.75、`QZKago 那首一上来就压得人喘不过气`→QZKago Requiem 14.01、`oshama 是啥`→Oshama Scramble! 14.0。

DS-03 修订后从 249 涨到 252，涨的同样是真命中：新增的 `games/da-hong-bao-lv`（大红/爆率）在语料里正确命中，另有几条 self 人话问句（`你打舞萌吗`、`你什么段位`）从「错条目」变成「对条目」。**命中数上涨不等于退化**，判定要看 `data/residual_audit.tsv` 的逐条分类。

清单在 `data/inject_audit.txt`（DS-02 版 249 条，行首留了 `[ ]` 供人工勾选；DS-03 修订后的 252 条请用 `data/residual_audit.py --dump` 重新导出）。

### 一个有用的对照实验

把 `_generic_alias_ok` 强制返回 `False`（等于关掉所有语境门禁），282 条里只有 **1 条**消失。说明语境门禁对召回几乎无影响，因此可以放心继续收紧。

### 曾经判「已知、不修」的残余误命中（DS-03 已全部修掉）

> **本表是 DS-02 交付时的状态，保留作历史记录。** DS-03 之后这 7 条全部有了结论：
> 前 4 条误命中已修（`WEAK_ALIASES`），「今天爆率高会摸回来的」不是误命中而是缺知识
> （已补「大红/爆率」条目），「手套」「社恐」判为可接受，
> 「你在干什么」的摘要已改写。详见 `docs/knowledge-residual-audit.md` 第四、七节。

| 输入 | 命中 | 分数 | 判定 |
| --- | --- | --- | --- |
| 今天爆率高会摸回来的 | Heavenly Blast | 10.36 | **当时判误命中，实际是三角洲的爆率/大红**（DS-03 已补条目） |
| 好像能旋转 | 旋转与"皿" | 11.13 | 误命中。DS-03 已修成空 |
| 光是看外貌和性格也能看出来 | 性格 | 15.98 | 误命中（「性格」是 self 条目，日常词）。DS-03 已修成空 |
| 你看没看过超时空辉夜姬 | 蓬莱山辉夜 | 11.8 | 误命中（在说动画，不是东方角色）。DS-03 已修成空 |
| 这手套挺好用的 | 手套 | 16.98 | **真命中**（条目讲的就是打舞萌戴手套） |
| 可能他社恐？ | 波奇 / 社恐梗 | 16.67 | 可接受（社恐确实是该条别名） |
| 你在干什么 | 平时做什么 | 43.27 | **正确**（qn 整句等于别名）。DS-03 改写了该条摘要 |

为什么当时不修——试过两种办法，都要么伤真话题、要么不可靠：

**办法一：降低 2 字别名的覆盖率下限。** 实测（floor 0.7 / 0.6 / 0.5 / 0.4）：

```
今天爆率高会摸回来的  → Heavenly Blast 10.36 / 8.96 / 7.56 / 6.16   ✓ 能压下去
好像能旋转          → 旋转与"皿"     11.13 / 9.73 / 8.33 / 6.93   ✓ 能压下去
墓守这歌怎么样        → 躯樹の墓守     11.8 / 10.4 / 9.0 / 9.0       ✗ 真话题丢失
闲鱼买模型靠谱吗      → 闲鱼买模型…    14.47 / 13.07 / 11.67 / 10.27  ✗ 0.4 才勉强保住
```

**办法二：用 jieba 分词做词边界。** Launcher 实例 Python 里 jieba 可用（0.391s 加载），但默认词典不认识圈内术语：

```
今天爆率高会摸回来的  → 今天/爆率/高摸/回来    （「高摸」切错）
你能帮我鸟加墓守吗    → 能/帮鸟/加墓守        （「鸟加」被切断）
他在打天爆          → 打天/爆              （「天爆」被切断）
```

会把真主题词切碎，未采纳。

**DS-03 的解法不一样**：不调阈值、不调下限，而是加「弱词必须独立成段」这条规则
（`WEAK_ALIASES` + `WEAK_VERB_PREFIX`），并给「今天爆率高会摸回来的」补上它真正在说的条目。
详见 `docs/knowledge-residual-audit.md` 第五节与第七节。

---

## 七、仍需人工核实的条目（50 条非 high）

560 条里 `confidence` 分布（2026-10-24 实测）：**high 503 / medium 55 / low 2**。以下按主题列出，接入运行期后如果这些条目被注入，措辞应当留余地（「好像是」「我记得」），不要当硬事实断言。
> 本节的 50 条非 high 清单写于 DS-02（494 条时点），此后新增的 `b50` 52 条全部 `high`（成绩来自查分截图，可核对），清单内容不变。

### `low`（2 条，最需要复核）

| 条目 | 主题 | 来源 |
| --- | --- | --- |
| `guo-biao`（国标） | maimai | monkeycathyd.github.io/maimai-dx-tutorial/Chapter2/5.html |
| `dian-wo`（"打舞萌会电我"） | maimai | gamerch.com/maimai/533406 |

### `medium` 48 条

**vrchat 11 条 —— 最大风险簇，整主题都是 medium**：

`vrchat-shi-shenme`、`zhuomian-vr-moshi`、`banshen-zhuizhui`、`avatar-moxing`、`gai-mo`、`moxing-shoushi`、`yifu-caizhi`、`xianyu-moxing-keng`、`oopz`、`nanniang-yin`、`guaji-shejiao`

原因：`hello.vrchat.com`、`docs.vrchat.com`、`creators.vrchat.com` 在本机网络全部连接超时，内容只能靠通行认知与二手来源。这是**知识库里唯一一个「整主题没有一手来源」**的主题，如果要提升可信度，需要 OTTO 用能连通 VRChat 官网的网络重抓一次。

**maimai 11 条**：`pai-zi`、`quan-liang`、`ji-ting-wen-hua`、`fu-wu-qi-shi-jian`、`player-level`、`hui-zhuan`、`wai-jian-nei-jian`、`jing-mian`、`huo-dong-qu`、`wu-meng-da-wang`、`lian-ji-yu-tong-bu`

**games 7 条**（整个主题都是 medium）：`hong-wen`、`san-jiao-zhou-xing-dong`、`pao-dao`、`dou-hun-jing-ji-chang`、`hai-ke-si-da-luan-dou`、`ce-shi-ju-dian`、`da-hong-bao-lv`（新增，「大红/爆率」的细节来自 OTTO 口述，属一手但未独立核实）

**sanguosha 4 条**：`pai-wei-sai`、`dan-tiao`、`shen-jiang`、`ban-ben-qu-bie`
**anime 3 条**：`ci-41-miao`、`ru-men-fan`、`zai-na-kan`
**memes 3 条**：`lao-da`、`gao-song-deng`、`ci-xiao-gui`（sensitive）
**self 3 条**：`sheng-ri-nian-ling`、`tao-yan-shen-me`、`maimai-qi-ta`
**vtuber 3 条**：`vshojo`（sensitive）、`virtuareal`、`ming-chang-mian`
**arknights 2 条**：`zhou`、`wei-pi`（sensitive）
**vocaloid 1 条**：`kaai-yuki`

### 另一个单源问题：`kaleidxscope` 系列

7 条 KALEIDXSCOPE 解谜条目给的是 `high`，但**只来自 `silentblue.remywiki.com`（英文维基）单一来源**。剧情细节（ACID 种 bug、Master Key、Ris 重启成 Prism、蓝屏原文与错误码、300 万点进度条）都对过原文，但国服时间线未独立核实。遇到对方纠正，以对方为准。

---

## 八、交给 Codex 的固定验收输入

接入运行期后，在**测试 QQ** 上跑这批句子。

**必须注入**
```
ACID是谁啊
7ref是啥
我昨天打到第七道门了
墓守这歌怎么样
万花筒解谜到哪了
街霸6杰米怎么玩
三角洲跑刀怎么打
小男娘音怎么练
7ref 和 KALEIDXSCOPE 有关系吗
```

**必须不注入（日常短句不该冒出知识）**
```
在干嘛
我去睡了
看你忙一天了
学校对面的那家店
今天忙一天了，晚上想打舞萌
[图片:任意.jpg]
好像能旋转
并非痛包
看到立绘脸红吗
我干脆直接入坑邦邦得了
什么雷霆封面
光是看外貌和性格也能看出来
```

**必须注入（弱词，DS-03 新增）**
```
旋转怎么打
立绘是什么
痛包怎么弄
雷霆的话是什么
怎么入坑
你什么性格
辉夜姬是谁
他在打天爆
今天爆率高会摸回来的     ← 应命中「大红 / 爆率（搜打撤）」，不是《Heavenly Blast》
```

**必须注入（self 人话问句，DS-03 第三轮新增）**
```
你打舞萌吗               ← 应命中「会不会打舞萌 / 什么水平」，不是「打舞萌会电我」
你什么段位
你有R值吗
你几岁
你唱歌吗
你住哪
你是不是真人
你打过实体机吗           ← 2026-10-22 设定反转后新增的别名族
你上过机台吗
你会出勤吗
你和夏玛拼过机吗
```

**必须不注入（日常/隐私）**
```
开盒是什么意思
雌小鬼是啥
你叫什么名字
什么意思
真的假的
你是格调
```

**判定方法**：看该轮 prompt 里有没有 `可参考的知识（只在相关时自然用上…` 这一行，以及后面跟的条目。**不要用「回复里提没提到」来判定**——模型可能收到知识但选择不提，也可能不提是对的。

离线等价命令：

```bat
"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\venv\Scripts\python.exe" knowledge\inject.py "墓守这歌怎么样"
```

---

## 九、改动清单

| 文件 | 改动 |
| --- | --- |
| `knowledge/query.py` | 新增 `SEP`/`GENERIC_CAP`/`NGRAM_ONLY_CAP`/`GAME_WORDS`/`VRC_WORDS`/`CONTEXT_WORDS`/`PLACEHOLDER_ASCII`/`WEAK_ALIASES`/`WEAK_VERB_PREFIX`；`GENERIC_ALIASES` 扩到约 52 词；别名整段命中给满分；别名 clean 命中（仅 self 主题）给 20.0；tags 整句给独立证据；纯 n-gram 封顶；标题命中 15.0；单字/纯数字/2 字符 ASCII 门禁；`_pick_non_overlapping`；`normalize` 加 lru_cache |
| `data/regression_cases.json` | 59 → 93 → 113 → **120** 条（v4 结构化，每条带 `why`；DS-03 加 20 条弱词与「大红/爆率」用例，第三轮再加 7 条「别名 clean 命中」正负用例） |
| `data/build_regression_cases.py` | 新建，用例生成器 |
| `data/probe_regression.py` | 重写为自动断言版（退出码 0/1/2、lint 断言、隐私词、长度） |
| `data/check_probe_asserts.py` | 新建，三种破坏的退出码自检 |
| `data/inject_audit.py` | 新建，全量语料审计 |
| `data/debug_score.py` | 新建，单条查询分数拆解 |
| `docs/knowledge-regression.md` | 本文件，DS-01 版重写为 DS-02 版 |

**未改**：`prompts/system.txt`、`persona/`、AstrBot 运行实例配置、`knowledge/src/` 下任何条目内容（除自检时临时改动并已还原的一条 summary）。**未部署、未向 QQ 发消息。**

`knowledge/inject.py` 的过期阈值注释问题：**实际不需要改**。它的 docstring 现在写的就是「阈值 10.0 是用真实语料标定出来的（`data/inject_sample.py`）：调到 8.0 时命中率 17%……10.0 时剩下的是「出勤」「改模」「何意味」这类真在聊的」，并补了「这个阈值**不是**误命中的主要防线」。任务单里说的「仍写 12.0 是实测出来的线」，`grep` 只在 `docs/assignments-20261021.md`（任务单原文引用）和旧的 `__pycache__` 字节码里出现。
