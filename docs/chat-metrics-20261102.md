# 聊天质量指标采集（2026-11-02）

用户原话（m09447）：「B，可以先做，做好投放吧」——B 指「更会聊」这个可量化方向，
与「更像她本人」（靠人工体感验收）分开推进。

投放（G10）已在同一窗口完成：来世 10000002 已加入 `friend_settings.session_list`，
首条主动消息排在 2026-11-02 09:29:40。

---

## 一、为什么是「只读采集」而不是「自动优化」

persona 决定它怎么说话，而它又根据对话判断自己说话好不好，然后修改 persona——这是
一个闭环。一旦某次判断有偏差（比如某天它觉得「太正经了该活泼点」），偏差就被写进
persona 固化下来，之后所有对话都带着这个偏差，它再基于偏差继续调整。一周后没人能说清
它为什么变成那样。

已有硬教训：**persona 有三份来源互不相同**——DB 的 `personas` 表才是生效源
（3524 字，sha `6ad06070cb80aae7`），`/opt/miruku/astrbot/data/laishi/system.txt`
是 3803 字，仓库 `prompts/system.txt` 是 3926 字。改错地方完全不会生效。在这个基础上
加自动驾驶，等于给一个自己不认路的系统加速。

所以分工是：**机器只记录，人做判断，改 persona 必须人工确认并走 `server/deploy-persona.py`。**

## 二、采集什么

插件 `astrbot_plugin_miruku_metrics`（v0.1.0），只读实现：不改 persona、不拦截发送、
不改写回复文本、不主动发消息（这四条由探针做源码静态断言把关）。

每次私聊后读本地 DB 的会话内容，算七项指标：

| 指标 | 含义 | 怎么用 |
|---|---|---|
| `user_turns` / `bot_turns` | 对方/她各说了几句 | 基础量 |
| `turn_ratio` | 话轮比 = 她/对方 | >1 她话多，<0.5 她冷淡 |
| `max_bot_streak` | 最长连续自说自话次数 | **≥3 = 冷场信号**（连发几句没人接） |
| `proactive_total` / `proactive_replied` | 主动消息条数与被真实回复的条数 | 接话能力 |
| `proactive_reply_rate` | 主动消息被回复率 | **<0.4 = 主动消息时机或内容不对** |
| `user_avg_len` / `bot_avg_len` | 双方平均字数 | 对方突然变短=在敷衍；她太长像客服 |

落盘：`/AstrBot/data/plugin_data/miruku_metrics/metrics.jsonl`（每次一条快照）。

### 三个必须过滤的「假用户发言」

不处理这三类，统计会完全失真（这是实测踩出来的，不是预防性设计）：

1. **工具结果写回 user 轮**——anysearch 的搜索结果会被 AstrBot 以 user 角色写进会话。
   实测第 468 轮是一条 29893 字符的 `## Search Results (6 results, 1417ms)`。
   不剔除时「对方平均字数」从 **28.9 被拉到 2071.3**（差 71 倍）。
   识别标记：`## Search Results (`、`[已截断：`、`` Tool ` ``。
2. **纯图片 / system_reminder**——`[图片]` 占位与时间提醒都不是真话。
3. **早期记录的 Python 字面量字符串**——10-20 的记录 `content` 是
   `"[{'type': 'text', 'text': '晚上好'}]"` 这种单引号字符串，`json.loads` 会失败。
   不兜底则整串原文被当正文。修法：`json.loads` 失败后 `ast.literal_eval`。
   另有 base64 图片（`data:image/jpeg;base64,`）必须正则剥掉。

### 主动消息的识别

主动消息把 prompt 写进 user 轮（`你正在以 Miruku 的身份，在 QQ 私聊中主动发起一条消息。`），
与用户真实发言混在同一条会话里。必须靠这个标记区分，否则「她回了没」的统计全是错的。

另一个坑：**机器人自己回复主动消息 prompt 不算「对方回应」**。初版在 assistant 分支里
也累加 `proactive_with_reply`，导致回复率恒为 100%（探针 5 条用例全部抓到）。

## 三、怎么用

```bash
# 服务器上跑（自动从容器捞数据）
bash /opt/miruku/server/metrics-report.sh              # 最近 7 天
bash /opt/miruku/server/metrics-report.sh --days 3     # 最近 3 天
bash /opt/miruku/server/metrics-report.sh --json       # 机器可读
```

报告直接给判断，不只丢数字：

```
── QQ 10000002 ──
  采样 6 次，最近一次 2026-11-02T09:05:29+08:00，会话共 120 轮
  最近 5 次中位数：
    话轮比（她/对方）              1.1      偏高=她话多；偏低=她冷淡
    最长自说自话                 3        >=3 说明连发几句都没人接，是冷场信号  ← 冷场
    主动消息被回复率               0.3      越高越好；<0.4 说明主动消息时机或内容不对  ← 主动消息接不住
  冷场占比：3/5 次出现连续 3 句以上无人接
```

取最近 5 次的**中位数**而非单次值，避免一次长对话把统计带偏。

## 四、验证

| 项目 | 结果 |
|---|---|
| 探针 `data/probe_metrics.py` | **39/39 ALL PASS** |
| 真实 DB 解析（来世 10000002） | user=58 bot=57 主动=2 回复率=1.0 冷场=2 话轮比=0.98 |
| 真实 DB 解析（测试号 10000001） | user=56 bot=90 主动=33 回复率=0.636 冷场=5 话轮比=1.61 |
| 真实 DB 解析（新好友 10000003） | user=10 bot=10 主动=0 回复率=None 冷场=1 话轮比=1.0 |
| 端到端（假事件触发采集） | jsonl 落盘、字段齐全、未命中 watch_user 不写、20 秒节流生效 |
| 报告脚本 | 假数据渲染正确、空数据不炸、JSON 模式可解析 |
| 重启后 | `[miruku_metrics] armed: enabled=True watch=3 window=200`；两条主动消息排期自动恢复 |

## 五、投放实况（G10）

- 切换前白名单断言通过：`enable_id_white_list=True`，3 项
  `['10000001','10000002','10000003']`，来世在内。
- `friend_settings.session_list` 从 `['...10000001']` 改为
  `['...10000001','...10000002']`，备份
  `astrbot_plugin_proactive_chat_config.json.bak.pilot-20261102-085119`。
- **踩坑**：改完 session_list 后 `/api/jobs` 起初只有测试号 1 条——因为
  `setup_auto_triggers_for_enabled_sessions()` 对 session_list 逐项调
  `setup_auto_trigger_for_session_config()`，新加的会话走的是「auto_trigger 定时检查器
  （after_minutes=60）」，不是真实排期。必须补一次
  `POST /api/jobs/{umo:path}/reschedule` 才会建出 chat job。
- 最终：来世 `next=2026-11-02T09:29:40`、未回复 `0/3`；测试号 `next=09:35:24`、`1/3`。

## 六、每周怎么用

见 docs/chat-metrics-weekly.md：跑一条命令、看五个阈值、什么情况才动 persona。

## 七、遗留

1. **指标只在收到私聊时采集**，所以「她连发 5 条没人理」这种情况要等对方下次说话才会被记录下来。
   对「冷场」的观测是事后视角，不是实时告警。要实时得另做（比如在主动消息发送钩子里也采一次）。
2. **`proactive_reply_rate` 的口径**：现在统计的是「主动消息后，对方在窗口内有过任何真实发言」，
   不区分对方是回应这条主动消息还是另起话题。
3. **`max_bot_streak` 的窗口是最近 200 轮**，长期会话里旧记录会被挤出窗口，适合看趋势不适合做累计。
4. persona 侧的任何改动仍需人工确认（见 §一），本轮**没有**改任何 persona。
