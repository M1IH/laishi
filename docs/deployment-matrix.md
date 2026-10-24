# 阶段 0 部署兼容矩阵

更新时间：2026-10-19

| 组件 | 第一版策略 | 当前验证状态 | 需要在本地确认 |
|---|---|---|---|
| Windows | 原生运行 | 已确定 | Python/uv 运行时和权限 |
| AstrBot | Windows Launcher 实例 | 4.29.1 正在运行，WebUI 本地端口动态发现 | 长时间运行稳定性 |
| NapCatQQ | QQ 小号 + OneBot v11 | Shell 实例已登录，反向 WebSocket 已连接 AstrBot `6199` | 重启后的自动登录和重连 |
| proactive_chat | 直接安装插件 | v1.2.6 已安装；测试私聊主动消息到达 QQ，AstrBot 核心重启后任务恢复 | 整机重启后的自动恢复 |
| DeepSeek | OpenAI 兼容 API | 真实 QQ 消息触发模型回复 | 长期限流和费用 |
| SQLite | 本地 WAL 数据库 | AstrBot 自带数据库已记录本次 QQ 会话；Miruku 长期记忆库仍待后续阶段 | 文件路径、备份方式 |
| 图片消息 | 项目 `images/` 目录 | `stage0-test.png` 经 AstrBot IM API 发出，OTTO 确认 QQ 收到 | 表情包素材及选择逻辑 |

## 本机只读检查

- Windows PowerShell：可用
- 系统 Python：3.9.13，不作为 AstrBot 运行时
- `uv`：0.12.1，已安装，可创建 Python 3.12 隔离环境
- Docker CLI：29.7.2，已安装
- Docker 不作为第一版运行路径
- 实际使用 `C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\core`，不是项目根目录中的早期 AstrBot 初始化目录
- 主动聊天插件已通过 WebUI API 安装并热加载

## 阶段 0 的完成条件

1. AstrBot、NapCatQQ 和 `astrbot_plugin_proactive_chat` 的版本可以同时运行
2. QQ 小号能接收和发送一条文字消息
3. DeepSeek 能完成一次 OpenAI 兼容调用
4. 机器人能发送项目目录中的一张图片
5. 主动聊天插件能创建一个私聊沉默任务
6. 日志中不出现 API Key

2026-10-19 验收：1–5 均已观察到。QQ 测试私聊收到文字和图片，机器人对两条消息产生回复；项目 PNG 到达 OTTO 的 QQ；主动消息插件在该私聊持久化了下一次任务。第 6 项检查了当时的 WebUI 日志缓存（216 条）：未含配置中的 DeepSeek Key；AstrBot 文件日志当前关闭。

2026-10-20 续验收：重构后的 `deploy_miruku.py --probe` 在 Launcher 实例 Python 环境运行成功，默认人格仍为 Miruku，提示词一致，自动分段关闭；四类本地探针均收到模型回复。10 月 19 日 23:28 的插件启动日志显示，从持久化文件恢复了 1 个测试私聊任务。该任务于 10 月 20 日 00:08:58 到点执行，插件日志显示 LLM 生成成功、平台发送流程完成，持久化的未回复次数由 0 变为 1；OTTO 随后确认测试 QQ 收到了主动消息。00:11 通过 AstrBot 官方 API 重启核心；00:11:43 的日志显示再次恢复 1 个持久化任务，未回复计数仍为 1，NapCat 与 AstrBot 的 6199 连接重新建立。当前配置为 1–8 点免打扰、未回复最多 1 次；下一次任务被排到 04:16，但按插件准入逻辑会被免打扰或未回复上限拦截。尚未验证 Windows 整机重启后 Launcher 与 NapCat 的自动启动、登录和重连。

2026-10-20 再次只读核对：AstrBot 控制 API 可访问，观察插件和主动消息插件均显示启用；NapCat Shell 与 QQ 进程在运行。Windows 计划任务、系统启动项和当前用户启动文件夹中未找到以 AstrBot、NapCat 或 Miruku 命名的启动项。这项检查不能代替整机重启验收，也不能排除 Launcher 使用其他启动机制；当前不声称自动恢复已配置完成。

2026-10-20 快速登录准备：NapCat Shell 自带 `napcat.quick.bat` 原先使用示例账号 `10086`；已改为本机 NapCat 配置对应的机器人 QQ 账号，并补充切换到脚本目录。随包说明要求该账号至少登录过一次，本机满足此前登录记录。下次请用 `NapCat.52230.Shell/napcat.quick.bat` 启动来验证是否免扫码；当前运行中的 NapCat 未重启，因此此项尚未完成实测。快速登录复用本地 QQ 登录态，不等于 Windows 开机自动启动，也不能保证 QQ 令牌过期或安全验证时永远免扫码。

2026-10-20 快速登录实测：只停止 NapCat Shell 目录内的旧 NapCat 与 QQ 进程，再以当前账号参数启动 `NapCatWinBootMain.exe`；未出现扫码步骤，OneBot 到 AstrBot `6199` 的连接恢复。经 AstrBot IM API 向测试 QQ 发送“Miruku 重连检查”消息，OTTO 确认收件端收到。此项证明当前本地 QQ 登录态可复用，不保证令牌过期后仍免扫码。白名单已设为测试私聊与来世私聊，当前版本阶段逻辑模拟显示其他私聊和群聊被拦截。

2026-10-20 用户登录恢复再验：任务计划程序的 `Miruku-AstrBot-AtLogon` 在 16:10 执行成功，AstrBot 进程同一时间创建，WebUI 和 OneBot 端口可访问；OTTO 确认“开机恢复检查”到达测试 QQ。登录 WebUI 的账号密码仅用于管理界面，不是 AstrBot 核心启动条件。之后手动启动 Launcher 实例又生成一套重复 AstrBot 进程；已清理未占用服务端口的副本，保留正在服务的核心。NapCat 登录任务也拉起 QQ，但快速登录态失效导致暂未连接；OTTO 扫码后 OneBot 恢复。自动启动已改为 `start_napcat.py` 无控制台方式，避免乱码窗口；再次需要新二维码时会尝试打开二维码图片，回退尚待实测。QQ 安全验证不能由脚本保证永久免扫码。

同日后续验收：QQ 曾继续刷新二维码，OTTO 最终完成手机登录；随后 OneBot 与 AstrBot `6199` 建立连接，两个 Miruku 相关插件保持启用，只运行一套 AstrBot 核心。通过 AstrBot IM API 向测试 QQ 发送“Miruku 登录恢复验收”，OTTO 确认收到。当前登录链路恢复，但这次需要人工扫码，不能算无人值守自动恢复。

## 当前不做的事

- 不导入原始 QQ 聊天记录
- 不填写真实危机电话
- 不实现 Miruku 画像提取
- 不实现自定义主动调度器
- 不把 Docker 作为第一版运行方式

