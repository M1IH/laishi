# Miruku QQ AI 陪伴机器人

本项目计划使用 AstrBot + NapCatQQ + DeepSeek，在 Windows 本地运行一个私聊 AI 陪伴机器人。人物形象采用《maimai》系列的 Miruku（みるく/咪璐库），聊天口吻遵循 OTTO 指定的短句、分段和低压力陪伴规则。

当前状态：阶段 0 已在 2026-10-19 完成真实 QQ 验收。Miruku 人格已设为 AstrBot 默认；口吻已用 2025-10 至 2026-10 的 QQ 私聊导出校准。最新提示词在 `prompts/system.txt`，实例重启后可运行 `deploy_miruku.py` 同步。

## 技术底座

- AstrBot：LLM 和消息框架
- NapCatQQ：QQ/OneBot v11 协议端
- 主动消息：运行实例已安装 `astrbot_plugin_proactive_chat` v1.2.6；仅配置本次测试私聊，3–6 小时随机调度、1–8 点免打扰、最多一次未回复后停发
- DeepSeek：OpenAI 兼容模型 API
- SQLite：本地消息、摘要、画像和风险事件

## 目录

- `persona/`：Miruku 人设和口吻
- `profiling/`：画像维度、采集脚本和画像数据
- `prompts/`：系统提示词
- `docs/`：架构、先例和部署记录
- `images/`：当前只有阶段 0 的传输测试 PNG；聊天导出只有图片引用，没有原图
- `data/`：运行时数据库和导出文件

## 当前实例

当前 AstrBot Launcher 实例路径保存在本机 `.env` 的 `ASTRBOT_CORE` 中；换机器或换实例时修改该值，模板见 `.env.example`。环境变量优先于 `.env`。Launcher 会改变 WebUI 本地端口，脚本自动从运行进程定位；也可用 `ASTRBOT_DASHBOARD` 显式指定。缺少有效实例路径时脚本会报错，不会猜测旧实例。

启动实例后，用该实例的 Python 环境运行 `deploy_miruku.py`，可同步 Miruku 人格并设置默认人格、60 轮上下文和关闭自动按标点分段。加 `--probe` 只在 WebUI 本地聊天创建临时会话做口吻检查，不会给 QQ 发消息。脚本从本地配置读取签名密钥并调用 AstrBot API，不打印密钥。

`setup_stage0.py` 安装项目内保存的主动消息插件压缩包，已安装时会跳过；`configure_proactive.py --qq <自己的测试QQ号>` 仅对指定且最近 30 分钟内活跃的私聊配置低打扰的主动消息；`verify_stage0.py --qq <自己的测试QQ号>` 向该私聊发送 `images/stage0-test.png`。主动消息的人格化开场方向记录在 `docs/active-message-ideas.md`；OTTO 选定的 Oshama 示例已作为低频参考写入插件提示词，不是固定发送内容。

最小可观测性插件源码在 `plugins/astrbot_plugin_miruku_observer/`，当前实例已安装。它仅记录指定私聊的消息方向、时间和首次回复间隔，不存正文；模式触发字段目前保持未知。状态与验证边界见 `docs/observability.md`。

## Windows 登录后启动

当前用户登录时，计划任务 `Miruku-AstrBot-AtLogon` 会用 Launcher 实例的 Python 执行 `start_astrbot.py`；`Miruku-AstrBot-Watchdog` 每 5 分钟检查一次进程。`Miruku-NapCat-AtLogon` 用同一 Python 环境执行 `start_napcat.py`，优先复用 QQ 本地登录态。两个入口都避免重复启动自身进程。运行核心无需登录 AstrBot WebUI；WebUI 的账号密码只用于打开管理页面。核心已在运行时，不要再在 Launcher 中点“启动实例”，否则可能出现第二套进程。

NapCat 自动入口将控制台输出写入被忽略的 `logs/`，避免中文混合编码窗口；QQ 若要求重新扫码，会尝试打开本机生成的二维码图片。QQ 的安全验证必须由 OTTO 在手机上完成；二维码失效时可用 `NapCat.Shell.Windows.OneKey/NapCat.52230.Shell/napcat.quick.bat` 交互处理。登录后启动依赖 Windows 用户会话，不保证停在系统登录界面时自动可用。

