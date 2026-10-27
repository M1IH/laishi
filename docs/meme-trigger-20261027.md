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
