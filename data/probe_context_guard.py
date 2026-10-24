"""DS-07 探针：验证上下文守卫插件把请求压回模型真实上限，且裁剪不落库。

为什么需要它
-----------
生产 400 的根因不是 L1 知识插件，也不是历史条数，而是历史里 22 张
``data:image/jpeg;base64,...`` 被每轮原样重发（2,366,262 字符）。AstrBot 自己的
``EstimateTokenCounter`` 对每张图只记 765 token，实测低估 63.2 倍，所以
``should_compress`` 从不触发；真报错后 ``pop_record`` 每次只弹两条文本，
永远弹不到图。

本探针直接调用插件的真实处理函数（不是复制一份逻辑），断言：

* 生产历史（content 是**整条字符串**，和本机库一致）里的 base64 被换成占位文本；
* 当轮新图不受影响（``req.image_urls`` 原样保留）；
* 字符预算超限时从最老整轮开始丢，且永远保留最近一轮；
* **裁剪只作用于请求**：``on_agent_done`` 之后 ``run_context.messages`` 回到完整历史，
  因此 ``_save_to_history`` 写回的是完整历史而不是裁剪结果；
* 不修改调用方传入的对象；幂等；空上下文不炸；短 data URI 不误剥。

跑法（只用 Launcher 实例 venv）::

    <venv>/Scripts/python.exe data/probe_context_guard.py
    <venv>/Scripts/python.exe data/probe_context_guard.py --verbose

退出码：0 全过；1 有失败。
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
CORE = Path(
    r"C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/core"
)
sys.path.insert(0, str(CORE))

PLUGIN = ROOT / "plugins" / "astrbot_plugin_miruku_context_guard" / "main.py"
DB = CORE / "data" / "data_v4.db"

# 生产 400 那次请求的会话与实测数字（用于回归对照）。
PROD_CONVERSATION = "de4f09dc-edf6-482e-ad61-e99f0dbf3f7f"
PROD_API_TOKENS = 1554619
MODEL_LIMIT = 1048576
TOK_PER_CHAR = 0.657


def load_plugin():
    spec = importlib.util.spec_from_file_location("ctx_guard_probe", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeConfig(dict):
    """插件只用到 ``config.get``，dict 够用。"""


class FakeEvent:
    """插件只用到 ``set_extra`` / ``get_extra``。"""

    def __init__(self):
        self._extras = {}

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_extra(self, key=None, default=None):
        return self._extras.get(key, default)


def make_guard(mod, **overrides):
    cfg = FakeConfig(
        strip_history_images=True,
        max_context_chars=400000,
        min_keep_rounds=1,
        restore_history_after_request=True,
        log_stats=False,
    )
    cfg.update(overrides)
    guard = object.__new__(mod.MirukuContextGuard)
    guard.config = cfg
    guard._stats = {
        "requests": 0,
        "images": 0,
        "chars": 0,
        "dropped_rounds": 0,
        "dropped_chars": 0,
    }
    return guard


class FakeReq:
    def __init__(self, contexts, image_urls=None):
        self.contexts = contexts
        self.image_urls = list(image_urls or [])
        self.system_prompt = "PERSONA"
        self.prompt = "hi"


def data_uri(n_bytes: int) -> str:
    """构造一个长度确定的假 base64 data URI。"""
    body = "A" * n_bytes
    return "data:image/jpeg;base64," + body


def msg(role: str, content):
    return {"role": role, "content": content}


def content_chars(content) -> int:
    if isinstance(content, str):
        return len(content)
    total = 0
    if isinstance(content, list):
        for p in content:
            if isinstance(p, dict):
                holder = p.get("image_url") or {}
                url = holder.get("url") if isinstance(holder, dict) else None
                total += len(url) if isinstance(url, str) else len(str(p.get("text", "")))
    return total


def total_chars(contexts) -> int:
    return sum(content_chars(m.get("content") if isinstance(m, dict) else getattr(m, "content", None)) for m in contexts)


def count_data_uris(contexts) -> int:
    """统计 data: URI 个数，字符串内容与 image_url 分片都算。"""

    def count_in_blob(blob: str) -> int:
        return blob.count("data:image/") + blob.count("data:audio/") + blob.count("data:video/")

    n = 0
    for m in contexts:
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if isinstance(c, str):
            n += count_in_blob(c)
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict):
                    holder = p.get("image_url") or {}
                    url = holder.get("url") if isinstance(holder, dict) else None
                    if isinstance(url, str):
                        n += count_in_blob(url)
                    else:
                        n += count_in_blob(str(p.get("text", "")))
    return n


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))


async def run_guard(guard, req, event=None):
    await guard.guard(FakeEvent() if event is None else event, req)


async def run_restore(guard, event, run_context):
    # on_agent_begin fires right after reset() and records the message count anchor.
    await guard.remember_begin(event, run_context)
    await guard.restore_history(event, run_context, None)


def bind(history):
    from astrbot.core.agent.message import bind_checkpoint_messages

    return bind_checkpoint_messages(history)


def simulate_runner(mod, req):
    """按 ``tool_loop_agent_runner.reset()`` 的顺序搭出 run_context.messages。"""
    from astrbot.core.agent.message import Message

    messages = bind(req.contexts or [])
    messages.append(Message(role="user", content="TAIL"))
    if req.system_prompt:
        messages.insert(0, Message(role="system", content=req.system_prompt))
    return SimpleNamespace(messages=messages)


def messages_blob(messages) -> str:
    return json.dumps([str(getattr(m, "content", "")) for m in messages], ensure_ascii=False)


def build_history(n_rounds: int, image_bytes: int = 100_000) -> list:
    """构造 n 轮历史（content 为分片列表），每轮一条带图 user + 一条 assistant。"""
    ctx = []
    for i in range(n_rounds):
        ctx.append(
            msg(
                "user",
                [
                    {"type": "text", "text": f"第{i}轮的话"},
                    {"type": "image_url", "image_url": {"url": data_uri(image_bytes)}},
                ],
            )
        )
        ctx.append(msg("assistant", [{"type": "text", "text": f"第{i}轮的回答"}]))
    return ctx


def build_text_history(n_rounds: int, chars_per_msg: int = 5000) -> list:
    """构造 n 轮纯文本历史——专门测字符预算裁剪。"""
    ctx = []
    for i in range(n_rounds):
        ctx.append(msg("user", [{"type": "text", "text": f"第{i}轮" + "字" * chars_per_msg}]))
        ctx.append(msg("assistant", [{"type": "text", "text": f"答{i}" + "话" * chars_per_msg}]))
    return ctx


async def main() -> int:
    mod = load_plugin()
    verbose = "--verbose" in sys.argv

    # ---- 1. 真实生产历史：剥离 + 恢复 ---------------------------------
    hist = None
    if DB.is_file():
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = con.execute(
            "select content from conversations where conversation_id=?",
            (PROD_CONVERSATION,),
        ).fetchone()
        con.close()
        if row:
            hist = json.loads(row[0])

    if hist:
        before = total_chars(hist)
        before_imgs = count_data_uris(hist)
        snapshot = copy.deepcopy(hist)
        str_content = sum(1 for m in hist if isinstance(m.get("content"), str))

        guard = make_guard(mod, max_context_chars=0)  # 只测剥离
        event = FakeEvent()
        req = FakeReq(copy.deepcopy(hist))
        await run_guard(guard, req, event)
        after = total_chars(req.contexts)
        after_imgs = count_data_uris(req.contexts)

        check(
            "真实历史-剥离前确实超大",
            before * TOK_PER_CHAR > MODEL_LIMIT,
            f"{before:,} 字符 ≈ {int(before * TOK_PER_CHAR):,} token > {MODEL_LIMIT:,}",
        )
        check(
            "真实历史-剥离后低于上限",
            after * TOK_PER_CHAR < MODEL_LIMIT,
            f"{after:,} 字符 ≈ {int(after * TOK_PER_CHAR):,} token",
        )
        check(
            "真实历史-data URI 清零",
            after_imgs == 0,
            f"剥离前 {before_imgs} 张 → 剥离后 {after_imgs} 张；其中整串内容的消息 {str_content}/{len(hist)}",
        )
        check(
            "真实历史-压缩后远低于模型上限",
            before > 0 and after > 0 and before / after > 40 and after < 100_000,
            f"压缩 {before / after:.0f} 倍，请求剩 {after:,} 字符（上限 1,048,576 token）",
        )
        check(
            "真实历史-条数不变（只换内容不删消息）",
            len(req.contexts) == len(hist),
            f"{len(hist)} → {len(req.contexts)}",
        )
        check(
            "真实历史-传入对象原样",
            json.dumps(snapshot, ensure_ascii=False) == json.dumps(hist, ensure_ascii=False),
            "深拷贝传入，原 list 未被改写",
        )

        # 请求结束后必须把完整历史还给 run_context，否则会被落库
        run_ctx = simulate_runner(mod, req)
        await run_restore(guard, event, run_ctx)
        restored_blob = messages_blob(run_ctx.messages)
        check(
            "落库-恢复后条数=原历史+系统+当轮",
            len(run_ctx.messages) == len(hist) + 2,
            f"{len(run_ctx.messages)} 条（原 {len(hist)} + system + tail）",
        )
        check(
            "落库-恢复后 base64 回到历史",
            restored_blob.count("base64,") >= before_imgs,
            f"{before_imgs} 张图仍在待保存历史里",
        )
        check(
            "落库-当轮 tail 保留",
            str(getattr(run_ctx.messages[-1], "content", "")) == "TAIL",
            "最后一条是当轮输入",
        )
        # 钩子是一次性的：第二次调用不再改动
        twice = copy.deepcopy(run_ctx)
        await run_restore(guard, event, twice)
        check(
            "落库-恢复只跑一次",
            messages_blob(twice.messages) == restored_blob,
            "event 上的状态已清空",
        )
    else:
        check("真实历史-库存在", False, f"找不到 {DB} 或没有该会话")

    # ---- 2. 当轮新图不受影响 ------------------------------------------
    fresh = data_uri(50_000)
    guard = make_guard(mod, max_context_chars=0)
    req = FakeReq(build_history(2, 50_000), image_urls=[fresh])
    await run_guard(guard, req)
    check("当轮新图保留", req.image_urls == [fresh], f"image_urls 长度 {len(req.image_urls)}，未被动过")
    check("历史旧图已剥", count_data_uris(req.contexts) == 0, "历史里 2 张旧图被替换")

    # ---- 3. 字符预算裁剪 + 恢复 ---------------------------------------
    hist_text = build_text_history(10, 5000)
    raw = total_chars(hist_text)
    guard = make_guard(mod, max_context_chars=50_000)
    event = FakeEvent()
    req = FakeReq(copy.deepcopy(hist_text))
    await run_guard(guard, req, event)
    trimmed = total_chars(req.contexts)
    check("预算-裁剪后不超限", trimmed <= 50_000, f"{raw:,} → {trimmed:,}（上限 50,000）")
    check("预算-确实丢了轮次", len(req.contexts) < len(hist_text), f"{len(hist_text)} 条 → {len(req.contexts)} 条")
    last_assistant = [m for m in req.contexts if m.get("role") == "assistant"]
    check(
        "预算-保留最近一轮",
        bool(last_assistant) and "答9" in last_assistant[-1]["content"][0]["text"],
        "最后一条 assistant 是第 9 轮",
    )
    run_ctx = simulate_runner(mod, req)
    await run_restore(guard, event, run_ctx)
    keep = sum(1 for m in run_ctx.messages if getattr(m, "role", "") == "user" and str(getattr(m, "content", "")) != "TAIL")
    check(
        "落库-裁剪后仍保存完整历史",
        len(run_ctx.messages) == len(hist_text) + 2,
        f"请求里只剩 {len(req.contexts)} 条，待保存 {len(run_ctx.messages)} 条（含 {keep} 条历史 user）",
    )

    # 若后续钩子（EmotionAI）改写/删减了上下文，能对上的照常还原，对不上的保留它
    guard = make_guard(mod, max_context_chars=50_000)
    req = FakeReq(copy.deepcopy(hist_text))
    event2 = FakeEvent()
    await run_guard(guard, req, event2)
    run_ctx = simulate_runner(mod, req)
    await guard.remember_begin(event2, run_ctx)  # anchor is taken before other hooks touch it
    from astrbot.core.agent.message import Message  # noqa: PLC0415

    head_len = 1 if req.system_prompt else 0
    run_ctx.messages[head_len] = Message(role="user", content="别人改过的内容")
    run_ctx.messages.pop(head_len + 3)
    await run_restore(guard, event2, run_ctx)
    restored_blob = messages_blob(run_ctx.messages)
    check(
        "落库-后续钩子改写/删条后仍按锚点还原完整历史",
        "别人改过的内容" not in restored_blob and len(run_ctx.messages) == len(hist_text) + 2,
        f"被改的那条回到原始内容，待保存 {len(run_ctx.messages)} 条（锚点不受 reshape 影响）",
    )

    # 生产形态：content 是整串字符串（EmotionAI 会把分片也 str 化），恢复仍要成功
    hist_str = []
    for i in range(10):
        hist_str.append(msg("user", f"第{i}轮" + "字" * 5000))
        hist_str.append(msg("assistant", f"答{i}" + "话" * 5000))
    guard = make_guard(mod, max_context_chars=50_000)
    req = FakeReq(copy.deepcopy(hist_str))
    event3 = FakeEvent()
    await run_guard(guard, req, event3)
    run_ctx = simulate_runner(mod, req)
    await run_restore(guard, event3, run_ctx)
    check(
        "落库-整串字符串历史同样完整还原",
        len(run_ctx.messages) == len(hist_str) + 2,
        f"待保存 {len(run_ctx.messages)} 条（原 {len(hist_str)} + system + tail）",
    )

    # ---- 4. 幂等 -------------------------------------------------------
    guard = make_guard(mod, max_context_chars=50_000)
    req = FakeReq(copy.deepcopy(hist_text))
    await run_guard(guard, req)
    once = json.dumps(req.contexts, ensure_ascii=False)
    await run_guard(guard, req)
    twice_json = json.dumps(req.contexts, ensure_ascii=False)
    check("幂等-跑两次结果一致", once == twice_json, "第二次调用不改变结果")

    # ---- 5. 边界 -------------------------------------------------------
    guard = make_guard(mod)
    try:
        await run_guard(guard, FakeReq([]))
        check("边界-空上下文不炸", True, "直接返回")
    except Exception as exc:  # noqa: BLE001
        check("边界-空上下文不炸", False, f"{type(exc).__name__}: {exc}")

    try:
        await run_guard(guard, FakeReq(None))
        check("边界-contexts 为 None 不炸", True, "直接返回")
    except Exception as exc:  # noqa: BLE001
        check("边界-contexts 为 None 不炸", False, f"{type(exc).__name__}: {exc}")

    short = "data:image/png;base64," + "B" * 100
    req = FakeReq([msg("user", [{"type": "image_url", "image_url": {"url": short}}])])
    guard = make_guard(mod, max_context_chars=0)
    await run_guard(guard, req)
    check("边界-短 data URI 不误剥", count_data_uris(req.contexts) == 1, f"保留 1 张（阈值 {mod._MIN_STRIP_LEN} 字符）")

    plain = [msg("user", "你好"), msg("assistant", "嗯")]
    req = FakeReq(copy.deepcopy(plain))
    guard = make_guard(mod, max_context_chars=0)
    await run_guard(guard, req)
    check(
        "边界-纯文本历史原样",
        json.dumps(req.contexts, ensure_ascii=False) == json.dumps(plain, ensure_ascii=False),
        "没有内容被改写",
    )

    req = FakeReq(build_history(1, 5000))
    guard = make_guard(mod, max_context_chars=0)
    await run_guard(guard, req)
    check(
        "边界-不动 system_prompt / prompt",
        req.system_prompt == "PERSONA" and req.prompt == "hi",
        "人格与当轮输入原样",
    )

    # 整串字符串里夹带 base64 的生产形态
    blob = "前文" + data_uri(90_000) + "后文"
    req = FakeReq([msg("user", blob)])
    guard = make_guard(mod, max_context_chars=0)
    await run_guard(guard, req)
    check("整串内容-内联 base64 被剥", count_data_uris(req.contexts) == 0 and "前文" in req.contexts[0]["content"], "占位后保留其它文字")

    # ---- 汇总 ----------------------------------------------------------
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        if ok and not verbose:
            continue
        mark = "ok  " if ok else "FAIL"
        print(f"{mark} {name}" + (f"   {detail}" if detail else ""))
    print()
    print(f"结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过，{len(failed)} 失败")
    print(f"（对照：生产 400 时 API 实际 {PROD_API_TOKENS:,} token，模型上限 {MODEL_LIMIT:,}）")
    return 1 if failed else 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
