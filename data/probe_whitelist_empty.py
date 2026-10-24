# -*- coding: utf-8 -*-
"""例 A1 的只读替代实现（替代「在运行实例里清空白名单再发消息」）。

为什么要有这个脚本
------------------
v3 原稿的 A1 第 3 步要求把生产实例的 `id_whitelist` 清空，再用测试号发一条消息，
以"亲眼看到全员放行"作为证据。这一步会**短暂把所有来源放开**，与"只服务一个人、
不出岔子"直接冲突。Codex 的复核要求：改成**只读断言或隔离测试配置模拟，绝不在
当前运行实例清空白名单**。

本脚本做两件事，都不触碰运行配置、不发任何消息、不写任何文件：

  A. 静态只读断言：读管线源码，断言"空列表直接 return"这个守卫**出现在**
     `event.stop_event()` 之前。（证明"列表清空＝放行"是代码事实）
  B. 隔离单测：把**真实的** `WhitelistCheckStage.process` 方法，配一个内存里
     构造的 self 和假 event 跑三遍，看它到底停不停事件。
     —— 用的是真源码，不是复制一份来测自己。

参数一律从源码读，不从文档抄。

跑法（必须用实例的 venv）：
  "C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/venv/Scripts/python.exe" \
      data/probe_whitelist_empty.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

INSTANCE = Path(
    r"C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176"
)
SOURCE = INSTANCE / "core/astrbot/core/pipeline/whitelist_check/stage.py"

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------- A. 静态断言
def part_a() -> None:
    print("A. 静态只读断言（只读源码，不改任何配置）")
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()

    def lineno(pattern: str) -> int:
        for i, ln in enumerate(lines, 1):
            if re.search(pattern, ln):
                return i
        return -1

    empty_guard = lineno(r"len\(self\.whitelist\)\s*==\s*0")
    stop_call = lineno(r"event\.stop_event\(\)")
    enable_guard = lineno(r"if not self\.enable_whitelist_check")

    check("找到「空列表」守卫", empty_guard > 0, f"{SOURCE.name}:{empty_guard}")
    check("找到 stop_event 调用", stop_call > 0, f"{SOURCE.name}:{stop_call}")
    check(
        "空列表守卫出现在 stop_event 之前",
        empty_guard > 0 and stop_call > 0 and empty_guard < stop_call,
        f"{empty_guard} < {stop_call}",
    )

    # 守卫必须是无条件 return（不是 return 别的、不是 pass）
    seg = "\n".join(lines[empty_guard - 1 : empty_guard + 2]) if empty_guard > 0 else ""
    check(
        "守卫内是无条件 return（不是 pass / 不是继续检查）",
        bool(re.search(r"len\(self\.whitelist\)\s*==\s*0\s*:[\s\S]{0,200}?\breturn\b", seg)),
        seg.replace("\n", " ")[:80],
    )

    # 总开关优先级：enable 为 false 时也直接 return（与"空列表放行"是两条不同原因）
    check(
        "总开关 enable=False 也是直接 return",
        enable_guard > 0 and enable_guard < empty_guard,
        f"{enable_guard} < {empty_guard}",
    )


# ------------------------------------------------------------ B. 隔离单测
class FakeEvent:
    """假事件：只实现 process() 会碰到的那几个方法。"""

    def __init__(self, origin: str = "test:friend:FakeSender", group: str = ""):
        self.unified_msg_origin = origin
        self.role = "member"
        self._group = group
        self.stopped = False

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_message_type(self):
        class _T:
            value = "FriendMessage"

        return _T()

    def get_group_id(self) -> str:
        return self._group

    def stop_event(self) -> None:
        self.stopped = True


class FakeSelf:
    """假 self：字段名与 initialize() 里赋的一模一样，值由用例给。"""

    def __init__(self, whitelist, enable=True):
        self.enable_whitelist_check = enable
        self.whitelist = list(whitelist)
        self.wl_log = True
        # 两个 admin 豁免都关掉，避免干扰判断（实例实测两者均为 false）
        self.wl_ignore_admin_on_group = False
        self.wl_ignore_admin_on_friend = False


def load_real_process():
    """从实例 core 导入真实的 Stage 类，返回未绑定的 process 方法。"""
    sys.path.insert(0, str(INSTANCE / "core"))
    from astrbot.core.pipeline.whitelist_check.stage import (  # noqa: E402
        WhitelistCheckStage,
    )

    return WhitelistCheckStage.process


async def part_b() -> None:
    print("\nB. 隔离单测（真 process 方法 + 内存假对象；不读运行配置、不改实例）")
    process = load_real_process()
    ME = "test:friend:FakeSender"

    async def run(whitelist, enable, origin=ME):
        ev = FakeEvent(origin=origin)
        res = process(FakeSelf(whitelist, enable), ev)
        # process 是 async 函数，返回 None（或 async generator）；两者都不需要 await
        if hasattr(res, "__aiter__"):
            async for _ in res:
                pass
        elif res is not None and asyncio.iscoroutine(res):
            await res
        return ev

    # ① 空列表 → 不拦（这就是"坑"本身的证据）
    ev = await run([], True)
    check("空列表 + 列表外来源 → 放行（stop_event 未被调用）", ev.stopped is False)

    # ② 列表只剩一项（来世），测试号在列表外 → 拦
    ev = await run(["来世"], True)
    check("列表只剩一项 + 来源不在表内 → 拦截", ev.stopped is True)

    # ③ 多项正常态（来世 + 别人），测试号在列表外 → 拦
    ev = await run(["来世", "另一个人"], True)
    check("多项正常态 + 来源不在表内 → 拦截", ev.stopped is True)

    # ④ 多项列表且包含该来源 → 放行
    ev = await run(["来世", ME], True)
    check("多项列表含该来源 → 放行", ev.stopped is False)

    # ⑤ 总开关关闭 → 一律放行（与列表内容无关）
    ev = await run([], False)
    check("总开关 enable=false → 放行", ev.stopped is False)

    # 结论：①② 的差异**只**由"列表现有几项"决定，与"谁在列表里"无关。
    # 所以"把来世移出"（剩 0 项）和"把来世之外的人移出"（剩 1 项）方向完全相反。


def main() -> int:
    print(f"源文件：{SOURCE}")
    if not SOURCE.exists():
        print("找不到管线源码，中止。")
        return 2
    part_a()
    asyncio.run(part_b())
    print(f"\n合计 {PASS + FAIL} 项：PASS {PASS} / FAIL {FAIL}")
    print("本脚本未读取或修改任何运行配置，未发送任何消息。")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
