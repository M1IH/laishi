"""开启 AstrBot 全局分段回复（让 Miruku 的普通回复真的能分两条发出）。

⚠️ 2026-10-22 二次核查：本脚本的前提已被推翻，**优先考虑 API 热改**，见 `WORK_LOG.md`
   「⚑ 全局分段的更正与最优路径待判」。历史上这里写的是"AstrBot 运行中改盘会被内存覆盖，
   所以必须停机"——前半句对（直接写 JSON 会被内存快照覆盖），后半句错：AstrBot 自带
   `PUT /api/v1/system-config`，它会一次做完三件事——原地改内存、落盘、重建 pipeline
   （`config_service.py:548` → `astrbot_config.py:318` → `core_lifecycle.py:475`），
   下一条消息即生效，不需要停机。若 Codex 判定走 API，本脚本可直接删除。

   保留本脚本的唯一理由：作为"停机窗口"方案的可执行备份。

背景：`prompts/system.txt` 一直要求"要补第二件事就另起一条短消息"，但
`cmd_config.json` 里 `platform_settings.segmented_reply.enable` 是 `false`，
这条规则从来没生效过。此外 humanlike 插件会删掉 `。！？；`，所以**标点不能当断点**；
`…` 已在正则字符类里天然可用，**换行 `\\n` 不在**，必须显式加进正则才能切。

用法（必须在 AstrBot 停止时跑，否则会被内存里的旧配置覆盖）：

    <instance venv python> patch_segmented_reply.py          # 打印将要做的改动并写盘
    <instance venv python> patch_segmented_reply.py --dry    # 只看不改

脚本是幂等的：已经是目标状态时什么都不做。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import miruku_client as mc  # noqa: E402

CONFIG = mc.INSTANCE / "data" / "cmd_config.json"
BACKUPS = mc.INSTANCE / "data" / "backups"

# 2026-10-22 实测值：enable=false（本脚本唯一要改的），interval_method 已经是
# "random"、interval 已经是 "1.5,3.5"、log_base=2.6、words_count_threshold=150。
# 上一版把这三项也写进 TARGET，是照着 AstrBot 的出厂默认值抄的，不是实测值——已剔除，
# 只为把改动面压到最小（改一个布尔值 + 一条正则）。
TARGET = {
    "enable": True,
}
REGEX = r".*?[。？！~…\n]+|.+$"


def astrbot_running() -> bool:
    try:
        mc.dashboard_url()
        return True
    except RuntimeError:
        return False


def main() -> int:
    dry = "--dry" in sys.argv

    if astrbot_running() and not dry:
        print("AstrBot 正在运行：改盘会被内存里的旧配置覆盖。")
        print("先停止 Launcher 实例再跑本脚本（或加 --dry 只看改动）。")
        return 2

    raw = CONFIG.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    seg = data["platform_settings"]["segmented_reply"]

    changes = []
    for key, want in TARGET.items():
        if seg.get(key) != want:
            changes.append((f"segmented_reply.{key}", seg.get(key), want))
    if seg.get("regex") != REGEX:
        changes.append(("segmented_reply.regex", seg.get("regex"), REGEX))

    if not changes:
        print("已是目标状态，无需改动。")
        return 0

    print("将要改动：")
    for name, old, new in changes:
        print(f"  {name}\n    旧: {old!r}\n    新: {new!r}")

    if dry:
        print("\n--dry：未写盘。")
        return 0

    # 阈值语义是反的（result_decorate/stage.py:220：len > threshold 就【不】切），
    # 但值本身不用动——150 远大于 Miruku 的回复长度，永远走"切"分支。
    # 这里只做健全性检查，不拿一个抄错的常量去 assert（上一版硬写 80，在真实值 150 上会直接中止）。
    keep = data["platform_settings"]["segmented_reply"].get("words_count_threshold")
    if not isinstance(keep, int) or keep <= 0:
        print(f"words_count_threshold 异常（{keep!r}），中止")
        return 1
    print(f"（words_count_threshold={keep}：超过 {keep} 字符的消息不分段；语义与名字相反，勿凭名字调参）")

    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = BACKUPS / f"cmd_config-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已备份: {backup}")

    seg.update(TARGET)
    seg["regex"] = REGEX
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 回读校验：目标字段已生效，其它关键字段未被改动。
    after = json.loads(CONFIG.read_text(encoding="utf-8-sig"))["platform_settings"]
    got = after["segmented_reply"]
    ok = all(got.get(k) == v for k, v in TARGET.items()) and got.get("regex") == REGEX
    print(f"回读: enable={got.get('enable')} interval_method={got.get('interval_method')} "
          f"interval={got.get('interval')} regex={got.get('regex')!r}")
    print("校验通过" if ok else "校验失败，请用备份回滚")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
