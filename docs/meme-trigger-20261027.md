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
