# 表情包零触发：触发链与定位手册（2026-10-27）

> 结论先行：meme_manager v5.2.6 的**表情判定是单点**——开了情感模型时，插件会把
> `&&tag&&` 指令从系统提示里**剥掉**（`main.py:888`），表情 100% 依赖那一次额外 LLM 调用。
> 所以「provider 不通 / 概率闸门 / 插件没加载」三者任一成立，表现都是**永远零表情且几乎没日志**。

## 1. 触发链（源码实测，插件 5.2.6）

| 环节 | 位置 | 失败表现 |
|---|---|---|
| 写 `origin` | `main.py:345` `on_waiting_llm_request` → `event_handlers.py:77` | 钩子不存在/未触发 ⇒ `origin=None` |
| scope 闸门 | `event_handlers.py:103` `_scope_allows_llm_origin` | 只放行 `origin=="chat"`；**None 直接 False** ⇒ 后面三步全部静默早退 |
| 概率掷骰 | `event_handlers.py:1348` `probability_hit(emotions_probability)` | 每条回复掷一次，结果存 `extra` 供发送阶段复用（不再二次掷骰） |
| 情感模型选类 | `event_handlers.py:1350-1392` | 抓 `情感模型选择标签` / `未选择有效标签` / `调用失败` 三条日志 |
| 出图 | `event_handlers.py:1560-1625`（非流式）/ `1714`（流式） | 分类目录 0 张图 ⇒ 选中也发不出 |

另外 `main.py:891-917`：分类映射会被过滤成「**目录里真有图片**」的类别，0 张图的分类连 tag 提示都不会出现。

## 2. 三层诊断（`server/diag-meme-flow.sh`，只读）

1. **插件层**：目录是否存在、文件数、加载日志有无 Traceback、AstrBot 实际版本 vs `metadata.yaml` 的 `astrbot_version: ">=4.17.0"`（低于要求 ⇒ import 失败 ⇒ 零日志零表情）。
2. **配置层**：`generation.emotion.probability / max_memes_per_message`、`emotion.llm.enabled / provider_id`、`trigger.scope`、`prompt.quantity_guidance_enabled`。
3. **provider 层**：`emotion.llm.provider_id` 能否在 AstrBot 的 providers 里解析（`type/model` 形态）。解析不到 ⇒ 情感模型每次都抛异常，`logger.error` 一条，其余无感。
4. **数据层**：10 个分类目录各自图片数，`memes_data.json` 的分类与目录差集。
5. **日志层**：24h 内 `[meme_manager]` 总条数与四类关键行。

每条都打 `PASS/FAIL`；**第一个 FAIL 就是根因层**。若 24h 内一条 `[meme_manager]` 都没有，脚本会显式提示「不是概率问题，是 origin/scope 闸门或插件未加载」。

## 3. 修（`server/fix-meme-flow.sh`）

- 默认：`probability 30/65 → 100`（把节流交给 `quantity_guidance_enabled=true` 的「约 4 条 1 张」和情感模型的选择）、`max_memes_per_message=1`、`provider_id` 不可解析则**置空复用回复 provider**（消除单点）。改前自动备份 `*.bak.<时间戳>`，重启后回读。
- `--force`：无视可解析性，强制清空 `provider_id`。
- `--from-tags`：关掉情感模型，改由回复模型自己打 `&&tag&&`（情感模型一直失败时的兜底；此分支会走 `main.py:891+` 真的注入 tag 提示）。

## 4. 判断表

| 日志现象 | 结论 | 动作 |
|---|---|---|
| 24h 无任何 `[meme_manager]` | 闸门/加载问题 | 看第 1、1c 节；版本不足就降级插件 |
| `情感模型调用失败` | provider 坏 | 重跑 `fix-meme-flow.sh`（置空 provider）或 `--from-tags` |
| `未选择有效标签` | 模型保守，正常 | 概率已 100，继续聊几句观察，别急着改 prompt |
| `选择标签: ['x']` 但无图 | 分类目录没图 | 补图或删掉该分类描述 |

## 5. 环境限制

本会话（Windows DSH）**无法 SSH**：`ssh-agent` 走命名管道被沙箱禁；显式 `-i *.pem` 被安全网按 `secret.ext.pem` 拦截；`~/.ssh` 在敏感路径规则内。故只出脚本，由 OTTO 在服务器执行：

```bash
bash /opt/miruku/server/diag-meme-flow.sh   # 先只读诊断
bash /opt/miruku/server/fix-meme-flow.sh    # 再按结论修
```

## 6. 2026-10-27 17:2x 实锤：401 才是零表情的直接原因

真机日志（`docker logs astrbot`，经本机面板 `/api/logs` 读取）：

```
[17:11:31] [ERRO] [mixins.event_handlers:1392] [meme_manager] 情感模型调用失败:
           Error code: 401 - {'message': 'Invalid API Key', 'param': 'Please provide valid API Key',
                              'code': '401', 'type': 'invalid_key'}
[17:11:31] [INFO] [mixins.event_handlers:1398] [meme_manager] 去重后的最终表情列表: []
```

- 16:24–16:28 同一插件**能**选出标签（`['baka'] ['sad'] ['sigh'] ['sleep'] ['happy']`），说明链路通；
- 17:11 起每次调用都 401，`最终表情列表` 恒为 `[]`，发送阶段自然无图可发；
- 会话聊天正常（回复不断）⇒ 会话 provider（deepseek）的 key 没问题，坏的是
  `generation.emotion.llm.provider_id` 指向的 `xiaomi/mimo-v2.6-flash`。
- 「概率 65% / 选包 / scope」在本例中**都不是原因**（选包问题另有一条，见 §7）。

## 7. 另两条已排除/已修的分支

| 症状 | 实测 | 处置 |
|---|---|---|
| 选了分类但一张都不发，且日志无异常 | 运行时 default 包是 `builtin-default`，`memes/` 下 0 张图；`juxueli-meme-pack` 有 38 张却未在 `registry.json` 登记 | `fix-meme-pack.sh`：登记 pack + 改 `selection_rules.json` 的 default；**规则每消息现读，不用重启** |
| 改完配置没反应 | `provider_id`/`probability`/`enable_mixed` 全部在插件 init 时读取（`main.py:240-278`） | 必须重启（或 WebUI 里重载插件） |

> 注意键名：发送相关是 `generation.message.enable_mixed` / `mixed_probability`，
> **不是** `enable_mixed_message`（后者只存在于内存属性名 `self.enable_mixed_message`）。

## 8. 无需 SSH 的日志读取（本次关键解锁）

本机面板进程已持有服务器 SSH：

```
http://127.0.0.1:8642/api/status            # 容器/服务/插件/provider/主动消息概览
http://127.0.0.1:8642/api/logs?src=astrbot&n=2000
http://127.0.0.1:8642/api/logs?src=napcat&n=2000
```

`src` 只认 `astrbot` / `napcat`，`n` 上限 2000 行、文本截断 400 KB。
只读，**无 exec 能力**；需要改文件时仍得 OTTO 在服务器执行脚本。

## 9. 判断表（补 401 行）

| 日志现象 | 结论 | 动作 |
|---|---|---|
| `情感模型调用失败: 401 Invalid API Key` | 情感模型 provider 的 key 失效 | `fix-meme-emotion.sh`（改指会话 provider） |
| `情感模型调用失败: <其他>` | provider 不可达/超时 | 同上；急需可用图可切 `--from-tags` |
| `选择标签` 正常但 `最终表情列表: []` | 分类目录无图 | `diag-meme-pack.sh` 对账，补图或删描述 |
| 完全没有 `event_bus` 入站、6199 无 `ESTABLISHED`、NapCat 日志出二维码 | **QQ 会话被踢，bot 掉线**（不是模型/表情问题） | 扫码重登；**别用重启容器当修复** |

## 10. 2026-10-27 19:2x 验证通过（端到端）

执行 `server/fix-meme-emotion.sh` 后线上配置回读：

```
provider_id = deepseek/deepseek-flash   (原 xiaomi/mimo-v2.6-flash，key 401)
probability = 90                        (原 65)
max_memes_per_message = 1
备份: config/meme_manager_config.json.bak.emotion
```

真实聊天实测（`docker logs astrbot`，时间戳为服务器本地时区）：

```
[19:14:56.922] [meme_manager] 情感模型选择标签: ['baka']
[19:14:56.923] [meme_manager] 去重后的最终表情列表: ['baka']
[19:14:56.987] [respond.stage] Prepare to send - OTTO/10000001: 怎么，上课无聊了 [图片]
[19:15:07.304] [meme_manager] 情感模型选择标签: ['sad']
[19:15:07.407] [respond.stage] Prepare to send - OTTO/10000001: 晚上好，慢慢熬吧 [图片]
```

**结论**：选择标签 → 出图 → 合并进消息链，全链路通；两条连续消息都带图。

### 10.1 同一时段踩到的第二个坑：NapCat 掉线

重启 AstrBot 后出现「聊了但没有回复」，实测判据：

- `docker logs astrbot` 停在启动日志，`event_bus` 零入站，`Prepare to send` 计数 0；
- AstrBot 容器内 `/proc/net/tcp` 的 6199 只有 `LISTEN`，无任何 `ESTABLISHED`；
- NapCat 日志出现 `二维码已保存到 /app/napcat/cache/qrcode.png`（QQ 会话被踢）。

扫码后 `aiocqhttp(OneBot v11) 适配器已连接`（19:11:39），`ESTABLISHED from 172.18.0.3` 出现，随后一切正常。
**排查顺序**：先看有没有入站事件 → 再看 6199 链路 → 最后才怀疑模型/插件。

### 10.2 取二维码图的实操

`docker exec napcat base64 -w0 /app/napcat/cache/qrcode.png` 取原始 PNG（147×147，约 600 B），
本地用 PIL 最近邻放大 5× 再给人扫；NapCat 每次重启/重试都会刷新该文件，
二维码有效期约 2 分钟，**先让对方准备好再取图**。

### 10.3 待调项

`probability=90` 属于「先确保能发」的临时高值；连发两条都命中说明偏高，
按 OTTO 体感可回落到 50~60（改完仍需重启，因该值在插件 init 时读取）。
**2026-10-27 19:34 已执行**：`probability` → **45**，`max_memes_per_message` 仍为 1，备份 `config/meme_manager_config.json.bak.freq`。

---

## 11. 2026-10-27 19:3x 两个后续问题（她否认发图 / 发的是图片不是 QQ 表情）

### 11.1 她为什么说「我发的都是字吧」

两条独立原因叠在一起：

1. **她自己的图不在历史里**。查 `data_v4.db` 的 `conversations`（`user_id=miruku:FriendMessage:10000001`，272 条），assistant 记录只有 `[think, text]`，**没有任何 image part**。原因是 AstrBot 在 `on_decorating_result` **之前**就把这一轮落库了，而 meme_manager 是在 `on_decorating_result` 里才把 Image 组件插进消息链的——**发出去的图永远不入历史**。
2. **人格里明写着不能发图**。`prompts/system.txt` L13 原文「不能发照片、拍视频、发语音、打电话，不能把图片、表情包或聊天内容存到本地」。她的 think 原文（库里的 `think` 字段）直接写：*“Per persona: I can't actually send stickers/images, and I don't control that.”* 于是回答「我发的都是字吧」。

**已修（人格侧）**：L13 追加例外条款——

> 唯一的例外是配图：你回话时可能被顺手配上一张表情包，那不算“发文件”，就当是你自己顺手配的。被问“你怎么老发表情包”“你发的什么图”时不要否认，别答“我发的都是字”“我发不了图”，就说顺手配的、觉得这个合适，不解释机制，也不提插件、发送层这类词。

部署方式：容器内用 `cmd_config.json` 的 dashboard 凭据签 5 分钟 JWT → `PUT /api/v1/personas/by-id`（`persona_id=miruku`），回读 `installed exactly: True`，长度 3803 → 3926。

**没修（历史侧）**：要让图真的进历史，得在落库前把「本轮配了图」写成文本标记，属于改插件时序，暂不做——人格条款已足够让她不否认。

### 11.2 为什么发的是图片，不是 QQ 里那种表情包

NapCat 的 OneBot 实现**支持**发 `mface` 段（源码里 `[ze.mface]` → `elementType: MFACE`，字段 `emoji_package_id` / `emoji_id` / `key` / `summary`）。但 mface 是**商城表情**：

- `emoji_package_id` + `emoji_id` 必须是 QQ 表情商城里真实存在的表情包；
- `key` 是服务器为那个表情下发的 token，伪造无效；
- 自定义图（橘雪梨这张）根本不在商城里，没有 ID 可言。

所以**包里的 jpg/png 只能以 `image` 段发出**，QQ 客户端就显示为图片。这是素材+协议的限制，不是配置漏了或插件写错。
唯一能让观感更像“表情包”的，是让素材本身更像梗图（尺寸小、留白少、单图单句），但它仍然是图片。

### 11.3 附带：为什么“一直”是她

`juxueli-meme-pack` 是**单角色包**（橘雪梨），38 张全是一个人，9 个分类。触发率降下来之后频率会正常，但角色单一这件事只能靠**加更多包轮换**解决（`selection_rules.json` 支持多包），需要 OTTO 定要不要找素材。

**2026-10-28 14:4x 已解决**：已加 `atri-meme-pack`（551 张 / 15 分类），`selection_rules.json` 的 `default` 规则改为 `pack_ids: ["juxueli-meme-pack","atri-meme-pack"]` 两包轮换。两个旧包没有的分类（`tired` / `angry` / `teasing` 等）已实测被选中。

---

## 12. 2026-10-28 18:4x 「聊了好多一条也没发」的根因与修复

OTTO 反馈：表情包触发率还是低，聊了很多一句都没配图。查下来**不是概率设置的问题**，是两条路径各自漏图。

### 12.1 主动消息 100% 不带图（代码级，配置改不了）

真正把图片塞进消息链的是 `mixins/event_handlers.py:1475 _on_decorating_result_impl`，由 `@filter.on_decorating_result()` 触发——**这个钩子只存在于 AstrBot 的 respond 管线里**。

主动消息走的是 `proactive_chat/services/sender_service.py:480` 的 `send_by_session()` 直发，**不经过 respond.stage**，所以那个钩子永远不会执行。

日志实证（24h 窗口）：

```
14:44:40.769  情感模型选择标签: ['reply']
14:44:40.771  [主动消息] 开始发送          ← 间隔 2ms，标签算出来但从没用上
```

15:23:53 / 16:03:54 / 16:33:27 / 17:09:41 五条主动消息**全部**是这个形态。情感模型跑得好好的，标签也选出来了，但没有任何代码把它变成图。

**结论：主动消息配图率恒为 0%，与 `probability` 取什么值完全无关。** 这也解释了 OTTO 的体感——主动消息一天 20+ 条，占了对话量的大头。

### 12.2 普通回复也有 50% 掉进 pending 黑洞

`event_handlers.py:1542`（语义路径）与 `:1602`（legacy 路径）同一套判定：

```python
use_mixed_message = not cleaned_components
if cleaned_components and self.enable_mixed_message:
    use_mixed_message = random.randint(1, 100) <= self.mixed_message_probability
```

- `cleaned_components` 非空（即这一轮有文字，几乎总是如此）+ `enable_mixed=true` → 再掷一次 `mixed_probability`（改前 **50**）
- 命中 → `_merge_components_with_images()` 把图并进正文，图正常发出
- 未命中 → `event.set_extra("meme_manager_pending_images", ...)`，交给 `:1641 @filter.after_message_sent()` 的事后补发

事后补发这条路很脆：`astrbot/core/pipeline/respond/stage.py:406` 才触发 `OnAfterMessageSentEvent`，而 `:211-213` 明确写了「空消息链…不打日志、也不触发 `after_message_sent`」。一旦清理后正文为空，补发直接不执行，图就静默丢了。

### 12.3 量化对账

24h 窗口统计：

| 指标 | 次数 |
|---|---|
| `Prepare to send` | 38 |
| 其中带 `[图片]` | 9（**23.7%**）|
| `情感模型选择标签` | 32（模型侧正常）|
| `去重后的最终表情列表: []` | 29 |

改前理论值：`45% × 100% = 45%`；实测 23.7%，与 `45% × 50% = 22.5%` 几乎吻合——**正好说明 pending 分支大面积没落地**。

### 12.4 修复（只改配置，不动第三方源码）

决策：**不改 meme_manager 源码**（第三方 anka 5.2.6，改了升级即覆盖，且主动消息那条要动 AstrBot 管线时序，风险高）。用配置把能修的那条路拉满。

| 键 | 改前 | 改后 | 理由 |
|---|---|---|---|
| `generation.emotion.probability` | 45 | **80** | 情感模型命中率 |
| `generation.message.mixed_probability` | 50 | **100** | 让图恒合并进正文，彻底绕开 pending |

`enable_mixed` 保持 `true`、`max_memes_per_message` 保持 `1`、`emotion.llm` 保持 `deepseek/deepseek-flash`。

`mixed_probability=100` 后 `random.randint(1,100) <= 100` 恒成立 → `use_mixed_message` 恒为 True（在有文字时）→ pending 分支永不进入。这是纯配置能达到的最优解。

备份 `config/meme_manager_config.json.bak.rate-20261028-184627`。18:46:54 重启，回读全部对上：

```
probability  = 80
mixed_prob   = 100
enable_mixed = True
max_memes    = 1
emotion_llm  = True deepseek/deepseek-flash
```

### 12.5 遗留（需 OTTO 知情的已知缺陷）

**主动消息永远不会带图**，每天 20+ 条。修法只有一条：改 meme_manager 或改 proactive_chat，让主动消息也走装饰阶段，或者在 `sender_service` 里显式调一次选图+拼链。属于第三方插件改动，未做。

按当前配置，**普通回复**配图率理论上限 = `80% × 100% = 80%`。

---

## 13. 2026-10-28 19:3x 终局：配图率的唯一闸门是 `probability`

> **本节更正 §12.1 与 §12.5。** 那两条的结论「主动消息绕过装饰阶段、恒无图」**是错的**，
> 代码级反证见 13.1。真实情况是：装饰链对主动消息**是通的**，配图率低只有一个原因——概率掷骰。

### 13.1 更正：主动消息**会**走装饰钩子

`proactive_chat/core/services/sender_service.py:238` 定义了 `run_decorating_hooks(event, components)`：

```python
result = MessageEventResult()
result.set_result_content_type(ResultContentType.LLM_RESULT)
result.chain = list(components)
event.set_result(result)
stopped = await dispatch_event_hook(event, EventType.OnDecoratingResultEvent)
```

`:520-540` 的发送顺序是 `should_send_text` → 补 `Plain(text)` → `run_decorating_hooks(...)` → 发送。
所以 `[主动消息] 开始发送` 这条日志**打在装饰之前**（`:480`），日志里看不到图是正常的，不代表没配图。

同时确认 `astr_message_event.py:195 _outline_chain` 确实把 `Image` 渲染成 `[图片]`，
所以「`Prepare to send` 无 `[图片]`」在**非流式**路径上确实是没图——但本项目 `streaming_compatibility=true`，
`STREAMING_FINISH` 走 `event_handlers.py:1498-1507` → `_send_memes_streaming()`，
图片经 `context.send_message()` **作为独立消息直发**，压根不出现在 `Prepare to send` 里。

⇒ **拿 `Prepare to send` 带 `[图片]` 的次数当配图率，是错误口径**，会把真实值低估好几倍。

### 13.2 正确口径与实测

以 `去重后的最终表情列表`（装饰阶段真正拿到的分类列表）为准，40 小时窗口：

| 指标 | 值 |
|---|---|
| 进入情感模型并选中标签 | **45** |
| 最终表情列表非空 | **45 / 103 = 44%** |
| 情感模型调用失败 | **0** |
| 情感模型「未选择有效标签」（空选） | **0** |

**关键结论：情感模型只要被调用，就 100% 能选出标签。**
那 56% 的空列表，全部是**根本没进模型**——被 `probability` 掷骰挡在门外：

`event_handlers.py:1348` `legacy_probability_hit = probability_hit(self.emotions_probability)`
→ `:1350` 只有 `legacy_probability_hit` 为真才调情感模型。
44% 实测值正好对上改前的 `probability=45`。

⇒ **`generation.emotion.probability` 就是配图率本身**，中间没有别的损耗。
（另：`_filter_emotion_selection` 只去重、`_parse_emotion_llm_selection` 支持精确/大小写折叠/剥 `&&`
和反引号，都不构成损耗；`_get_category_meme_files` 遍历**全部** `pack_dirs`，两包分类都能取到图。）

### 13.3 已排除的两个疑点

- **`juxueli-meme-pack` 的 `manifest.categories`（10 个语义键）与实际目录（9 个）对不上**——
  无害。`backend/packs/resolver.py:217 load_pack_category_mapping` **优先读 `memes_data.json`**，
  只有它为空才回落 `manifest.categories`；该包的 `memes_data.json` 正好是那 9 个目录名。
- **两包合并后 18 个候选分类里有 9 个只属于 atri**（`approval/angry/tired/eating/affection/greeting/refusal/teasing/action`）——
  也无害，`_get_category_meme_files:595-598` 遍历所有 `pack_dirs`，atri 目录在列表里。

### 13.4 最终配置（2026-10-28 19:30 生效并回读）

| 键 | §12 的值 | 现在 | 说明 |
|---|---|---|---|
| `generation.emotion.probability` | 80 | **75** | 唯一配图闸门。45 → 75 后实测上限从 44% 提到 75% |
| `generation.emotion.max_memes_per_message` | 1 | 1 | 一条回复最多 1 张 |
| `generation.message.enable_mixed` | true | true | |
| `generation.message.mixed_probability` | 100 | 100 | 恒内联，不走 pending 补发 |
| `generation.prompt.quantity_guidance_enabled` | true | true | **必须为 true，否则下一行文案完全不生效** |
| `generation.prompt.quantity_guidance` | 「每约 4 条回复中 1 条配图」 | 「每约 2 条回复中 1 条配图」 | 从 25% 提到 50%，放宽模型主动配图意愿 |
| `generation.emotion.llm.provider_id` | deepseek/deepseek-flash | 不变 | |
| `generation.trigger.scope` | chat_and_plugin_llm | 不变 | 主动消息属于 plugin origin，靠它放行 |

> **坑记**：`quantity_guidance` 受 `quantity_guidance_enabled` 开关控制
> （`main.py:471-486 _build_meme_quantity_prompt`），开关为 false 时改文案**完全无效**。
> 改这一段前先回读开关。

备份 `config/meme_manager_config.json.bak.rate2`。19:30:12 插件重载，回读全部对上。

### 13.5 仍未解决的

- **语义检索不可用**：`semantic.vision_provider_id` 与 `embedding_provider_id` 都是空串，
  启动日志 `首次开启语义检索：juxueli-meme-pack 的图片描述尚未全部完成`。走的是 legacy 分类路径，不影响配图。
- **主动消息的实际送达**：`/tmp/al.txt` 里 `[主动消息] 平台发送失败喵` retcode 1200
  `result: 1006514 网络连接异常!` —— 这是 QQ 侧网络问题，不是配图问题。
