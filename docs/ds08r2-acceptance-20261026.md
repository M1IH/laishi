# DS-08R2 Codex 验收（2026-10-26）

**结论：通过工具补件验收；C-19 回复质量仍未验收。** 使用 AstrBot Launcher 实例 Python，在未设置 `PYTHONIOENCODING`/`PYTHONUTF8` 的 Windows 环境复跑：自检 48 项退出 0；`check_ds08r_regression.py` 9 例退出 0；`check_ds08r_matrix.py` 10 格退出 0。不带 `--baseline` 的混版和全新版 20 轮样本均返回 `UNVERIFIED_VERSION`/1，带基线且逐轮已确认的全新版正对照返回 `PASS`/0。此前的 `gate_ok=None` 命令行绕过已封住。

直接运行探针时还发现：默认控制台代码页无法编码提示符号，导致打印证据问题时抛 `UnicodeEncodeError`。Codex 已把探针输出显式设为 UTF-8、提示符号改为普通文本，并更新文件头示例的基线与逐轮证据字段；复跑无异常，结论和退出码不变。此为输出修正，不涉及判据或运行实例。

**证据边界**：输入 JSON 的 `bot_time`、`delivered=confirmed` 仍须由取样人拿日志和 QQ 收件端逐轮核对；脚本只能校验字段及时间关系，不能独立证明字段来源真实。数据库模式缺逐轮时间，不能单独给新版验收 `PASS`。现有六轮不足 20 轮；C-19 继续开放，正式投放仍 No-Go。
