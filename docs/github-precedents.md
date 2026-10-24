# GitHub 先例与复用边界

## 直接采用

### AstrBotDevs/AstrBot

仓库：[https://github.com/AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot)

采用其 QQ/OneBot 适配、OpenAI 兼容模型、DeepSeek 配置、Persona、插件生命周期、上下文压缩和 WebUI。Miruku 不重写 AstrBot 的消息管线。

### NapNeko/NapCatQQ

仓库：[https://github.com/NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ)

采用其 QQ 协议端和 OneBot v11 图片消息接口。NapCat 只作为外部运行依赖。

### Pancakes-Labs/astrbot_plugin_proactive_chat

仓库：[https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat](https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat)

直接采用其沉默计时、未回复上限、免打扰、持久化任务、上下文感知、分段发送和打字间隔。不要自己重写主动聊天调度器；只在配置不足时补一个很薄的适配层。

## 改造借鉴

### KouriChat/KouriChat

仓库：[https://github.com/KouriChat/KouriChat](https://github.com/KouriChat/KouriChat)

借鉴长期陪伴角色的记忆结构、分段和表情包触发思路，不复制代码，也不替换 AstrBot。

### mem0ai/mem0

仓库：[https://github.com/mem0ai/mem0](https://github.com/mem0ai/mem0)

借鉴事实提取、去重和冲突更新。第一版只实现 SQLite + 摘要 + `profile.json`，不引入完整向量服务。

### langchain-ai/langmem

仓库：[https://github.com/langchain-ai/langmem](https://github.com/langchain-ai/langmem)

借鉴短期上下文与长期记忆分层，不引入完整 LangGraph 工作流。

### shuakami/qq-chat-exporter

仓库：[https://github.com/shuakami/qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter)

借鉴 QQ 历史聊天导出和后续导入流程。原始记录不会直接进入每轮 Prompt。

### promptfoo/promptfoo

仓库：[https://github.com/promptfoo/promptfoo](https://github.com/promptfoo/promptfoo)

借鉴批量 Prompt 评估、自定义断言和红队测试。句号率、问题数量、口头禅和危机模式使用本项目自己的确定性断言。

### NVIDIA/NeMo-Guardrails 与 protectai/llm-guard

仓库：[https://github.com/NVIDIA/NeMo-Guardrails](https://github.com/NVIDIA/NeMo-Guardrails)、[https://github.com/protectai/llm-guard](https://github.com/protectai/llm-guard)

仅借鉴输入输出安全检查和模式分离。中文自伤风险规则、资源提示和隐私边界由本项目自行定义。

