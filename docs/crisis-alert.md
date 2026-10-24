# 危机事件告警规范（Miruku → OTTO 本人）

> **决策来源（OTTO 已拍板，不可擅改）**
> - 2026-10-21：危机事件**必须**直接告警给 OTTO 本人，而不只是让机器人发一句「你现在安全吗？」。
> - 2026-10-21：**B 档（袒露/低落）也发** QQ 告警，但**降级**为「发一次、不补发、不确认」。
> - 2026-10-21：**L3 webhook 先不配**，v1 不实现、不留半成品。
>
> 撰写：WorkBuddy 智能设计助手。初版 2026-10-21，**修订 v2 2026-10-21**（WB-03，按 Codex 退回的 6 项失败路径重写），
> **修订 v3 2026-10-21**（WB-03R，按 Codex 退回的 5 项事件身份/状态矛盾修订：指纹与发生 ID 分离、
> 去掉截断与"必然不同"断言、`ack_state` 与 `resend_state` 正交、A 档问句次数固定为两槽位、
> 撤回未授权的 B 档次日汇总）。
> **修订 v4 2026-10-22**（补 C-11，不涉及任何已拍板次数）：`push_state` **新增终态 `failed_final`**——
> B 档「发一次、不补发」那一发失败后，原枚举 `pending / sent / suppressed` 里**没有合法落点**，
> 三种凑法都会把已拍板的规则实现反（详见 §7.5、§8.1 之二）。同时明确 `suppressed_push_count`
> **只数限流抑制**，传输失败走 `delivery.failed_reason`，两者在 `PENDING.md` 与搭车行里的措辞必须分开。
> **修订 v5 2026-10-22**（补 `docs/crisis-alert-v4-review-20261022.md` 的一处阻断级缺口）：A 档**首次发送失败**时
> `first_pushed_at = null`，而 v4 仍让它带着 `resend_state = active` 并沿用"+15/+30/+45 从 `first_pushed_at` 起算"，
> 于是三个 slot 的时间**算不出来**——启动扫描要么把事件当逾期补发反复拾取，要么永远不触发。
> v5 把**首次成功前的传输重试**与**首次成功后的三次提醒补发**拆成两个时钟（详见 **§7.9**），
> 并把 `failed_final` 的释义改为不预设"尝试过"（`target_check` 拒发根本不该尝试 QQ）。
> 边界：只写产品与接口规范。未改 `prompts/system.txt`、`persona/`、运行实例配置，未写插件或启动脚本，未向任何 QQ 发消息。

---

## 一、这条链路补的是哪个缺口，以及它真实的覆盖范围

`docs/post-crisis-outreach.md` 已定：A 档危机之后，Miruku 只发一句「你现在安全吗？」。

这句话能做到的**只有保持连接**：不能阻止任何事；若对方回「不安全」，Miruku 也只能给三步行动建议；
若对方**根本不回**（在一个主动发消息都不多的人身上，这是最可能的情况），系统里除了观察插件记一条 `NULL`，
**没有任何人会知道这件事发生过**。本文件补的就是这个缺口。

### 它实际能覆盖什么（这一段是本次修订的核心，不许含糊）

~~人工置位零误判零漏判~~ ← **这个说法不成立，已删除。** 准确表述是：

**告警链路只能覆盖「被察觉到的危机」，不是「所有危机」。** 漏报有三个真实来源，且都不是 bug：

| 漏报来源 | 说明 | 能否靠工程消除 |
|---|---|---|
| ① 没人在看 | AstrBot 在跑、消息收到了，但没有任何人（或机制）去调用 `alert.py` | **不能**。这是人在环路的固有代价 |
| ② 看到了但判断"不严重" | 人工判断的主观性；同一个人不同状态下判断也不同 | 不能，但可用"宁滥勿缺"的置位指引降低 |
| ③ 机器不在线 | PC 关机/休眠时消息根本还没到本机 | 部分能（见第四节启动补扫） |

人工置位的真实价值是：**消除自动误判**（不会把一个玩梗当成危机，也不会漏掉一个隐晦表达），
**而不是消除漏判**。L1 通道"独立于 AstrBot"这个性质，只在**有人或某个机制真的去调用了 `alert.py` 之后**才成立——
如果没人调用，L1 什么都不会发生。这一点必须写在实现注释里，防止后来者把"有这条链路"误读成"有安全网"。

---

## 二、技术前提（已核实，2026-10-21 只读核查，非假设）

| 事项 | 核查结果 | 对设计的影响 |
|---|---|---|
| 机器人 QQ | `10000004` | — |
| OTTO 本人 QQ | `10000001`，已有私聊会话 `miruku:FriendMessage:10000001`（最后活跃 2026-10-20） | QQ 告警可直发，无需建好友 |
| **该会话同时是当前"测试会话"** | 同一会话既用来测 Miruku，也用来收告警 | **必须做上下文隔离**，见第五节 5.3——否则 Miruku 会在自己上下文里读到"来世说了自伤的话" |
| NapCat 连接方式 | OneBot v11 **反向 WebSocket 客户端**，连 `ws://127.0.0.1:6199/ws`，**未开 HTTP server** | 不能脱离 AstrBot 直调 OneBot API |
| AstrBot dashboard | 只有 webchat 的 `/chat/*`，**没有「发到平台会话」的接口** | 不能用 REST 发 QQ |
| `notification_settings` | proactive_chat 插件自带的**作者公告轮询** | **不可复用**，别误用 |
| 可用发送原语 | 插件内 `context.send_message` / `target_platform.send_by_session()` | QQ 通道必须由插件发 |

**结论**：QQ 通道依赖 AstrBot 进程活着，所以**必须**有不依赖它的本地通道。这是三层设计的原因。

---

## 三、递送状态：四个互不替代的状态（本次修订新增，最重要的一节）

~~任一层成功即算送达~~ ← **错误，已删除。** 本地写了个文件，不等于有人知道。四种状态必须分开记录、分别上报：

| 状态 | 判据 | 它能证明什么 | **它不能证明什么** |
|---|---|---|---|
| `recorded` | `events/<occurrence_id>.json` 已落盘 | 事件**没有丢**，重启后还能查到 | 任何人知道这件事 |
| `notified_local` | 本机弹窗/提示音已执行（系统返回成功） | 如果**此刻有人在电脑前**，他有机会看到 | 有人看到了；看到了会去处理 |
| `delivered_qq` | OneBot `send_private_msg` 返回成功 | **NapCat 已接收并交由腾讯转发** | OTTO 手机收到/看到；手机没静音；消息没被折叠 |
| `acked` | OTTO 运行 `alert_ack.py` | **OTTO 本人确认知晓** | 他已处理；危机已解除 |

> **`acked` 的存放位置（v3 更正）**：前四档里 `recorded / notified_local / delivered_qq` 是**递送**，
> 记在 `delivery` 下；`acked` 不是一次递送，而是**人的确认**，单独存在 `ack_state` 字段。
> 原因见 §7.6——它必须与"补发计划终止"分开，否则两个状态会被互相抄写。

**硬规则**：

1. **禁止把四者合并成一个"success"布尔值。** 前三档的达成时间都要记录（`delivery`），`ack_state` 单独记录。
2. **任何对外汇报（日志、PENDING.md、给 OTTO 的说明）都必须用这四档之一措辞**。禁止出现「告警已送达」「已通知」这种不分层的说法——那是把 `recorded` 冒充 `acked`。
3. **`ack_state = acked` 与「补发计划终止」是两个正交状态**（v3 更正，参见 §7.6）。
   `delivered_qq` 只说明"我发出去了"；补发跑完 3 次后 `resend_state = exhausted`，只说明**"不再自动提醒"**，
   **绝不等于 OTTO 已知晓**。`ack_state` 仍为 `unacked` 的事件**永久**留在 `PENDING.md`，不因超时消失。
4. 若一次告警最终停在 `notified_local`（QQ 一直发不出去），系统必须**显式承认失败**：
   `PENDING.md` 顶部写「⚠️ 有一条 A 档告警**只到本机**，QQ 未送达（原因：…），请勿假设已收到」。

### 各状态在真实故障下的表现（这是"边界"，必须写清）

| 故障 | 会停在哪一档 | 系统的正确行为 |
|---|---|---|
| QQ 掉登录态 / NapCat 断线（**A 档**） | `notified_local` | 事件留在 outbox 重试（退避 60s→1h 封顶，**不放弃**，见 §7.9 时钟①），`PENDING.md` 标注"QQ 未送达"；通道恢复瞬间立即补试一次 |
| QQ 掉登录态 / NapCat 断线（**B 档**，v4 补） | `notified_local` | **不重试**（已拍板「发一次、不补发」）→ `push_state = failed_final`、`delivery.failed_reason = "transport"`；`PENDING.md` 写「发送失败，按规则不补发」；**`suppressed_push_count` 不动**（那是限流专用，见 §8.1 之二） |
| AstrBot 进程挂了 | `notified_local`（L1 不依赖它） | 等 AstrBot 起来后启动补扫并补发；期间**不要**谎称已发 |
| OTTO 手机静音/未看 | `delivered_qq` | **无法检测，也不假装能检测**。这是本链路的机制上限，只能靠 A 档补发 3 次来对抗 |
| PC 休眠 / 关机 | **无任何状态产生** | 见第四节"启动补扫"：开机后补生成、并标注"延迟告警" |

---

## 四、通道与真实边界

```
危机事件（由人/机制调用 alert.py 置位）
   ├─ L1 本地（零依赖，必做）  → events/<occurrence_id>.json + Windows 弹窗 + PENDING.md
   ├─ L2 QQ  （手机可达，必做）→ 插件 → OTTO 私聊 10000001
   └─ L3 Webhook（OTTO 已定「先不配」）→ v1 不实现、不读配置、不留半成品
```

- **L1 不依赖网络、不依赖 AstrBot、不依赖 QQ 登录态。** 这是最后一道底线。
- **L2 必须存在**，因为只有它能到手机。L1 做得再好也到不了 OTTO 口袋。
- **电脑休眠/关机时的真实行为**：QQ 消息由腾讯服务器暂存，NapCat 重新上线后才推送。所以消息**不会丢**，
  但 "来世 23:00 说了自伤的话、PC 03:00 才唤醒" 这种情况，告警会是 03:00 才响。

  **因此必须有一个启动补扫（v1 就要有）**：AstrBot 启动后，扫描离线期间到达的入站消息，
  若命中硬信号 → 生成告警，正文首行写「⚠️ 延迟告警：离线期间到达，实际发生于 X 小时前」。
  没有这一条，"PC 休眠"这个最常见的场景会让整条链路静默失效——而这恰好是夜间最可能发生危机的时段。

---

## 五、目标校验：四重 fail-closed（本次修订新增）

### 5.1 为什么原设计不够

原设计只有 `assert TARGET != 10000002`。**这不够**：它只排除了"发给被观察的人"，
但没保证"真的发给了 OTTO"。任何一个配置错误、会话 ID 拼接错误、把"测试号"当成 OTTO 号、
或来世以后换了号，都可能让告警发到一个**错的、但也不是来世的**人手里——那同样不可接受：
对方会收到一条写着别人隐私的告警，而 OTTO 什么都不知道。

### 5.2 四重校验（全部通过才发，任一不通过即拒发）

发送前必须逐项校验，任一不符 → **拒发**，并走 5.4 的失败处理：

```python
# 全部为常量，不接受任何运行时覆盖
PLATFORM_ID   = "miruku"
SESSION_TYPE  = "FriendMessage"
OTTO_QQ       = "10000001"
FORBIDDEN_QQ  = "10000002"          # 来世
# 校验
assert platform_id == PLATFORM_ID                 # ① 平台
assert session_type == SESSION_TYPE               # ② 会话类型必须是私聊
assert user_id == OTTO_QQ                         # ③ 收件人
assert user_id != FORBIDDEN_QQ                    # ④ 兜底互斥
assert session_umo == f"miruku:FriendMessage:{OTTO_QQ}"   # ⑤ 完整会话 ID 一致
```

并且：**该会话必须已存在于 `conversations` 表**（`miruku:FriendMessage:10000001`，已核实存在）。
不允许"发送时顺手创建会话"——新建会话意味着目标未经验证。

**明确不给通过的三种情况**（Codex 第 3 项点名的）：
- 把**测试会话**当作成功目标，而该会话不是 OTTO 本人 → 拒发。
- 把**任何其他联系人**（含来世、含群）当作目标 → 拒发。
- 目标会话 ID 缺失或拼接不出完整 umo → 拒发。

### 5.3 上下文隔离（原设计漏掉的、很关键的一条）

OTTO 的私聊会话同时是"测试会话"。如果告警消息被写进该会话的 `platform_message_history`，
那么**Miruku 下一次在该会话回复时，会从上下文里读到「来世说了涉及自伤的话」**。后果有两个：

1. Miruku 可能主动提起这件事（在测试会话里说"来世最近……"），一旦 OTTO 截图/分享，就是二次泄漏；
2. 更糟的是，若将来这条会话历史被桥接进与来世的对话，就是**直接把告警内容说给来世听**。

**要求**：告警消息**不得进入 Miruku 的对话上下文**。两种实现任选：
- 发送时不写入 `platform_message_history`；或
- 写入时带标记（如 `metadata.alert = true`），构建上下文时**强制过滤**。

并且验收时必须实测：发一条告警后，在该会话问 Miruku"刚才有人发消息吗"，**不许**提到告警内容。

### 5.4 拒发时的处理（不许静默）

1. **事件保留**：`events/<occurrence_id>.json` 仍在，`delivery` 停在 `notified_local`；**`push_state = failed_final`、`delivery.failed_reason = "target_check"`、`resend_state = none`**（v4 补，与 §8.1 之二 的表一致——这是"递送层"与"推送状态层"两套字段，别当成矛盾）。
2. **`PENDING.md` 顶部写**：「⚠️ 目标校验失败，告警**未发送**。期望 `miruku:FriendMessage:10000001`，实际 `<...>`。请人工核对配置。」
3. **本地弹窗**仍要弹（提示"告警未能发送"）。
4. **不重试**——配置错误重试一万次也发不出去，只会掩盖问题。

---

## 六、触发来源（表述已按 WB-03 第 5 项修正）

| 版本 | 触发方式 | 真实定位 |
|---|---|---|
| **v1（先做）** | 人工置位：`python alert.py --mode crisis\|disclosure --note "..."` | **降低自动误判**，不消除漏判（见第一节漏报三来源） |
| v1 并行 | 观察插件已识别的关键词级硬信号只写 `care_candidate`，**不发告警** | 候选归候选，告警归告警 |
| v1 补充 | **启动补扫**（第四节）：离线期间到达的消息，命中硬信号时生成"延迟告警" | 覆盖"PC 关机/休眠"这个最常见的漏报来源 |
| v2（之后） | 观察插件写出结构化 `mode` 后，`crisis` 档可自动触发 | 前置条件：`mode` 不再是 `NULL` |

**硬规则：v2 上线前，模型输出的任何"我觉得这是危机"都不允许直接触发告警。**
误报会让 OTTO 半夜被叫醒处理一件没发生的事，几次之后他开始忽略告警——**那比没有告警更危险**。

---

## 七、事件身份：两个 ID，不许混用（v3 重写，对应 WB-03R 第 1、2 项）

### 7.0 v2 为什么还是错的

v2 用同一个 `event_id = sha1(...)[:8]` 同时承担两件事：

1. 判断"是不是同一句话"（内容身份）；
2. 当文件名、ack 目标、补发队列键（一次发生的身份）。

这两个身份的生命周期不同：**同一句话可以发生很多次，但内容指纹永远只有一个。** 混用必然导致
Codex 举出的那个反例——6 小时后同一句话再次发生 → 指纹一样 → 文件名一样 → **新记录覆盖旧记录，
旧的 ack 状态被冲掉**。这不是边界情况，是"同一句话隔天又说一次"这种**最常见**的情形。

### 7.1 两个 ID 的定义

| 名称 | 定义 | 回答什么问题 | 什么时候变 |
|---|---|---|---|
| `fingerprint`（内容指纹） | `sha256(mode + "\x00" + session_umo + "\x00" + normalize(text))`，**64 位十六进制全量，不截断** | "这是不是同一句话" | 只有内容变了才变 |
| `occurrence_id`（一次发生的唯一 ID） | `f"{fingerprint}__{occurred_at:%Y%m%dT%H%M%S}{rand4}"` | "这是哪一次" | **每次发生都不同** |

- `rand4`：4 位随机十六进制，只用于同一秒内并发的消歧。
  **不用自增序号**——序号需要"扫描后 +1"，一旦有人手工删文件或锁失效，序号会撞，撞了就是覆盖。
- `occurred_at` 写进文件名（本地时间），让 `events/` 目录天然按时间排序，重启扫描不需要额外索引。
- 文件名 = `events/<occurrence_id>.json`，长度约 85 字符，远低于 Windows 路径上限。
- **写入前必须再检查一次同名文件是否存在**；存在就重新生成 `rand4`。这是"永不覆盖"的最后一道保证。

### 7.2 两个 ID 各自用在哪（混用即错）

| 用途 | 用哪个 | 说明 |
|---|---|---|
| 事件文件名 | `occurrence_id` | 每次发生一个文件，**永不覆盖** |
| `alert_ack.py --event` | `occurrence_id` | 确认"这一次"，**不是**"这句话以后都不报" |
| 补发队列、待确认列表 | `occurrence_id` | — |
| 判断"同一句话 N 小时内重复" | `fingerprint` | `glob events/<fingerprint>__*.json` |
| 判断"已 ack 后重现" | `fingerprint` | 取该指纹下 `occurred_at` 最大的 occurrence，看它的 `ack_state` |
| 启动补扫防重复告警 | `fingerprint` | 离线消息要生成延迟告警前，先查该指纹是否已有 occurrence |

`alert.py` 的执行顺序（必须按这个顺序，否则会出现两处状态不一致）：

1. 算 `fingerprint`；
2. `glob events/<fingerprint>__*.json`，取 `occurred_at` 最大的一个（记作 `latest`）；
3. 按 §7.3 的窗口规则决定"复用 `latest` 并 `seen_count += 1`" 还是"新建 occurrence"；
4. 新建时生成 `occurrence_id`，查重后落盘。

### 7.3 窗口规则（同一句话反复出现时）

| 情况 | 判据 | 动作 |
|---|---|---|
| 同一指纹，距 `latest.occurred_at` **< `DEDUP_WINDOW`（默认 6h）**，且 `latest.ack_state == unacked` | 内容相同 + 短窗 + 尚未确认 | `latest.seen_count += 1`、更新 `last_seen_at`；**不新建、不再推送** |
| 同一指纹，距 `latest` **≥ 6h** | 视为新一次发生 | **新建 occurrence**（新文件），状态全新，按 §8 决定是否立即推送 |
| 同一指纹，`latest.ack_state == acked`（**无论间隔多短**） | 已确认后重现 | **一定新建 occurrence**，重新进入待推送。**"确认过"不能成为"以后这句不再报"的理由**；推送时机受 §8 的同指纹节流约束（延后，但不丢） |
| 指纹相同但 `text_len` 不同 | 碰撞或输入被改 | **拒绝合并**，新建 occurrence，`alerts.jsonl` 记 `fingerprint_conflict`，`PENDING.md` 提示人工核查 |

**注意最后两行的差别**：窗口只对"还没被确认的重复"生效。**一旦确认过，窗口不再抑制。**

### 7.4 不截断 + 碰撞处置（WB-03R 第 2 项）

v2 写"不同 `excerpt` **必然**不同 `event_id`"是**错的断言**。8 位十六进制只有 32 位熵，
按生日界，几千个事件量级上碰撞就不可忽略；即使 64 位也只能说"概率可忽略"，不能说"必然"。

修订后：

1. **指纹不截断**，用完整 64 位 sha256。32 位碰撞风险直接消失。
2. **删除"必然不同"的表述**。改为可执行判据：指纹相同 **且** `text_len` 相同 → 判为同一句话；
   指纹相同但 `text_len` 不同 → 判为**碰撞或输入不一致**，拒绝合并。
3. 事件文件必须存 `text_len`（`normalize` 之后的长度）。**存长度、不存全文**：
   既够用作判据，又不额外扩大隐私暴露面。
4. 指纹只负责"是不是同一句话"，**不承担任何唯一性承诺**；唯一性由 `occurrence_id` 单独保证。

### 7.5 事件结构（字段缺一即视为损坏）

```json
{
  "occurrence_id": "<fingerprint>__20261021T231405a3f1",
  "fingerprint": "<64 hex>",
  "text_len": 11,
  "mode": "crisis",
  "session_umo": "miruku:FriendMessage:10000001",
  "excerpt": "……我不想撑了……",
  "note": "人工置位",
  "occurred_at": "2026-10-21T23:14:05+08:00",
  "first_seen_at": "2026-10-21T23:14:05+08:00",
  "last_seen_at": "2026-10-21T23:14:05+08:00",
  "seen_count": 1,

  "ack_state": "unacked",
  "acked_at": null,

  "resend_state": "active",
  "resend_count": 0,
  "next_resend_at": "2026-10-21T23:29:07+08:00",
  "resend_exhausted_at": null,

  "delivery": {
    "recorded": "2026-10-21T23:14:05+08:00",
    "notified_local": "2026-10-21T23:14:06+08:00",
    "delivered_qq": null,
    "failed_reason": null
  },

  "push_state": "sent",
  "push_due_at": "2026-10-21T23:14:07+08:00",
  "first_pushed_at": "2026-10-21T23:14:07+08:00",
  "last_pushed_at": "2026-10-21T23:14:07+08:00",
  "suppressed_push_count": 0,

  "transport_retry": {
    "failed_attempts": 0,
    "last_attempt_at": "2026-10-21T23:14:07+08:00",
    "next_retry_at": null
  },
  "reminder_failed_count": 0
}
```

字段取值约束（超出即视为损坏）：

- `push_state`：`pending`（未推送）/ `sent`（已推送）/ `suppressed`（被限流挡下，只记流水）/ **`failed_final`（v4 新增：未成功且按规则不再尝试、不再重试）**。
  **`pending` 不是"失败"**：`push_due_at` 到时就会发（首次传输失败过的，还要同时满足 `transport_retry.next_retry_at`，见 §7.9 规则 2）；`suppressed` 是本 24h 内不会再发。
  **`failed_final` 也不是"待发"**：它是终态，调度器扫到必须**直接跳过**，不得因为 `push_due_at` 到期就重发。
  > **v5 措辞更正（Codex 复核第 3 条）**：v4 写"已尝试、未成功"，不完全覆盖 `failed_reason = "target_check"` 的情形——
  > 四重校验不通过时**根本不得尝试** QQ（§五）。终态的正确定义是"**结果未成功，且按规则不再尝试**"，
  > 它描述的是"到此为止"，不是"试过了"。**判据不看试没试过，只看还会不会再发。**
- `delivery.failed_reason`（v4 补取值约束）：`null`（未失败）／`"transport"`（QQ 侧未接受：掉线、NapCat 断、平台拒收）／`"target_check"`（四重校验拒发，见 §五）／`"quiet_hours"` 不适用（告警豁免免打扰）。
- **`push_state = sent` 与 `delivery.failed_reason` 互斥**：一个事件不可能既推送成功又带失败原因；同时出现即判损坏，启动时拒绝加载（与"`ack_state = acked` 但 `acked_at = null`"同一处理口径）。
- **`suppressed_push_count` 与 `failed_final` 互斥计数**：前者只数 `push_state = suppressed`（限流），后者**永不**增加前者。理由见 §8.1 之二。
- **`first_pushed_at = null` 时 `resend_state` 不得为 `active`**（v5 新增，本规范最强的一条判损坏）。
  理由：`active` 的含义是"15/30/45 的提醒计划正在跑"，而这个计划的起点就是 `first_pushed_at`。
  起点为 `null` 却标 `active`，等于声明"一个没有起点的计划正在进行"——这正是 v4 被 Codex 抓到的缺口：
  调度器要么算不出 `next_resend_at` 而**永不触发**，要么拿 `occurred_at` 顶上而**每轮扫描都当逾期补发**。
  首次成功前 `resend_state` 必须是 `none`，重试交给 §7.9 的传输时钟。
- `push_due_at`：**策略层**允许推送的最早时间（"能不能发"）。默认 = `occurred_at`；被 §8.3 同指纹节流时
  = `last_pushed_at + 30min`。**它只延后，不会把事件变成"不发"。**
- `first_pushed_at`：**实际首次推送成功**的时间，**只有成功才写，失败一律保持 `null`**。
  **补发三个 slot（+15/+30/+45）从它起算**，不是从 `occurred_at` 起算——否则被延后的事件会一推送就立刻触发补发。
  **`first_pushed_at = null` 是一个必须被单独处理的合法状态**（v5）：它表示"这条告警**从未成功送达过**"，
  此时**三个 slot 根本不存在**，不得按 `occurred_at + 15/30/45` 去凑时间（见 §7.9）。
- `transport_retry`（v5 新增）：**首次成功之前**的传输重试账本，只服务 A 档。
  - `failed_attempts`：失败次数（累计，成功后保留作审计，不再参与判断）；
  - `last_attempt_at`：最近一次尝试时间（成功或失败都写）；
  - `next_retry_at`：下一次允许重试的时间；`null` = 无需重试（成功过，或从未失败过）。
  - **它不参与任何"补发"语义**：不推进 `resend_count`、不影响 15/30/45、不计入 `suppressed_push_count`。
- `reminder_failed_count`（v5 新增）：**首次成功之后**，三次提醒补发中实际失败的次数（0–3）。
  与 `delivery.failed_reason` **不冲突**——`failed_reason` 描述"推送尝试的最近结果"，`push_state = sent` 时它必须是 `null`；
  而"提醒没送到"这件事不能靠改 `push_state`（那会谎报首次失败）也不该污染 `failed_reason`，所以单独计数。

**没有 `pending.json`。** "是否待推送/待补发"完全由 `push_state` / `resend_state` / `ack_state` 三个字段推导，
单一真相来源，不存在两处维护。

### 7.6 `ack_state` 与 `resend_state` 是正交的两个状态（WB-03R 第 3 项，本节是 v2 的真矛盾所在）

v2 同时写着"只有 `acked` 才停补发"和"45 分钟后停止补发"——这两句直接打架。根因是把两件事写成了一个：

| 字段 | 取值 | 谁写 | 含义 |
|---|---|---|---|
| `ack_state` | `unacked` / `acked` | **只有 `alert_ack.py`** 能写 `acked` | OTTO 本人确认知晓 |
| `resend_state` | `active` / `exhausted` / `stopped_by_ack` / `none`（B 档，或 **A 档尚未首次成功**） | 调度器 | 自动补发计划的生命周期 |

**规则**：

1. 补发计划固定 3 次（+15 / +30 / +45 分钟，从 `first_pushed_at` 起算）。
   第 3 次发完 → `resend_state = exhausted`，写 `resend_exhausted_at`。
   **这只表示"不再自动提醒"，不表示"OTTO 知道了"。**
2. `ack_state` 仍为 `unacked` 的事件，即使 `resend_state = exhausted`：
   - **永久**留在 `PENDING.md` 顶部，标注「已停止自动提醒（**未确认**）」；
   - 在任何后续告警正文末尾追加一行「另有 N 条未确认告警（已停止自动提醒）」；
   - `alert_status.py` 每次运行都把它列出来。
3. **禁止任何超时逻辑写 `acked`。** `acked_at` 只能是 `alert_ack.py` 的执行时间。
   措辞上也禁止把 `exhausted` 写成"已处理/已确认/已关闭"——统一写 **「已停止自动提醒（未确认）」**。
   这是"不许把未确认偷记成已确认"的唯一落地办法：**字段层面就不给它写的机会**。
4. ack 之后 `resend_state` 置 `stopped_by_ack`，未发的 slot 全部作废（不补发）。
5. **重启时 `resend_state` 不重置**（**前置判断：本节四条只适用于 `first_pushed_at ≠ null` 的事件**；
   `first_pushed_at = null` 的一律改走 §7.9 的传输重试，**不得进下面任何一条**）：
   - `active` 且 `now < next_resend_at` → 继续等，不立即发；
   - `active` 且 `now >= next_resend_at` 且 `resend_count < 3` → 立刻补发一次（正文标"重启补发"），推进 slot；
   - `active` 但已超过最后一个 slot → 直接转 `exhausted`，`resend_exhausted_at` 记为**实际发现时间**，
     **不补发 3 次、也不假装补过**；
   - `exhausted` / `stopped_by_ack` → 保持，只出现在 `PENDING.md`。
6. **`push_state = failed_final` 时 `resend_state` 不得为 `active`**（v4 新增，C-11）：终态不重试，若两者同为
   "还要发"，调度器会同时被两个字段驱动，必然重发。B 档失败 → `resend_state = none`；
   A 档四重校验拒发 → `resend_state = none`（§5.4 已定"不重试"）；
   A 档**传输失败**不进 `failed_final`，留在 `pending`，但（v5 更正）**`resend_state = none`**——
   它要重试，可重试的是"**首次送达**"这件事，不是"提醒补发"。**首次成功之前没有 slot 可补**，
   把 `active` 写上去会让 slot 时间无解（§7.5 判损坏、§7.9 两个时钟）。
   **判据一句话：`failed_final` 与 `active` 互斥；`first_pushed_at = null` 与 `active` 也互斥。**

### 7.7 重启恢复与并发

- **启动扫描 `events/` 全量**：**先分两路**——`first_pushed_at = null` 的 A 事件走 §7.9 的传输重试表；
  `first_pushed_at ≠ null` 的按 §7.6 第 5 条处理。B 档事件 `resend_state = none`，**永不因重启补发**。
  **分路依据只有一个字段，不许"看哪个时间近就用哪个"。**
- 状态全在文件里，不依赖内存，所以重启不会丢、也不会重复造事件。
- **启动补扫 ≠ 重启补发**（两件事，别混）：
  - 启动补扫 = 扫描**离线期间到达的入站消息**，生成**新**的延迟告警；
  - 重启补发 = 把**已经记录**但未 ack 的 A 事件按 §7.6 第 5 条继续推。
  - 两者可能对同一句话各产生一次动作 → **启动补扫在生成新事件前必须先查 `fingerprint`**，
    若已有 occurrence，则只 `seen_count += 1`，不新建、不重复告警。
- **单实例锁**：`data/alerts/.lock`（文件锁 + PID）。第二个进程**直接退出**。
  锁残留时按 PID 是否存活判断，不死锁。

### 7.8 确认（ack）

- `python alert_ack.py --event <occurrence_id>` 只确认**这一次发生**；
- `python alert_ack.py --all` 确认当前全部未确认事件（需二次确认输入 `yes`）；
- ack 一个不影响其它事件的补发计时；
- **唯一确认方式**。不拿"OTTO 在 QQ 里说了话"当确认——那可能是别人在用他的号。

### 7.9 两个时钟：首次成功前的传输重试 ≠ 首次成功后的三次提醒补发（v5 新增，补 Codex 复核的阻断项）

**v4 的写法在这里是自相矛盾的**：一边说"A 档传输失败 → `pending` + `resend_state = active`，+15/+30/+45"，
一边又说"三个 slot 从 `first_pushed_at` 起算"。可首次发送失败时 `first_pushed_at` **根本还是 `null`**——
起点不存在，slot 时间算不出来。启动扫描遇到这种事件只有两种下场，**两种都是错的**：

| 实现者的自然写法 | 后果 |
|---|---|
| 拿 `occurred_at` 顶替 `first_pushed_at` 算 slot | 事件一被创建就已"逾期"，**每轮扫描都判定该补发**，同一条告警按分钟级重发，直到把 QQ 打满 |
| 严格按 `first_pushed_at + 15min` 求值，遇 `null` 就跳过 | **永远不触发**。通道恢复了也不发，事件静静躺在 `pending`，`PENDING.md` 上写着"待推送"却没有任何东西会推它 |

根因是把两件不同的事写成了一件：**"这条告警有没有送到过"** 和 **"送到之后有没有提醒够"**。
它们是两个时钟，起点、次数、封顶规则都不同，必须分开。

#### 两个时钟的对照

| 维度 | ① 传输重试（首次成功前） | ② 提醒补发（首次成功后） |
|---|---|---|
| 要解决的问题 | 这条告警**一次都没送到** | 送到了，但 OTTO **可能没看见** |
| 适用档位 | **仅 A 档** | 仅 A 档 |
| 起点 | `push_due_at`（首个允许推送时刻，默认 = `occurred_at`） | **`first_pushed_at`**（首次成功时间） |
| 驱动字段 | `transport_retry.next_retry_at` | `next_resend_at` |
| 状态字段 | `push_state = pending`、`resend_state = none` | `push_state = sent`、`resend_state = active` |
| 次数 | **不设总次数上限**（A 档不许放弃），靠间隔封顶 | **固定 3 次**（+15/+30/+45） |
| 退避/间隔 | 60s → 180s → 600s → 1800s → **3600s 封顶** | 从 `first_pushed_at` 起每 15 分钟一次 |
| 计入 `resend_count` | **否** | **是** |
| 计入 `suppressed_push_count` | **否** | **否** |
| 计入 `failed_attempts` | **是** | 否（失败记 `reminder_failed_count`） |
| 重启后 | 按 `next_retry_at` **继续重试**（A 档不因重启放弃） | 按 §7.6 第 5 条四条分支 |
| 失败后的终态 | **没有终态**——一直 `pending`，直到成功或人工介入 | `resend_state = exhausted`（不是 `failed_final`） |

> **`first_pushed_at` 是这两个时钟唯一的分界点**：`null` → 时钟①；非 `null` → 时钟②。
> 任何实现只要在入口处判这一个字段，就不会把两条路径混起来。

#### 时钟①：传输重试的八条规则

1. **适用范围**：`push_state = pending` **且** `first_pushed_at = null` **且** `mode = crisis`（A 档）。
   **B 档永不进这条路**——B 档传输失败直接 `failed_final`（§8.1 之二），不重试、不延期、不进 outbox。
2. **生效时刻**：`effective_at = max(push_due_at, transport_retry.next_retry_at)`（`next_retry_at = null` 时只取前者）。
   `push_due_at` 管"该不该发"（策略、节流），`next_retry_at` 管"该不该现在再试"（通道），**两者取较晚，不互相覆盖**。
3. **退避阶梯**（仅失败后推进）：第 1 次失败 → +60s；第 2 次 → +180s；第 3 次 → +600s；
   第 4 次 → +1800s；第 5 次及以后 → **+3600s 封顶**。
   封顶 1 小时的理由：再长的间隔会让"NapCat 已经恢复"这件事最多晚 1 小时才被发现；
   而不封顶次数是因为 A 档是安全通道，**"放弃"不是一个可选项**。
4. **写前推进（防崩溃循环的唯一办法）**：**每次尝试之前**，先把 `transport_retry.next_retry_at` 推进到"本次 + 当前阶梯"并**落盘**，再调 `send_private_msg`。
   这样即使进程在发送中崩溃、重启后立刻重扫，也不会对着一个"到期的过去时刻"无限狂发——
   **它看到的是一个未来时刻。**
5. **失败后写什么**：`push_state` 保持 `pending`；`delivery.failed_reason = "transport"`；`delivered_qq` 保持 `null`；
   `failed_attempts += 1`；`last_attempt_at = now`；`next_retry_at` 按规则 3 推进；`resend_state` 保持 `none`。
   **`resend_count` 必须仍是 0**（这是本条最容易被写错的地方）。
6. **成功后写什么（唯一一次"状态跃迁"）**：`push_state = sent`；`delivered_qq = now`；`failed_reason = null`；
   `first_pushed_at = now`；`last_pushed_at = now`；`transport_retry.next_retry_at = null`；
   **同时**启动时钟②：`resend_state = active`、`resend_count = 0`、`next_resend_at = first_pushed_at + 15min`。
   `failed_attempts` **保留原值**（只作审计，此后不参与任何判断）。
7. **通道恢复可提前**：平台状态从非 `RUNNING` 变 `RUNNING` 时，**忽略 `next_retry_at` 立刻试一次**，
   正文标「通道恢复补发」。这是**唯一**允许无视规则 2 的路径，因为"通道刚回来"正是最该立刻发的一刻。
   - 状态源是 AstrBot 真实枚举 `PlatformStatus`（`astrbot/core/platform/platform.py` L20–26：`PENDING / RUNNING / ERROR / STOPPED`），**不是自造标志**。
   - **但"NapCat 掉线会不会真的把它翻成 `ERROR`/`STOPPED`"尚未实测**（`docs/reconnect-experience-acceptance.md` T2/T3 只记录了"需实测"）。
     所以这条**不能作为唯一手段**，必须有兜底：**任意一条消息发送成功时顺手 flush 一次待重试队列**（幂等，多跑无害）。
     二者都没有时，靠规则 3 的阶梯到点触发——**最坏晚 1 小时**，这是可接受的上限。
8. **崩溃窗口允许重复，禁止丢失**：若进程在"已发出、未落盘"之间挂掉，重启后会再发一次。
   **这是刻意的取舍**：A 档重复一条的代价是 OTTO 多看一眼，丢失一条的代价是他不知道。**永远选重复。**

#### 重启时怎么处理 `first_pushed_at = null` 的事件

| 重启时看到 | 动作 |
|---|---|
| `next_retry_at = null`（首次尝试前就崩了） | **立即尝试一次**（走规则 3 的第 1 档） |
| `now ≥ next_retry_at` | **立即尝试一次**，正文标「重启重试」 |
| `now < next_retry_at` | **等到点再试**，不得提前（避免"重启一次就多发一条"） |
| `push_state = pending` 但 `resend_state = active` | **判为损坏**（§7.5 判损坏条），按 `none` 修复并在 `PENDING.md` 记一行 |
| 已超过"最后一个 slot" | **不适用**——`first_pushed_at = null` 的事件**没有 slot**，不得因此转 `exhausted`。这正是 v4 会踩的坑 |

#### 时钟②里"补发没送到"怎么办（首次成功后）

首次成功之后，某一次提醒补发（+15/+30/+45）可能又撞上通道断。规则：

1. **失败即消耗该 slot，不追补**。下一个 slot 照原计划（+30、+45）来。
   理由：追补会在通道恢复瞬间连发两三条，比"少提醒一次"更像刷屏，而 §8.3 的节流精神是"**延后可以，堆积不行**"。
2. `reminder_failed_count += 1`，`push_state` **保持 `sent`**（他确实收到过首条，不能谎报首次失败）。
3. 三个 slot 全部落空 → `resend_state = exhausted`，**不是 `failed_final`**
   （`failed_final` 的语义是"这条从没送到"，这里首条已送到）。
4. `PENDING.md` 的措辞必须区分：
   - 提醒部分失败：`已送到 1 条，3 次提醒中 2 次未送达（QQ 未接受）`
   - 三次全失败：`已送到 1 条，3 次提醒**均未送达**（QQ 未接受），已停止自动提醒（未确认）`
   **禁止只写"已停止自动提醒"**——那会让人以为提醒发过了只是没人应。

#### 一句话判据

**`first_pushed_at = null` → 只谈"送达"（传输重试，退避到 1 小时封顶，永不放弃）；
`first_pushed_at ≠ null` → 只谈"提醒"（3 个 slot，15 分钟一次，失败即消耗）。
两者的字段、次数、终态**互不借用**；`resend_count = 0` 是"我还没开始提醒"，不是"我送不到"。**

---

## 八、限流：A 优先，B 受限，且不新增未授权推送（v3 重写，对应 WB-03R 第 5 项）

~~A+B 合计 24h 最多 8 条，第 9 条起只写文件~~ ← **会让新 A 档被先前的 B 档吞掉，已废弃（WB-03）。**

~~B 第 5 条起改为次日 12:00 一条汇总~~ ← **这条是我越权加的，已撤回（WB-03R 第 5 项）。**

OTTO 拍板 B 档的边界是 **「发一次、不补发、不确认」**。次日汇总是一条**新的推送**，
不在授权范围内。它听起来更"负责"，但它改变的是 OTTO 已经定下的**打扰预算**——
这类改动只能由 OTTO 拍板，不能由规范自行升级。

### 8.1 v1 默认规则（零额外推送）

| 档位 | 24h 上限 | 达到上限后的行为 |
|---|---|---|
| **A** | **不设总量上限**，只靠 §7 的指纹去重 + §8.3 的同指纹节流 | —（A 档的"刷屏"本身携带信息：越密集说明风险越持续，**此时沉默是最坏的选择**） |
| **A 持续模式** | 10 分钟内 ≥3 个**不同指纹**的 A 事件 → 合并为一条「持续告警」，每 30 分钟一条，上限 48 条/24h | 超 48 条 → 每 2 小时一条；`PENDING.md` 持续置顶；本地弹窗**每次都弹** |
| **B** | 4 条/24h | 第 5 条起 **不推送、不发汇总**，只写 `alerts.jsonl`、`suppressed_push_count += 1`、`PENDING.md` 记计数行 |

### 8.1 之二　`suppressed`（限流）≠ `failed`（发送失败）：为什么必须两个字段（v4 新增，C-11）

B 档的规则是「**发一次、不补发、不确认**」。这句话有个以前没写清的后果：**"这一发"本身可能发不出去**（NapCat 断、QQ 掉登录态、平台拒收）。这时事件既不是"已推送"，也不是"被限流"，更不该"等下一次"。

**三种凑法的后果，全部与已拍板规则相反**：

| 错误做法 | 表面看 | 实际后果 |
|---|---|---|
| 塞 `push_state = pending` | "以后会发" | `push_due_at` 到期被调度器反复拾取 → **"不补发"变成无限重试**，正是 OTTO 明确否掉的行为 |
| 塞 `push_state = suppressed` + 计数 | "和限流一样处理" | `suppressed_push_count` 被污染 → 搭车行把**链路故障**说成**因限流未推送**，OTTO 的归因直接错位 |
| 塞 `push_state = sent` | "看起来正常" | 直接谎报，违反 §三 第 2 条 |

**正确做法**：

| 场景 | `push_state` | `delivery.failed_reason` | 是否重试 | `suppressed_push_count` |
|---|---|---|---|---|
| B 档第 5 条起被限流 | `suppressed` | `null` | **否**（本 24h） | **+1** |
| B 档发送失败（QQ 不通） | **`failed_final`** | `"transport"` | **否**（已拍板"不补发"） | **不变** |
| B 档被四重校验拒发 | **`failed_final`** | `"target_check"` | **否**（§五 已定"不重试"） | **不变** |
| A 档发送失败 | `pending` | `"transport"` | **是**，但走 §7.9 时钟①（`resend_state = none`，退避 60s→1h 封顶） | 不适用 |
| A 档被四重校验拒发 | `failed_final` | `"target_check"` | **否** | 不适用 |

> **A 档也有 `failed_final`**：四重校验拒发是"绝不再试"（§5.4 已写"事件不删、不重试"）。以前没给它状态名，现在归到同一终态，由 `failed_reason` 区分原因。**A 档的传输失败不走这条**——它要重试，所以留在 `pending`。
>
> **v5 关键更正（这张表最容易读错的一行）**：A 档传输失败虽然"要重试"，但**重试的不是"+15/+30/+45"**。
> v4 在"是否重试"一栏括号里写的 `resend_state = active` 是错的：首次发送还没成功，`first_pushed_at` 为 `null`，
> 三个 slot 没有起点，写 `active` 等于给调度器一个算不出来的时间。正确形态是
> **`resend_state = none` + `transport_retry.next_retry_at` 驱动**（§7.9 时钟①）。
> **一句话：`resend_state` 只回答"提醒计划跑到哪一步了"，不回答"要不要再试一次送达"。**

**一天里既有成功又有失败时，`PENDING.md` 必须分两行写**：

```
今日 B 档：4 条已推送｜3 条因限流未推送（见 §8.2 搭车行）
今日 B 档：2 条发送失败（QQ 未接受，按规则不补发）；明细事件 <occurrence_id 前 8 位>
```

**这两行不能合并成"5 条未推送"**——一个说明"太多被压住"，一个说明"链路坏了"，处置完全不同：前者是预算问题，后者是故障。

### 8.2 B 超限后 OTTO 怎么知道：靠"搭车"，不靠新推送

下一条**本来就要发**的推送（A 档，或未超限的 B 档）正文末尾追加一行：

```
（今日另有 N 条 B 档因限流未推送，明细见 PENDING.md）
```

这一行**不构成额外推送**——它附着在已经要发的消息上，不新增打扰次数，
但保证"系统没有偷偷少报"。这比"次日补一条汇总"更省打扰，也更诚实。

**N 的取值范围（v4 收紧）**：`N` **只数 `push_state = suppressed`**，即"因限流未推送"。发送失败（`failed_final`）**不计入 N**，否则这一行的语义会变成"两种完全不同的原因"混在一起（见 §8.1 之二）。

- `N = 0` → **这一行不出现**（禁止写"今日另有 0 条因限流未推送"）。
- 发送失败的条数**只写 `PENDING.md`**，不搭车。
- 若要让 OTTO 在 QQ 里也知道"链路坏了"，那是一条**新的信息**（虽然不新增推送次数），属于 §十三 未决项的范围，**不在本节自动授权内**。当前默认：文件层留痕，QQ 层不报。

### 8.3 同指纹节流（新增，防"同一句话刷屏"）

同一 `fingerprint` 在 **30 分钟**内重复（**含已 ack 后重现**）→ 推送**延后**到
`last_pushed_at + 30min`，**不丢失**：新 occurrence 照常创建（`push_state = pending`，
`push_due_at` 记为延后后的时间），到期由调度器发出。

- 这条**不许静默**：`PENDING.md` 对应事件行标注「该句 30 分钟内已推送过 N 次，本次延后至 HH:MM」。
- 它**只约束"同一句话的重复推送"**，不约束"新的危机事件"：不同指纹、不同 mode 的事件永不被这条吞掉。
- 理由：OTTO 已经因为这一句话被叫起来过一次。一分钟内叫 60 次不增加任何信息，只会消耗他对告警的敏感度。
- **与 §7.3 的分工别混**：`DEDUP_WINDOW`（6h）决定"要不要新建事件"；本节只决定"新建后什么时候推"。

### 8.4 三条原则（保留）

1. **A 与 B 分开计数**，B 的用量**永不**影响 A 的发送资格。
2. **任何降级都不是静默的**：B 超限有搭车行、A 持续模式有明确标注、同指纹延后有 PENDING 标注，
   `alerts.jsonl` 永远留全量流水。
3. **A 档如果哪天真的需要设上限**（当前不需要），必须在 `PENDING.md` 顶部挂一条永久提示
   「⚠️ A 档已达上限，后续事件仅记录未推送」——**宁可让 OTTO 知道"系统不响了"，也不能让他以为"没消息=没事"**。

---

## 八之二、状态转移表（Codex 手工演算用，覆盖它要求的 7 个反例；v4 增至 15 条，新增 T13–T15 为"失败终态"；v5 增至 19 条，新增 T16–T19 为"首次失败与提醒失败"）

设：`fp` = 内容指纹；`latest` = 该 `fp` 下 `occurred_at` 最大的 occurrence；
`W` = `DEDUP_WINDOW`（6h）；`TH` = 同指纹节流窗口（30min）。

| # | 输入情形 | 查到什么 | 动作 | 文件变化 | 推送 | 之后的状态 |
|---|---|---|---|---|---|---|
| **T1** | 同一句话，距 `latest` < 6h，`latest` 未 ack | `latest.ack_state = unacked` | 复用 `latest` | 无新文件，`seen_count += 1` | **不推送** | `latest` 保持 `unacked / active` |
| **T2** | 同一句话，距 `latest` ≥ 6h，`latest` 未 ack | `latest` 存在但已过期 | **新建 occurrence** | `events/<fp>__<新时间><rand4>.json` | 推送（若未被 §8.3 延后） | 新事件 `unacked / active`；**旧事件原样保留**（若仍 unacked，两条都留在 PENDING） |
| **T3** | 同一句话，`latest` 已 ack（间隔任意短） | `latest.ack_state = acked` | **新建 occurrence** | 新文件 | 推送；若距上次推送 < 30min → **延后到窗口末**，不丢 | 新事件 `unacked / active`；旧事件 `acked / stopped_by_ack` 不动 |
| **T4** | 同一天两个**内容不同**的 A 事件 | 两个不同 `fp`，互不命中 | 各建 occurrence | **两个文件**，各自 `seen_count = 1` | **两条都立即推送**（不同指纹不过节流） | 彼此完全独立，ack 一个不影响另一个 |
| **T5** | 推送后 45 分钟仍未 ack | `resend_count = 3` | 第 3 次补发已执行 | 无 | **停止自动补发** | `resend_state = exhausted`、`ack_state` **仍为 `unacked`**；PENDING 顶部常驻「已停止自动提醒（未确认）」；后续告警尾部带计数行 |
| **T6a** | 重启，`active`，`now < next_resend_at` | 未到点 | 继续等 | 无 | 不立即发 | 不变 |
| **T6b** | 重启，`active`，`now ≥ next_resend_at`，`resend_count < 3` | 已过点 | 立刻补发一次（标"重启补发"），推进 slot | `resend_count += 1` | 发 1 条 | 仍 `active`，直到第 3 次 |
| **T6c** | 重启，`active`，但已过**最后一个** slot | 全部 slot 已过期 | 转 `exhausted`，`resend_exhausted_at` = **实际发现时间** | 改字段 | **不补 3 次、也不假装补过** | `exhausted / unacked` |
| **T7** | B 档第 5 条（24h 内） | B 计数 = 4 | 不推送 | 写 `alerts.jsonl`、`suppressed_push_count += 1` | **不发汇总** | `push_state = suppressed`；下次真实推送时带搭车行 |
| **T8** | B 档事件遇到重启 | `resend_state = none` | 跳过 | 无 | **永不因重启补发** | 不变 |
| **T9** | 已 ack 的事件遇到重启 | `ack_state = acked` | 跳过 | 无 | 不推送 | 不变 |
| **T10** | 启动补扫发现离线期间的入站消息命中硬信号 | 先查 `fp` | 已存在 → 只 `seen_count += 1`；不存在 → 新建延迟告警 | 视情况 | 1 条（首行标"延迟告警"） | 与重启补发不重复 |
| **T11** | 两个 alerter 同时启动 | `.lock` 已被持 | 第二个**直接退出** | 无 | 只 1 条 | 不产生双份 |
| **T12** | 同指纹但 `text_len` 不同 | 判为碰撞 / 输入不一致 | 新建 occurrence + 记 `fingerprint_conflict` | 新文件 | 推送 | PENDING 提示人工核查 |
| **T13** | **B 档推送时 QQ 不通**（v4 新增） | 事件已建，`push_state = pending` | 尝试 1 次，`send_private_msg` 未成功 | `push_state = failed_final`、`delivery.failed_reason = "transport"`；`suppressed_push_count` **不变** | **不重试**、不因重启补发 | `failed_final` 永久终态；PENDING 记「发送失败（按规则不补发）」 |
| **T14** | **上述 `failed_final` 事件遇到重启**（v4 新增） | `push_state = failed_final` | **直接跳过**（即使 `push_due_at` 已过） | 无 | **不推送** | 不变；若被误发，说明实现把它当成了 `pending` |
| **T15** | **同日 4 条成功 + 2 条失败 + 1 条限流**（v4 新增） | — | 三者分别落 `sent` / `failed_final` / `suppressed` | `suppressed_push_count = 1` | 下一条真实推送带「今日另有 **1** 条 B 档因限流未推送」 | PENDING **分两行**：1 条限流、2 条发送失败 |
| **T16** | **A 档首次推送 QQ 不通**（v5 新增） | 事件已建，`push_state = pending`、`first_pushed_at = null` | 尝试 1 次未成功；**先写 `next_retry_at = now+60s` 再发** | `failed_attempts = 1`、`delivery.failed_reason = "transport"`、`resend_state = **none**` | 不立即重发（等到点）；**`resend_count` 必须是 0** | 仍在 outbox，等 `next_retry_at`；**不是** `failed_final` |
| **T17** | **上述事件遇到重启**（v5 新增） | `first_pushed_at = null`、`resend_state = none` | 只看 `next_retry_at`：`null` 或已过 → 立即试一次（标"重启重试"）；未到 → 等 | 尝试前先推进 `next_retry_at`；失败则 `failed_attempts += 1` | 至多 1 条 | **绝不因"已过 slot"转 `exhausted`**（它没有 slot）；若转成 `exhausted`，说明实现把 §7.6 第 5 条用错了地方 |
| **T18** | **首次成功（第 k 次重试成功）**（v5 新增） | `push_state = pending`、`first_pushed_at = null` | 写成功状态并**启动时钟②** | `push_state = sent`、`delivered_qq = now`、`failed_reason = null`、`first_pushed_at = now`、`next_retry_at = null`、`resend_state = active`、`resend_count = 0`、`next_resend_at = now+15min` | 1 条 | 进入提醒计划；`failed_attempts` 保留作审计 |
| **T19** | **首次成功后，某次提醒补发发送失败**（v5 新增） | `resend_state = active`、`push_state = sent` | 该 slot **视为已用掉**，不追补 | `resend_count += 1`、`reminder_failed_count += 1`；`push_state` **仍 `sent`**；`failed_reason` **仍 `null`** | 本次没发出去，下一个 slot 照常 | 3 次全失败 → `exhausted`（**不是** `failed_final`）；PENDING 写"3 次提醒均未送达" |

### 手工演算示例（Codex 可按此逐条验）

```
2026-10-21 23:14:05  来世说"……我不想撑了……"
  fp = sha256("crisis\x00miruku:FriendMessage:10000001\x00" + normalize(text))
  glob → 无 → 新建 #1
  events/<fp>__20261021T231405a3f1.json    ack_state=unacked   resend_state=active
  推送 1 条

23:29 / 23:44 / 23:59   补发 3 次（resend_count 1→2→3）
00:00                   resend_state = exhausted    ← 但 ack_state 仍是 unacked
                        PENDING 顶部："已停止自动提醒（未确认）1 条"

2026-10-22 05:30:12   同一句话再次出现
  fp 相同；latest.ack_state = unacked；间隔 6h16m ≥ 6h
  → 新建 #2（不是覆盖 #1！）
  events/<fp>__20261022T0530127b2e.json
  #1 与 #2 两个文件同时存在，各自独立状态

2026-10-22 05:35  OTTO 执行 alert_ack.py --event <#2>
  #2 → acked / stopped_by_ack
  #1 → 仍是 unacked，继续留在 PENDING     ← 关键：ack 一个不等于 ack 全部

2026-10-22 05:40  同一句话第三次出现
  latest = #2 已 acked → 一定新建 #3
  但距 #2 推送仅 5 分钟 → 受 §8.3 节流，push_due_at = 06:05
  → 延后但不丢，PENDING 立刻显示"待推送 06:05"
```

**第二条演算链（v4 新增）：B 档发送失败与限流抑制不能共用计数**

```
2026-10-22 06:12  来世说了句低落的话 → B 档命中
  当天 B 已推 2 条，未超 4 条上限
  events/<fp>__20261022T061200c9d1.json    push_state = pending
  尝试推送 → NapCat 已断 → send_private_msg 未成功
  push_state         = failed_final          ← 不是 pending，也不是 suppressed
  delivery.delivered_qq = null
  delivery.failed_reason = "transport"
  suppressed_push_count 保持 0               ← 关键：本次不增加
  resend_state = none（B 档本来就不补发）
  PENDING：「B 档发送失败（QQ 未接受），按已拍板规则不补发」

06:40  重启 AstrBot
  扫到 push_state = failed_final → 直接跳过，即使 push_due_at 已过
  → 不推送、不改字段、不计入任何次数

07:05  当天第 5 条 B 档
  B 计数已达 4 → push_state = suppressed
  suppressed_push_count = 1
  下一条真实推送的搭车行：「今日另有 1 条 B 档因限流未推送」
  ← 只写 1，不含 06:12 那条失败；那条只在 PENDING 的第二行里
```

> **这条链要验的就一件事**：06:12 那次失败，会不会在 07:05 之后变成"2 条因限流未推送"。会，就是 C-11 没修。**演算可以直接比对两个数字：`suppressed_push_count` 必须是 1，不是 2。**

**第三条演算链（v5 新增，Codex 指定必验）：首次失败 → 重启 → 仍失败 → 首次成功 → 三次补发**

```
2026-10-21 23:14:05  来世说"……我不想撑了……" → A 档，新建 #1
  push_state = pending     first_pushed_at = null      resend_state = none
  resend_count = 0         transport_retry = {failed_attempts: 0, next_retry_at: null}

23:14:07  第 1 次尝试
  规则 4：先写盘 next_retry_at = 23:15:07（+60s），再 send_private_msg
  → NapCat 已断，未成功
  failed_attempts = 1，failed_reason = "transport"，delivered_qq = null
  ← 关键：resend_count 仍是 0；没有 15 分钟 slot 被创建

23:15:07  第 2 次尝试 → 仍失败 → next_retry_at = 23:18:07（+180s），failed_attempts = 2

23:18:07  第 3 次尝试 → 仍失败 → next_retry_at = 23:28:07（+600s），failed_attempts = 3

23:21  OTTO 重启 AstrBot（NapCat 还没起来）
  扫到：pending / first_pushed_at = null / next_retry_at = 23:28:07
  §7.6 第 5 条的前置条件不成立 → 不进 slot 分支
  §7.9 重启表：now < next_retry_at → 等到点（不得提前）
  ← 若这里写成"已过 slot 转 exhausted"，事件就永久死了

23:28:07  第 4 次尝试 → 仍失败 → next_retry_at = 23:58:07（+1800s），failed_attempts = 4

23:40  NapCat 恢复 RUNNING
  规则 7（通道恢复可提前）：忽略 next_retry_at，立刻试一次，正文标「通道恢复补发」
  → 成功
  push_state = sent        delivered_qq = 23:40:12
  first_pushed_at = 23:40:12     last_pushed_at = 23:40:12
  failed_reason = null     next_retry_at = null
  resend_state = active    resend_count = 0
  next_resend_at = 23:55:12（+15min）
  failed_attempts 保留 4（审计用，不再参与任何判断）

23:55:12  补发 #1 → 成功（正文标"补发 1/3"），resend_count = 1，next_resend_at = 00:10:12
00:10:12  补发 #2 → 成功，resend_count = 2
00:25:12  补发 #3 → 成功，resend_count = 3 → resend_state = exhausted
          ack_state 仍是 unacked → PENDING 顶部「已停止自动提醒（未确认）」
```

**这条链要验的是三个数字，任一不对就说明两个时钟被混成一个**：

| 检查点 | 正确值 | 常见错误值 |
|---|---|---|
| 23:14–23:40 期间 `resend_count` | **0** | 4（把每次重试当补发，之后 3 个 slot 直接作废） |
| 首次成功后 `next_resend_at` | **`first_pushed_at + 15min`** = 23:55:12 | 23:29（用 `occurred_at` 算，一推送就立刻触发补发） |
| 重启后（23:21）的状态 | `pending` + `resend_state = none` | `exhausted`（把 §7.6 第 5 条用在没有 slot 的事件上，告警永久静默） |

> **一句话**：**第一次成功之前，"重试"不是"补发"。** 把两者写成一件事，就会出现"通道断 2 小时后恢复，
> 但系统认为 3 次提醒已经用完了"——OTTO 只收到 1 条，系统却报告"已补发 3 次"。

---

## 八之三、B 档限流：需要 OTTO 拍板的一点（不代拍板）

**B 超限后要不要一条次日汇总？**

- **现状默认（我的建议）：不要。** 零额外推送，靠 §8.2 的搭车行让你知道。
  代价：若当天既没有 A、也没有未超限的 B，你就完全不知道当天还有 N 条 B 被压掉了。
- **若你希望"至少每天知道一次 B 有多少"**：授权一条固定时间的汇总。
  代价是**多一次固定打扰**，而这条汇总本身很容易变成你开始忽略的那条消息——
  一条每天准时到、内容永远是"N 条 B"的通知，比没有更危险。

（这是价值判断，不是技术判断，所以我不替你选。你若选汇总，我在规范里改一条固定时刻，
并写清"汇总不计入 B 额度、但计入打扰次数"。）

---

## 九、告警内容模板（已修歧义：即时回复 vs 后续主动确认）

### 9.0 先分清两层（WB-03 第 6 项的核心）

同一件危机里，Miruku 有两次说话机会，**必须分开描述，否则 OTTO 会以为已经问过了**：

| 层 | 时机 | 内容 | 依据 |
|---|---|---|---|
| **即时层** | 对方刚说完，当前对话内 | 按 `system.txt` L21 立刻回应（「你现在安全吗？」+ 视情况三步行动） | 普通对话回复 |
| **后续层** | 3–6 小时后，主动消息 | 只发「你现在安全吗？」**一次**；`crisis_hold` 72h；`ask_sent` 持久化 | `documented in post-crisis-outreach.md` |

**两层互斥规则（v3 改为单一计数器，对应 WB-03R 第 4 项）**

v2 用 `inline_asked` 布尔 + 三条文字规则，读起来仍有歧义（`post-crisis-outreach.md` 里
"对方不回复不重发"与"补问一次"像两条打架的规则）。v3 改为**一个计数器、两个固定槽位**：

| 字段 | 含义 | 上限 |
|---|---|---|
| `safety_ask_count` | 本次危机 episode 内「你现在安全吗？」**已被说过**的次数 | **2** |
| 槽位 #1 | 即时层（对方刚说完、当前对话内） | — |
| 槽位 #2 | 后续层（下一条主动消息） | — |

- 槽位 #1 用掉、对方**有回应**（无论答什么，含"没事"）→ 槽位 #2 **作废**，`safety_ask_count` 停在 1。
  72h hold 仍生效（不发轻话题），但只允许 B 档式关怀一句或不发。
- 槽位 #1 用掉、对方**没回应** → 槽位 #2 补问一次，`safety_ask_count = 2` → **此后永不再问**。
- 槽位 #1 **没用掉**（离线期间到达、当时无对话窗口）→ 槽位 #2 问一次，`safety_ask_count = 1` → 此后永不再问。
- **不存在槽位 #3。** 无论组合如何，"你现在安全吗"在同一 episode 内最多 2 次。

> **这属于 OTTO 已授权的后续主动确认**：OTTO 于 2026-10-21 拍板"A 档必须发，且只发
> 「你现在安全吗？」一句"。槽位 #2 就是那一次，**不是**在授权范围外新增第二次。
> 这两条曾经看起来矛盾的规则，本质是同一件事的两面——"补问一次"就是那唯一一次补问，
> "不重发"指的是**补问之后再无第三次**。之前没写清次数归属，才读着像打架。

**Episode 的边界（必须写清，否则与"最多 2 次"冲突）**：
若对方对 #2 的回应显示**仍有危险**（"还是想""有时候会想"），走 `system.txt` L21 的三步行动
（其中含"再确认一次"）。这构成**新的 episode**，`safety_ask_count` 归零重算。
理由：那是"风险仍在持续"的新信息，不是对同一句话的重复确认；若不允许重算，
三步行动里要求的"再确认一次"就永远发不出去。

### 9.1 A 档模板

```
【系统告警 · 非 Miruku】A 档 · 2026-10-21 23:14 · 通报 <occurrence_id 后 12 位>

触发：来世 说了一句涉及自伤的话（原文已删减，请到 QQ 查看完整上下文）
"……我不想撑了……"

Miruku 这边：
· 即时回复：已在对话里问过「你现在安全吗？」（23:12）
· 后续主动：若他还没回应，会在明早 08:xx 前后补问一次；已回应则不再问

建议你先做的：
1. 现在打开这段对话看一眼
2. 如果你觉得可以，直接联系他

确认已看到：python alert_ack.py --event <occurrence_id>
（不确认会每 15 分钟再提醒一次，最多 3 次；3 次后停止自动提醒，但仍留在 PENDING 里等确认）

（今日另有 N 条 B 档因限流未推送 —— 仅当 N>0 时出现，见 §8.2）
（另有 N 条未确认告警 —— 仅当存在历史未确认事件时出现，见 §7.6）
```

### 9.2 B 档模板

```
【系统告警 · 非 Miruku】B 档 · 2026-10-21 22:40 · 通报 <occurrence_id 后 12 位>

触发：来世 表达自我否定 / 疲惫（原文已删减）
"[自我否定类表达]"

Miruku 这边：下一条主动消息会改为关怀确认（「你还好吗」等一句，不叠加）

不必现在做什么。看到了就行。
（本条只发这一次，不会重复提醒）
```

### 9.3 模板的四条硬要求

1. **`【系统告警 · 非 Miruku】` 前缀不可省。** 否则 OTTO 半睡时会把它当成 Miruku 在说话，
   甚至误以为"Miruku 已经处理好了"从而不去看。
2. **必须写清"即时层 / 后续层各做了什么"**，否则 OTTO 会重复处置（自己也发一条，和 Miruku 撞车）。
3. **必须写明"原文已删减"** 并给 **≤30 字**片段。给太少无法判断，给全文则是把私密对话复制进通知。
4. **B 档模板不许出现"确认"那一行**——要求确认就等于把它当 A 档用，会迅速消耗 OTTO 对告警的敏感度。

---

## 十、观察统计隔离（保持，并加强）

告警是"机器人发给 OTTO"的出站消息。若被观察插件记录，会污染度量：

- "bot 出站条数"虚高；
- `reply_state.last_bot_at` 被 OTTO 会话覆盖 → **来世的首次回复间隔算错**。

**要求**：告警发送必须被观察插件**显式排除**（消息 metadata 标记 `metadata.alert = true`，
或按 `occurrence_id` 识别），**不能靠"内容看起来像系统消息"来判断**。
验收：发一条告警后，来世会话的 `message_count / reply_state / last_bot_at` **三个都不许变**。

---

## 十一、文件布局

```
data/alerts/
  events/<occurrence_id>.json   # 每次发生一个文件 = 唯一真相来源
                                # 命名 = <fingerprint>__<YYYYMMDDTHHMMSS><rand4>
  alerts.jsonl                  # append-only 全量流水（审计用，不承担状态）
  outbox/                       # 待推送队列（`push_state = pending` 的事件引用）
                                # v4：`failed_final` 与 `suppressed` 的事件**必须移出 outbox**，
                                # 否则调度器会反复拾取；事件文件本身不删（留 PENDING 与审计）
                                # v5：outbox 里的 pending A 事件分两种——`first_pushed_at = null` 的由
                                # §7.9 时钟①（`next_retry_at`）驱动，`≠ null` 的由 `next_resend_at` 驱动。
                                # **取件时先判 `first_pushed_at`**，不许只按"时间到了"就发。
  PENDING.md                    # 人可读的未确认/未送达提示（含"目标校验失败""已停止自动提醒（未确认）"）
  .lock                         # 单实例锁
alert.py                        # 置位入口（算指纹 → 判窗口 → 生成 occurrence → L1 → 入 outbox）
alert_ack.py                    # 确认入口（--event <occurrence_id> / --all）
alert_status.py                 # 只读：列出所有 unacked 事件（含 exhausted 的），供人核对
```

`alert.py` 的职责：算 `fingerprint` → 按 §7.3 判窗口 → 生成/复用 `occurrence_id` → 写事件文件
→ L1 弹窗 + PENDING → 入 outbox。
**不做任何判断，不自己猜"这算不算危机"——判断权在调用它的人。**

`alerts.jsonl` 保留期：**90 天**（含片段），到期后该行的 `excerpt` 清空、只保留
`occurrence_id + fingerprint + mode + 时间 + 递送/ack 状态`。
理由：片段是隐私，状态是审计依据，两者保留期不同。
**清理流水不得删除 `events/` 下的文件**——文件是状态真相来源，流水只是审计副本。

---

## 十二、验收清单（27 项，覆盖 WB-03R 的 7 个反例 + WB-03 的 8 个失败场景 + v4 的 2 条失败终态 + v5 的 4 条首次/提醒失败）

| # | 场景 | 合格标准 |
|---|---|---|
| 1 | 手动置位 A 档 | 事件文件生成；`recorded`/`notified_local`/`delivered_qq` 三档都有时间；QQ 收到带前缀告警 |
| 2 | 手动置位 B 档 | 同上，措辞为 B 档模板，**且无「确认」行** |
| 3 | **错目标（把 TARGET 改成 10000002）** | **拒发**；`PENDING.md` 写"目标校验失败"；本机弹窗提示"未能发送"；事件不删、不重试 |
| 4 | **错目标（改成来世以外的第三人）** | 同上（四重校验任何一项不过都要拒发） |
| 5 | 会话 ID 拼接缺失 | 拒发，原因写明"umo 不完整" |
| 6 | **QQ 掉线时置位** | 停在 `notified_local`；`PENDING.md` 明确"QQ 未送达"；通道恢复后**立即**补试一次（§7.9 规则 7，标"通道恢复补发"），状态推进到 `delivered_qq`；**此时 `resend_count` 必须仍是 0** |
| 7 | **AstrBot 完全停掉时置位** | L1 弹窗仍出现；事件文件在；AstrBot 起来后启动补扫并补发 |
| 8 | **同日两次内容不同的 A 事件** | **两个 `events/` 文件**，各自 `seen_count = 1`，两条独立告警，互不覆盖（T4） |
| 9 | **同一句话 6 小时内重复（未 ack）** | 只发一条；`seen_count` 增加；**不新建文件**（T1） |
| 10 | **同一句话 6 小时后重复（未 ack）** | **新建第二个文件**，旧文件**仍在**、字段未被改动；`#1` 若仍 unacked 则继续留在 PENDING（T2） |
| 11 | **已 ack 后同一句话再来** | **新建 occurrence 并推送**（不得因"确认过"而静默）；距上次推送 < 30min 时**延后不丢**（T3） |
| 12 | **ack 一不影响另一个** | ack `#2` 之后，`#1` 仍是 `unacked`，仍在 PENDING（这是"ack 粒度 = occurrence"的验法） |
| 13 | **45 分钟后仍未 ack** | 3 次补发后 `resend_state = exhausted`，`ack_state` **仍是 `unacked`**；PENDING 显示「已停止自动提醒（未确认）」；`acked_at` **必须仍为 null**（T5） |
| 14 | **重启（未到补发点）** | 继续等，不立即发（T6a） |
| 15 | **重启（已过补发点）** | 补发一次并推进 slot，正文标"重启补发"（T6b） |
| 16 | **重启（已过全部 slot）** | 转 `exhausted`，**不补 3 次、不假装补过**（T6c） |
| 17 | **B 档占满 4 条额度后再来 A 档** | **A 档照常立即发送**（B 的用量不影响 A） |
| 18 | **B 档第 5 条** | 不推送、**不发任何汇总**；`suppressed_push_count` 增加；下一条真实推送的尾部出现搭车行（T7） |
| 19 | **电脑休眠跨夜后开机** | 启动补扫生成"延迟告警"，正文首行标注离线时长；与重启补发不重复（T10） |
| 20 | **观察统计不污染 + 上下文隔离** | 来世会话三个统计字段不变；在该会话问 Miruku"刚才有人发消息吗"，**不许**提到告警内容 |
| 21 | **指纹碰撞 / 输入不一致** | 同指纹但 `text_len` 不同 → 新建 occurrence + `alerts.jsonl` 记 `fingerprint_conflict` + PENDING 提示（T12） |
| 22 | **B 档推送时 QQ 不通**（v4 / C-11） | `push_state = failed_final`、`delivery.failed_reason = "transport"`、`delivered_qq = null`；**`suppressed_push_count` 不变**；**重启后不补发**（即使 `push_due_at` 已过）；PENDING 写"发送失败，按规则不补发" |
| 23 | **同日 4 成功 + 2 失败 + 1 限流**（v4 / T15） | 搭车行写「今日另有 **1** 条 B 档因限流未推送」；PENDING **分两行**（1 条限流 / 2 条失败）。**写成 3 或 2 即 C-11 未修** |
| 24 | **A 档首次发送失败**（v5 / T16） | `push_state = pending`、`first_pushed_at = null`、`resend_state = none`、`failed_reason = "transport"`、`failed_attempts = 1`、**`resend_count = 0`**；`next_retry_at ≈ now + 60s`；**不得**出现 `next_resend_at` |
| 25 | **上述事件被重启**（v5 / T17） | 若 `now < next_retry_at` → **不立即发**（等）；若已过期 → 试一次并标"重启重试"；**`resend_state` 必须仍为 `none`、`first_pushed_at` 必须仍为 `null`**；**不得转 `exhausted`** |
| 26 | **首次成功 → 启动三次补发**（v5 / T18） | `first_pushed_at = delivered_qq 时间`、`resend_state = active`、`next_resend_at = first_pushed_at + 15min`（**不是 `occurred_at + 15min`**）；`failed_reason` 清为 `null`；`transport_retry.next_retry_at = null`；`failed_attempts` 保留原值 |
| 27 | **提醒补发中途发送失败**（v5 / T19） | 该 slot 消耗、不追补；`reminder_failed_count` 增加；`push_state` **仍 `sent`**、`failed_reason` **仍 `null`**；3 次全失败 → `exhausted`（**不是 `failed_final`**）；PENDING 写"3 次提醒均未送达"，不得只写"已停止自动提醒" |

**四项回归**：

- `alert_ack.py` 连跑两次 → 第二次不报错、不产生副作用。
- 同时起两个 alerter → 第二个直接退出，只发一条（T11）。
- 把 `DEDUP_WINDOW` 调成 0 → 同一句话两次必须两个文件两条告警（验证窗口参数真的生效，而不是被硬编码吞掉）。
- 把手动置位的事件文件里 `ack_state` 改成 `"acked"` 但 `acked_at` 为 null → 启动时**必须判为损坏并拒绝加载**，
  不允许"字段不一致时猜一个"。

---

## 十三、决策状态

### OTTO 已拍板（不改）

1. 危机事件**必须**告警到 OTTO 本人。
2. **B 档也发**，降级为「发一次、不补发、不写待补发、不确认」。
2a. **B 档独立限 4 条/滚动 24 小时**；第 5 条起只记录并计数，不发 QQ 告警，A 档不受影响。OTTO 于 2026-10-21 明确允许这一取舍；不含授权次日汇总。
3. **L3 webhook 先不配**，v1 不实现。
4. A 档后续主动确认只发「你现在安全吗？」一句；`crisis_hold` 72h；`ask_sent` 持久化。
5. 上一条的**次数归属**已明确为 `safety_ask_count ≤ 2`（槽位固定，无第三次），
   且"补问一次"就在这次授权之内，不构成授权扩张。

### 仍需 OTTO 定（单列，不代拍板）

1. **B 超限后要不要一条次日汇总？** 见 §八之三。
   - 现状默认：**不要**（零额外推送，靠搭车行）。
   - 若选"要"，我加一条固定时刻；代价是多一次固定打扰、且易被忽略。
2. **是否改用独立 QQ 号接收告警。** 现状用 OTTO 私聊 = 同一个会话既是测试又是告警箱，
   需要额外做上下文隔离，且测试历史与告警混在一起。
   - 用独立号的代价：加一次好友、配置一行常量；收益：彻底隔离，§5.3 整节风险消失。
   - **我的建议：v1 先按现状做隔离，等告警真的开始用之后再决定是否升级**——不值得为了一个还没跑起来的链路先加一个号。
3. **（v4 新增）告警链路故障要不要在 QQ 里告诉你。** 现状默认：**不**——只看 `PENDING.md` 与日志。
   - 背景：B 档那一条发不出去时，事件进 `failed_final`，文件里留痕，但 QQ 里你什么都看不到。若当晚没有任何 A 档或未超限的 B 档，**你就不知道告警链路断过**。
   - 可选项：在**下一条本来就要发的**推送尾部加一行（沿用 §8.2 搭车手法，不新增推送次数）。代价是一行字；收益是"链路故障不再静默"。
   - **这不在我的授权范围内**——它虽然不是新推送，但确实是一条你从未同意的信息。当前默认保守执行：**只写文件**。

### v4 的边界（不涉及任何已拍板项）

v4 只补 `push_state` 的失败终态与计数口径，**不改**：B 档 4 条/24h、A 档不设上限、A 档 3 次补发（15/30/45）、
B 档「发一次、不补发、不确认」、`safety_ask_count ≤ 2`、`crisis_hold` 72h、L3 webhook 不实现。
**它是把已有规则在"那一发失败"这一格上写清楚，不是加新规则。**

### v5 的边界（同上，只补"首次失败"这一格）

v5 只做三件事：① 把"首次成功前的传输重试"从"三次提醒补发"里拆出来（§7.9），给出退避阶梯与封顶；
② 新增 `transport_retry` 与 `reminder_failed_count` 两个字段，并补两条判损坏；
③ 更正 `failed_final` 的措辞（不预设"尝试过"）。

**不改任何已拍板项**：B 档 4 条/24h、A 档不设总量上限、**A 档仍是 3 次提醒（15/30/45）**、
B 档「发一次、不补发、不确认」、`safety_ask_count ≤ 2`、`crisis_hold` 72h、L3 不实现。

**新增的"1 小时封顶"是工程参数，不是新的打扰预算**：它只控制"QQ 不通时多久再试一次"，
试的对象是**同一条已经存在的告警**，不产生新消息、不影响来世侧、不改变 OTTO 会收到的条数上限。
**唯一的用户可见变化是**：以前"通道恢复前所有重试都可能白跑"，现在通道一恢复就会立刻补上一次。

---

## 十四、给 Codex 的交接摘要

| 优先级 | 事项 |
|---|---|
| P0 | **两个 ID 分离**：`fingerprint`（64 位全量 sha256，判"是否同一句话"）与 `occurrence_id`（判"哪一次"）。文件名、ack 目标、队列键一律用 `occurrence_id`；窗口判断、ack 后重现、启动补扫去重一律用 `fingerprint`。 |
| P0 | **`occurrence_id = f"{fingerprint}__{occurred_at:%Y%m%dT%H%M%S}{rand4}"`**，落盘前查重；不用自增序号（序号会撞，撞了就是覆盖）。 |
| P0 | **`ack_state` 与 `resend_state` 正交**：`acked` 只能由 `alert_ack.py` 写；`exhausted` 只表示"停止自动提醒"，不表示"已确认"；`ack_state = unacked` 永久留在 PENDING（§7.6）。 |
| P0 | **递送三档 + ack 分开存**：`delivery.{recorded,notified_local,delivered_qq}` + 独立 `ack_state`，禁止合并成布尔值。 |
| P0 | **四重目标校验 + fail-closed**：平台/会话类型/收件人/完整 umo，任一不符 → 拒发 + `PENDING.md` + 本机提示 + 不重试。 |
| P0 | **上下文隔离**：告警不进 `platform_message_history`（或打标后构建上下文时过滤）。验收第 20 条。 |
| P0 | **A 不设总量上限、B 限 4 条**，两者独立计数；B 超限**只计数不推送、不发汇总**；同指纹 30 分钟节流是**延后不是丢弃**。 |
| P0 | **`push_state` 必须有失败终态 `failed_final`**（v4 / C-11）：B 档那一发失败后，塞 `pending` 会变成无限重试（违反"不补发"）、塞 `suppressed` 会污染限流归因。`failed_final` 是**终态**，调度器扫到必须跳过，`push_due_at` 到期也不发；`suppressed_push_count` **只数 `suppressed`**。验收第 22、23 条。 |
| P0 | 告警**豁免 `quiet_hours`**，且**排除在观察插件统计外**。 |
| P0 | **单实例锁**，防双份告警。 |
| P0 | **两个时钟必须分开实现**（v5 / §7.9）：入口只判 `first_pushed_at`——为 `null` 走**传输重试**（`transport_retry.next_retry_at`，退避 60s→180s→600s→1800s→**3600s 封顶**，不设总次数上限，`resend_count` 恒为 0）；非 `null` 走**三次提醒补发**（+15/+30/+45）。**首次成功那一刻才写 `first_pushed_at` 并把 `resend_state` 从 `none` 置 `active`**。验收第 24–26 条。 |
| P0 | **每次尝试前先把 `next_retry_at` 推进到未来并落盘，再发**（§7.9 规则 4）。这一步是防"崩溃 → 重启 → 判定逾期 → 再发"循环的唯一措施；漏掉它，NapCat 断线期间会变成按秒重置的狂发。 |
| P0 | **`first_pushed_at = null` 时不得进 §7.6 第 5 条任何分支**，尤其**不得**因"已过最后一个 slot"转 `exhausted`——没有 slot 的事件不存在"过期"。转错一次，这条 A 档告警就永久静默。验收第 25 条。 |
| P1 | **`reminder_failed_count`**：首次成功后补发失败的次数（0–3）。失败即消耗 slot、不追补；3 次全失败 → `exhausted`（**不是 `failed_final`**），PENDING 写"3 次提醒均未送达"。**`push_state` 不能因此改成 `pending`**——首条确实送到了。验收第 27 条。 |
| P1 | **通道恢复触发一次补试**：平台状态 非 `RUNNING` → `RUNNING` 时忽略 `next_retry_at` 立刻试一次（标"通道恢复补发"）。**状态源用 `PlatformStatus`（`platform.py` L20–26），但 NapCat 掉线是否驱动它变状态尚未实测**，因此必须同时做兜底：任意发送成功时 flush 一次待重试队列（幂等）；都没有则等阶梯到点，最坏晚 1 小时。 |
| P1 | A 档 **首次成功后**的 15/30/45 分钟提醒补发（`resend_state = active` 时才补）；`alert_ack.py --event/--all`。 |
| P1 | **重启时 `resend_state` 不重置**（§7.6 第 5 条四种分支，尤其"已过全部 slot 直接 exhausted、不补 3 次"）。 |
| P1 | **启动补扫**（离线期间消息 → 延迟告警，先查 `fingerprint` 防与重启补发重复），这是 PC 休眠场景的唯一覆盖手段。 |
| P1 | 与 `post-crisis-outreach.md` 的 `crisis_hold` / `ask_sent` / **`safety_ask_count`** 同源，防"告警了但 Miruku 没进关怀态"或反之。 |
| 不做 | **L3 webhook**（OTTO 已定）；**B 次日汇总**（未授权，见 §八之三）；不自动打电话、不自动通知第三方、不因告警改 `system.txt` 行为。 |
