# D4-⑦ 空窗消息补拉（场景 B）实现与验收

2026-10-31 · 对应 Codex 终验「D4 第 7 断言未通过：缺端到端证据、场景 B 未实现」

## 一、问题定义

QQ 掉线有两种，处理方式完全不同：

| 场景 | 现象 | 是否需要补拉 |
|---|---|---|
| **A：QQ 掉线** | QQ 进程/登录态没了，对方消息留在腾讯服务器 | **不需要**。重登后 QQ 自己会推离线消息（10-28 实证：扫码后积压 6 条自动进来） |
| **B：QQ 在线但机器人停摆** | SnowLuma 正常收消息，AstrBot 重启/假死期间没处理 | **需要**。消息进了 QQ 却不进 AstrBot，重启后永久丢失 |

Codex 终验时场景 B 只有「接口能拉回历史」的可行性报告，没有实现、没有端到端证据。本文档记录实现与验收。

## 二、实现：`astrbot_plugin_miruku_backfill`

新插件（v0.1.0），启动完成后向 SnowLuma 的 OneBot HTTP `get_friend_msg_history` 查询最近历史，把空窗期内对方发来且未处理的消息重新构造成 `AstrBotMessage`，交回 `platform_inst.handle_msg()`，走**完整正常管线**（LLM → 装饰 → 表情包 → 出站闸门），效果等同对方刚刚发来。

### 关键设计（四条硬约束，写进插件 docstring）

1. **只补对方发的** —— 自己发的补进去会和已有的历史回复打架。
2. **只补一次** —— `message_id` 落盘去重（`injected_ids`，只留最近 200 条）。否则每次重启都追认一遍。
3. **只在空窗内补** —— 默认 120 分钟。半天前的质问现在回更奇怪。
4. **单人有上限** —— 默认 3 条。5 条一起注入 = 5 次 LLM + 5 条回复刷屏。

另外两条自证要求：
- **首次运行无基线时只建基线，不补历史**（否则第一次装上就把 120 分钟内的历史全补一遍）。
- **纯图片消息跳过** —— `[图片]` 占位没有语义内容，注入一条只有占位的消息只会让模型对着空气回复。图文混合才保留占位。

### 关键技术点

- **平台注入入口**：`platform_inst.handle_msg(AstrBotMessage)`（`core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py:509`），内部 `commit_event(create_event(message))` 走完整管线。
- **bot uin 不靠猜**：从历史里反推「sender 不是对方的那个」= bot，不读 `self_id`。
- **token 读取**：HTTP API 要**全局** `onebot.json` 的 `networks.httpServers[0].accessToken`（Bearer）。账号级 `onebot_<uin>.json` 的 token 是 WS 反连用的，用了会 401。
- **容器看不见宿主路径**：`onebot.json` 在 `/var/lib/docker/volumes/qq-gateway-data/_data/`，插件在 astrbot 容器里读不到。新增 `server/sync-onebot-token.sh` 由宿主读出 token 写进容器，插件 `_read_token()` 先读缓存再回退直读。
- **日志只记条数与时间，不打正文**（隐私铁律）。

## 三、验收

### 探针 `data/probe_backfill.py`（26/26 全绿）

用「向 `sys.modules` 注入假 astrbot 模块 + `spec_from_file_location` 原样 import 真插件」的方式测真文件，不做源码字符串改写。

覆盖：首次只建基线不补 / 只选空窗内对方消息 / 太老跳过计 `skipped_old` / 已补过不重复计 `skipped_dup` / 上限只取最新 N 条计 `skipped_cap` / bot uin 从历史发现 / 注入 `handle_msg` 且 ABM 字段正确 / 注入后基线前移+去重累积+落盘 / 平台不在线只记 `no_platform` 不炸 / 图文混合拼接。

**探针抓到的真 bug**：初版把纯图片消息当成有内容（选出 `['空窗二','[图片]','空窗三']`），修 `_message_text` 加 `has_text` 判定后 26/26。

### 线上端到端演练（真实制造空窗）

实测号 10000001 两小时内只有机器人发的消息、没有对方发的文本，所以临时把 `max_age_minutes` 放宽到 1440 并把 `last_handled_ts` 拨到该号最后一条**带文本**消息之前，制造真实空窗：

```
[miruku_backfill] 10000001 发现空窗消息 1 条，开始补拉
[miruku_backfill] 已补拉 uid=10000001 msg_id=-494585010 age=43620s
[meme_manager] 去重后的最终表情列表: []
[respond.stage] Prepare to send - OTTO/10000001: ?这才早上九点呢
[miruku_backfill] 本轮结束 注入=1 累计 injected=1 dup=0 old=0 cap=0 failed=0
```

补拉的消息**完整走了 LLM → 表情包 → 出站闸门 → 真实发送**，收到回复气泡 `?这才早上九点呢`，`injected_ids` 落盘记录该 msg_id。

**幂等复验**：再次放宽 `max_age` 并重启，输出 `注入=0 dup=0`，`injected_ids` 未重复增长 —— 时间线（`last_handled_ts` 已前移）+ msg_id 双保险都在。

演练后 `max_age_minutes` 已还原 120。

## 四、顺带修掉的 heartbeat v3 回归（严重）

演练中发现心跳误报 `QQ_OFFLINE / qq_login=no-signal`，而机器人当时正常收发消息。

**根因**：`login detected` 只在真正登录那一刻打一次，一直在线就不会再打。heartbeat v2 只读「昨天 + 今天」两个日志文件 → **跨天之后必然找不到事件**，判成 `no-signal` → 误报掉线 + 微信推送轰炸风险。

**修复（v3）**：
1. 扫全部日志（近 7 个文件）取最后一次登录事件，不再只看两天。
2. 增加正向确认：今天日志 15 分钟内有写入 = 会话真在跑 → `online-by-activity`。只用于把 `no-signal` 升级，**绝不覆盖 `awaiting`**（凭据失效时日志仍在轮询，不能算在线）。

修后实测 `status=OK up=true/true qq_login=online`，并清掉 SENTFLAG（下次真掉线能重新推）。

## 五、部署物

| 文件 | 作用 |
|---|---|
| `astrbot_plugin_miruku_backfill/{main.py,_conf_schema.json,metadata.yaml}` | 补拉插件 |
| `data/probe_backfill.py` | 26 条验收探针 |
| `server/sync-onebot-token.sh` | 宿主→容器 token 同步 |
| `server/heartbeat.sh` | v3：token 同步挂进在线分支 + QQ 在线判定跨天修复 |

## 六、遗留

- 场景 B 只在「启动时补一次」。运行期间 AstrBot 假死（WS 连着不处理，10-28 实证过）不会触发补拉 —— 那种情况心跳会报 `NO_WS_LINK` 并重启 astrbot，重启后由本插件补。
- `max_age_minutes` 默认 120 分钟是拍的，没有实测依据。若发现真掉线超过 2 小时，需要调大。
- 后端 `_fetch_history` 固定拉 30 条；若空窗内消息超过 30 条会漏（有 `skipped_cap` 计数可观察）。
