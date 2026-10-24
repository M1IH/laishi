# NapCat 手工登录入口（2026-10-24）

## 已验证状态

- **手工入口**：项目根目录 `NapCat 手工登录（独立副本）.lnk`，指向真正独立的 `C:\Users\OTTO\NapCatShell-Recovery\miruku-manual-utf8.cmd`。此目录不是 junction。
- 原始 `napcat.quick.bat - 快捷方式.lnk` 保留，未改。它位于含中文的项目路径，当前启动命令在该路径处截断；不要把它误记为已修复。
- 2026-10-24 重新打开独立副本后生成新二维码；OTTO 手机确认；副本 QQ 与 NapCat 进程保持运行，AstrBot 6199 出现 `Established`，AstrBot 日志 `aiocqhttp_platform_adapter:107` 记录适配器已连接。
- 英文路径的 junction `C:\Users\OTTO\NapCatShell` 不是独立备份；经它启动的 QQ 在 `QQNT.dll` 崩溃（异常 `0x80000003`）。**不要把 junction 当恢复入口**。

## 保护规则

1. `NapCatShell-Recovery` 是**保留的可见手工登录副本**。后续自动启动、升级、配置试验、修复脚本不得以它为目标；需要试验时另建目录。项目的 `start_napcat.py` 遇到该目录的 `.manual-login-reserved` 标记会拒绝启动。
2. 不覆盖、不改名、不删除该副本、`miruku-manual-utf8.cmd` 或项目里的手工快捷方式；脚本已设只读。不要在此目录直接解压新版 NapCat。
3. `Miruku-NapCat-AtLogon` 仍指向原项目 Shell，经核对**没有**指向此独立副本。改自动启动时继续保持隔离。
4. 静态启动文件和当前 NapCat JSON 配置已备份到 `C:\Users\OTTO\NapCatShell-ManualBaseline-20261024`。静态六个文件逐个哈希与副本一致。配置可能含令牌和账号，只在本机保留，排障输出不得打印内容。
5. 以后每次碰 NapCat，先核对手工快捷方式目标、`.manual-login-reserved` 标记、独立副本文件和 6199 连接；变更后再核对一次。若自动方案失败，优先用这个可见入口扫码，**不要在排障中改它**。

## 使用与限制

双击 `NapCat 手工登录（独立副本）.lnk`；若出现新二维码，OTTO 自行扫码并在手机确认。登录成功后核对 AstrBot 6199 已建立连接与适配器日志。QQ 登录凭证仍可能失效，此入口保留人工扫码能力，不保证免扫码或 24 小时持续在线。独立副本与普通 `D:\QQ` 进程可能冲突；排障时应先分辨进程，不要无故结束用户的普通 QQ。
