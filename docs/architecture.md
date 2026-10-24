# Miruku 机器人架构

## 目标

在 Windows 本地运行 AstrBot + NapCatQQ，通过 DeepSeek 提供模型能力。Miruku 的人格、主动聊天、画像、记忆和危机兜底保持独立边界，便于测试和替换。

## 运行拓扑

```text
QQ 小号
  |
NapCatQQ / OneBot v11
  |
AstrBot
  |-- DeepSeek OpenAI-compatible API
  |-- astrbot_plugin_proactive_chat
  |-- Miruku custom plugin (后续阶段)
  |-- prompts/system.txt
  |-- data/miruku.sqlite3
  |-- images/
  `-- logs/
```

## 组件边界

| 组件 | 负责 | 不负责 |
|---|---|---|
| NapCatQQ | QQ 登录、收发消息、图片消息 | 人格、记忆、风险判断 |
| AstrBot | 消息管线、模型调用、插件生命周期 | Miruku 的业务规则 |
| proactive_chat | 主动消息调度、沉默计时、免打扰、分段发送 | E/B/C/D 策略和危机处理 |
| Miruku 插件 | 画像、记忆、行为配额、危机规则 | QQ 协议和模型底层 |
| SQLite | 本地消息、摘要、画像、风险事件 | 在线同步和远程查看 |

## Windows 第一版选择

第一版采用 Windows 原生运行 AstrBot + NapCatQQ，不把 AstrBot 放进 Docker。理由是本地调试、查看日志、导入聊天记录和导出 SQLite 更直接。Docker 保留为后续稳定运行或迁移方案，不影响插件代码边界。

## 数据目录约定

```text
data/
  miruku.sqlite3
  exports/
images/
  stickers/
logs/
prompts/
persona/
profiling/
```

`data/`、`images/` 和 `logs/` 不提交到代码仓库。API Key、危机资源和路径只通过 `.env` 或 AstrBot 配置提供。

## 许可证边界

- AstrBot、NapCatQQ 和主动聊天插件作为外部依赖使用
- 不复制 NapCatQQ 内部实现
- 主动聊天调度优先直接使用 `Pancakes-Labs/astrbot_plugin_proactive_chat`
- 若未来公开分发包含该插件的修改版本，必须重新检查 AGPL-3.0 的源代码提供义务

