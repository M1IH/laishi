# CX-01 落地记录（Codex，2026-10-25）

## 结果

五项改动已按派单顺序分别提交并部署；**行为验收待测试 QQ 取样**，C-18/C-19/C-20 暂不销账。未向来世发测试消息。

| 顺序 | 改动 | 提交 |
|---|---|---|
| 1 | 日常长度改为跟随对方，情绪与危机留清楚表达例外 | `80ba025` |
| 2 | 知识块前缀要求最相关一条、一两句话说完 | `65c78d1` |
| 3 | 被调侃贬低时不自我否定，也不攻击对方 | `db1c248` |
| 4 | 轻度低落可先换话题；明确自我否定、关系愧疚先接住 | `16e3406`；消除“疲惫”歧义 `5eee9e5` |
| 5 | EmotionAI 伪造 assistant 样本去除“星绘/前辈” | `c373649`（补丁记录）；实例文件已改 |

改前 `prompts/system.txt` 原始 Windows 文本为 **3343 字符**，SHA-256 `2df7fde57f7c8210…`；换行规范化后为 **3320 字符**，与派单数字相符。运行人格更新前与此版本规范化逐字一致；更新后与现行文件规范化逐字一致，已通过 Dashboard API 回读。知识插件和 EmotionAI 均已热重载，AstrBot 主进程未因本次变更重启。

EmotionAI 原版备份在 `data/backups/cx01-emotionai-20261025/main.py`，实例新文件通过 Launcher Python `py_compile`；其伪造样本现在为中性“当前状态正常。”。全文件搜索旧称呼无命中。原运行人格备份在 `data/backups/cx01-persona-20261025-before.txt`。上述备份在本地忽略目录，不入仓库；`plugins/emotionai-cx01.patch` 是可审阅的最小变更。第三方插件升级后须重施补丁或复核样本。

## 验证

- Launcher 实例 Python：`probe_regression.py` 120/120、`probe_outbound_guard.py` 53+9、`probe_knowledge_adversarial.py` 32/32、`knowledge/lint.py --strict` 严重 0，均退出码 0。
- AstrBot 日志确认两个插件完成 Terminating → Loading；运行人格 API 回读与当前 `system.txt` 一致。
- 只读扫描实例 `data_v4.db` 的 14 个 conversation 记录：含“星绘”或“前辈”的历史记录 0 条。此检查不等于未来输出必然为 0。

## 尚未验收

派单规定的 C-18 三条、C-19 真实输入 20 轮统计、Q12 两类回复，需要在 **OTTO 测试 QQ** 上观察实际气泡；目前只有规则和离线探针验证。测试时记录回复长度与是否问句收尾，避开来世私聊。T1 同题问卷至少等变更后 3–5 天稳定对话再做。

另外 `docs/miruku-style-from-otto-tone.md` 是 DeepSeek 同时交来的另一个风格提案，含待 OTTO 决定的冲突项；本次 CX-01 未纳入，也未改 `persona/`。
