# 主动消息真实测试：流程与服务器部署交接

> 整理：DeepSeek　2026-10-26　触发：OTTO 要求「A，开始真实测试，包流程文档，等租好服务器再修」
> 当前状态：**收件人已切到「来世」，13:33 首次自动发送**。快速登录问题**暂不修**，等服务器。
> 本文分三部分：① 这次真实测试怎么跑、怎么看 ② 出问题怎么回滚 ③ 服务器到了以后怎么做

---

## 一、当前生效的配置（已核对，2026-10-26 10:35）

### 1.1 主动消息配置（通过插件 API 写入，内存+磁盘一致）

| 项 | 值 | 说明 |
| --- | --- | --- |
| `session_list` | `["miruku:FriendMessage:352***294"]` | **来世**（原为测试号） |
| `enable` | `true` | 私聊主动消息开启 |
| `auto_trigger_after_minutes` | 120 | 对方 2 小时未说话则自动触发 |
| `min_interval_minutes` / `max_interval_minutes` | 90 / 240 | 正常排期随机 1.5–4 小时 |
| `quiet_hours` | `1-8` | 凌晨 1–8 点不打扰 |
| `max_unanswered_times` | **0** | **不限制**（对方不回也不会停） |
| `segmented_reply.enable` | `true` | 分段发送开启 |
| `segmented_reply.interval` | `1.5, 3.5`（random） | 两条之间随机停 1.5–3.5 秒 |

### 1.2 已确认的运行态

```
6199 LISTEN=1  ESTABLISHED=1        ← NapCat ↔ AstrBot 已连通
jobs 总数: 1                        ← 只有来世一条任务
  来世  next_run = 2026-10-26 13:33:24  unanswered=0
机器人号 QQ 日志 10:33:33 活跃      ← 已登录
```

> **注意**：插件 `/api/status` 的 `ws_connections` 字段显示 0，但 AstrBot 日志 10:33:32 明确记录「适配器已连接」，且 TCP 上 `ESTABLISHED=1`。**`ws_connections` 是插件自己的统计口径，与实际连接不一致，不要拿它判断。** 判断连接一律看 AstrBot 日志的 `适配器已连接` 或 `Get-NetTCPConnection -RemotePort 6199`。

---

## 二、真实测试怎么跑（这次不用你做任何事）

### 2.1 时间线

| 时刻 | 会发生什么 |
| --- | --- |
| 13:33:24 | 触发首次主动消息（LLM 生成 → 分段发送 → 2 个 QQ 气泡到「来世」） |
| 之后 | 每 1.5–4 小时再发一次；若她 2 小时没说话也会补触发 |
| 凌晨 1–8 点 | 静默 |

### 2.2 你会看到什么

**来世的手机**：应该收到 1–2 条短消息（因为分段开启，长度超过阈值会拆成 2 条，间隔 1.5–3.5 秒）。

**我这边能查的证据**（你随时可以让我查）：

```bash
# ① 是否真的发出去了
grep "主动消息" logs/astrbot-20261026.log | tail -20

# 期望看到（成功）：
#   [主动消息] 开始发送 私聊 352***294 的主动消息喵。
#   [主动消息] 分段回复已启用，将发送 N 条消息喵。
#   然后没有 ERRO 行

# 失败的样子（今天 10:28 那次）：
#   [主动消息] 平台发送失败喵，尝试核心 API 兜底:
#   [主动消息] 事件发送与核心 API 兜底均未送达，不再重复尝试喵。
#   [主动消息] 私聊 352***294 的主动消息未能送达任何平台喵。

# ② 是否被记录成"已主动发过"
# 插件会写 session_data 的 unanswered_count / last_proactive_time
```

### 2.3 这次测试真正要观察的五件事

| # | 观察点 | 为什么重要 |
| --- | --- | --- |
| 1 | **来世是否真的收到气泡** | 分段发送 + 送达确认，之前从未在真实收件人上验过 |
| 2 | **两段之间的间隔** | 配置是 1.5–3.5 秒随机；太长像卡住，太短像刷屏 |
| 3 | **内容是否像人** | 主动消息用的是独立 PROMPT（不是日常 system.txt），口吻可能不一致 |
| 4 | **他回不回** | `max_unanswered_times=0` 意味着**他不回也会继续发**——这是设计还是隐患？ |
| 5 | **是否触发免打扰** | quiet_hours 1-8 已配，13:33 不在窗口内 |

> **特别提醒第 4 点**：`max_unanswered_times = 0` 表示「不设上限」。如果来世一直不回，她会**每 1.5–4 小时发一条，无限持续**。这是 C-05 记录的原始问题（当时值是 1，被 OTTO 拍板要放宽）。现在配 0 等于完全放开。**要不要设个上限（比如 2），你决定。**

---

## 三、出问题怎么回滚（三档，都很快）

### 3.1 只改回收件人（最快，10 秒）

**用现成脚本，别手搓 API**：

```bash
VENV=<launcher>/instances/<id>/venv/Scripts/python.exe

$VENV data/switch_proactive_recipient.py                    # 只查看当前
$VENV data/switch_proactive_recipient.py --to test --dry-run # 预览
$VENV data/switch_proactive_recipient.py --to test           # 切回测试号
$VENV data/switch_proactive_recipient.py --to laishi         # 切到来世
```

脚本会输出打码后的收件人（`352***294`），并且**先 GET 全量、只改 `session_list`、再整段回写**，不会冲掉 prompt / schedule / segmented_reply。

> **号码放在哪**：脚本本身不含 QQ 号，收件人 UMO 从 `data/proactive_targets.local.json` 读。
> 该文件被 `.gitignore` 的 `data/*` 排除，**不会入库**。换机器时需重新创建：
> ```json
> {"test": "miruku:FriendMessage:<测试号>", "laishi": "miruku:FriendMessage:<来世号>"}
> ```

> ⚠️ **手搓 API 有一个坑**：`POST /api/config` 对 payload 里的每个 key 是**整段替换**。
> 只传 `{"friend_settings": {"session_list": [...]}}` 会把 `friend_settings` 下**其它字段全部冲掉**（proactive_prompt、schedule_settings、segmented_reply_settings、context_settings 全丢）。
> 这就是为什么用脚本而不是一行 curl。

### 3.2 停用主动消息（不卸载）

Via WebUI `http://127.0.0.1:4100` → 配置 → `friend_settings.enable = false`。

### 3.3 完全恢复改前状态

配置备份：`data/backups/proactive_config-before-laishi-20261026-102327.json`（改前，收件人是测试号）。

```powershell
# 把备份内容通过 API POST 回去，或直接覆盖磁盘文件后重载插件
```

---

## 四、等服务器到了：快速登录问题怎么修

### 4.1 已经查清的事实（两次扫码实测，不用重查）

| 观察 | 证据 |
| --- | --- |
| 扫码**不会**把机器人号写进 `login.enc` | 09:05 扫码后、10:33 扫码后，`login.enc` 的 mtime 都没变（仍是 10:12:12，只有 OTTO 号） |
| 上午 09:05 免扫成功，靠的不是 `login.enc` | 当时该文件同样只有 OTTO 号，但机器人免扫成功 |
| 免扫能力来自 **QQ 进程内的共享会话** | 两个 QQ 共用 `AppData\Roaming\QQ`，你的号先登录、会话是热的，机器人号就能借用 |
| 你的 QQ 一重启，机器人就得重扫 | 10:10 你的 QQ 重启后，10:31 机器人启动 → 快速登录失效 |
| NapCat 启动器**不支持** `--user-data-dir` | 扫了 `NapCatWinBootMain.exe`(32KB) + `NapCatWinBootHook.dll`(19KB)：以 `--` 开头的参数字符串**共 0 个** |
| NapCat 的快速登录机制 | `napcat.mjs` 里 `n.getLoginList() → LocalLoginInfoList.filter(u => u.isQuickLogin) → quickLoginWithUin(uin)`，读的就是 `login.enc` |

### 4.2 结论

> **这是结构性限制，不是 bug。** 机器人号的免扫是**寄生在你日常 QQ 会话上的**，你的 QQ 重启就断。
> **换 SnowLuma 解决不了**——它读同一套 QQ 登录态，而且官方文档明确「hook 按 QQ 版本对齐」、无头环境还要 noVNC 扫码。
> **降 `login.enc` 的兼容性也不是办法**，因为机器人号根本没被写进去。

### 4.3 服务器上的推荐做法（按优先级）

| 方案 | 做法 | 优点 | 代价 |
| --- | --- | --- | --- |
| **A（推荐）** | 服务器上**只跑机器人号**，首次扫码后观察 `login.enc` 是否变 2 条 | 环境干净，无宿主依赖 | 若仍不写入，就退到 B |
| **B** | 机器人 QQ 用**独立 Windows 用户**（本机同样适用） | profile 天然隔离 | 需管理员权限 + 重扫码 |
| **C** | 接受「偶发重扫」，配**扫码通道 + 掉线告警** | 最省事 | 需人工介入 |

**A 的关键验证点**（服务器上第一次扫码后立刻做）：

```powershell
$enc = "$env:APPDATA\QQ\auth\login.enc"
(Get-Item $enc).LastWriteTime
(Get-Content $enc -Raw) -match '<机器人号>'    # 机器人号是否出现
```

- **出现** → 说明本机的问题是「共用 profile 被抢占」，服务器上单跑就好了
- **不出现** → 确认「机器人号天生不进快速登录名单」，走 B 或 C

### 4.4 服务器上必须同时做的两件事

1. **扫码通道**：Linux 用 SnowLuma 那种 noVNC，或 Windows 服务器留远程桌面 —— 保证失效时 10 分钟能扫完
2. **掉线告警**：登录态一掉就推送到手机（微信/Server酱/Telegram 都行），而不是等你发现机器人不说话

> 这两条比换框架实在。`docs/soak-watch-card.md` 里的「心跳 + 看门狗」就是同一类东西。

---

## 五、这次操作留痕（谁改了什么）

| 时间 | 动作 | 文件/接口 | 备份 |
| --- | --- | --- | --- |
| 10:23:27 | 备份配置 | — | `data/backups/proactive_config-before-laishi-20261026-102327.json` |
| 10:23 | 手改磁盘 `session_list` → 来世 | `astrbot_plugin_proactive_chat_config.json` | 同上 |
| 10:26 | 发现手改不生效（插件读内存） | — | — |
| 10:26 | 改用插件 API `POST /api/config` 写入 | `http://127.0.0.1:4100/api/config` | 同第一次备份 |
| 10:27:50 | 触发测试 → **发送失败**（6199 无连接） | — | — |
| 10:33:32 | OTTO 扫码，适配器重连 | — | — |
| 10:35 | 确认 jobs 只有来世一条，13:33 触发 | — | — |

**关键教训**：**主动消息插件的配置不要直接改磁盘 JSON**——插件把 `self.plugin.config` 读进内存了，改磁盘不生效（实测：手改后 `/api/jobs` 仍为空、`/api/session-config` 未命中来世）。必须走 `/api/config`。

**第二条教训**：`POST /api/config` 是**按 key 整段替换**，不是 merge。改单个字段也要把该 key 下全部字段带上，否则会静默清空。`data/switch_proactive_recipient.py` 已经处理了这一点。

---

## 六、本文没做的事

- 没改 `prompts/`、`persona/`、`knowledge/`、NapCat 副本
- 没重启 AstrBot
- 没设置 `max_unanswered_times` 上限（那需要你决定）
- 没触发额外的测试消息（只触发了 10:27 那一次，且失败未送达）

---

## 七、2026-10-27 复测（主动消息已通；失败可归因到掉线）

### 7.1 结论

功能本身是通的：**手动触发一次即送达**，排期、免打扰、计数、用户回话后取消这一整套逻辑都对。今天两次失败（18:01 / 18:36）**不是插件缺陷**，而是 NapCat 在 17:56 之后掉线，发送时没有任何在线会话。真正该补的是**可观测性**（见 7.5）。

### 7.2 今日完整轨迹

| 时间 | 结果 | 证据 |
| --- | --- | --- |
| 12:29:22 | ✅ 第 2 次发送完成 | `flow_orchestrator:203` 存档进对话历史 → `:224 未回复次数: 2`，下次 15:25 |
| 12:40:12 | ✅ 第 3 次发送完成 | 同上，下次 16:39 |
| 18:01:50 | ❌ 未送达 | `astrbot_event:257` 平台发送失败 → `:279` 核心 API 也失败 → `sender_service:452` → `:600` |
| 18:36:42 | ❌ 未送达 | 同上，随后 `split_delivery:40` 跳过存档与计数并重排 |
| 19:07:27 | — | NapCat 出二维码 ⇒ 确认掉线 |
| 19:14:50 / :54 | — | 用户回「hello」「晚上好」→ `event_handlers:154` 取消任务、`:158` 计数归零，重排 20:08 → 20:15:53 |
| 19:27:14 | 手动触发 | `gating_feature:74 开始生成第 1 次主动消息，当前未回复次数: 0` |
| 19:27:15 | ✅ LLM | `llm_service:195 调用 LLM 成功` → `:272 长度 7` |
| 19:27:18 | ✅ 送达 | `sender_service:480 开始发送` → `flow_orchestrator:224 第 1 次主动消息已发送完成，未回复次数: 1`，下次 20:40:23 |

### 7.3 手动触发配方（插件 Web 端 4100，容器内）

```bash
docker exec astrbot curl -s http://127.0.0.1:4100/api/auth-info   # {"auth_required":false} 未开鉴权
docker exec astrbot curl -s http://127.0.0.1:4100/api/jobs        # 看 next_run_time / unanswered_count
docker exec astrbot curl -s -X POST \
  'http://127.0.0.1:4100/api/jobs/miruku:FriendMessage:10000001/trigger'
```

三个坑：

1. umo 里带冒号，**整个 URL 必须加引号**，否则 shell 会把 `:FriendMessage:` 当命令分隔。
2. `trigger` 是异步的，返回 `{"ok":true,"in_progress":true}` 不代表已送达，**等 3~5 秒再读日志**。
3. 配置仍要走 `POST /api/config`（见 §五）——**改磁盘 JSON 不生效**，插件 init 时已把配置读进内存。

### 7.4 日志判据

**成功链**：`gating_feature:74` → `llm_service:195` → `:272` → `sender_service:480` → `flow_orchestrator:203`（存档）→ `:224`（计数 +1）→ `:266`（下次时间）

**失败链**：`sender_service:452`（事件发送与核心 API 兜底均未送达）→ `:600`（未能送达任何平台）→ `split_delivery:40`（跳过存档与计数，直接重排）

判读要点：

- 看到 `:600` **先查 NapCat 登录态**，再看 astrbot 容器内 `/proc/net/tcp` 有没有到 `6199` 的 ESTABLISHED（只有 LISTEN 就是没连上）。
- 有失败日志但 `unanswered_count` 没动 ⇒ 没送达（符合设计）。
- 「聊了没回复」先分清**掉线**还是**链路问题**：`docker logs astrbot` 完全静止 + `Prepare to send` 计数 0 = 掉线。

### 7.5 三处观测缺口（是否补请 OTTO 定）

1. **失败原因丢失**：`adapters/astrbot_event.py:257/279/264` 三处把异常拼进日志时拿到的是空串，日志只有「平台发送失败喵，尝试核心 API 兜底: 」后面什么都没有。补成 `repr(e)` 即可，但要动第三方插件（升级会覆盖）。
2. **掉线不告警**：心跳已有 `QQ_OFFLINE` 判据，但没有主动推送通道。18:01 那次掉线，用户体感只是「她不理我」。
3. **直发绕过 respond 管线**：主动消息不走 `on_decorating_result` / `after_message_sent`，所以观察插件测不到 bot 方向的主动消息，也测不到「用户多久才回」——即 WORK_LOG 里记的 P2 观测缺口。
