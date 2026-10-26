"""End-to-end check that the revive step really fixes the outbound payload.

Loads the *live* conversation store (read-only), runs the guard's real
``_apply`` on the stored history, then replays the provider's payload assembly
(``_ensure_message_to_dicts`` + ``_finally_convert_payload``) to see what the
model would actually receive.

Before the fix, stringified assistant turns bypass the think/reasoning split and
their private reasoning is sent as ordinary conversation text. This script
asserts that no such turn survives.

Usage:
    <venv>/Scripts/python.exe data/verify_revive_payload.py
Exit code 0 means every assertion held.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

CORE = Path(r"C:/Users/OTTO/.astrbot_launcher/instances/298681be-6ba8-4137-818c-28ed67ec9176/core")
sys.path.insert(0, str(CORE))

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "astrbot_plugin_miruku_context_guard" / "main.py"
DB = CORE / "data" / "data_v4.db"

CONVERSATIONS = [
    "miruku:FriendMessage:10000001",
    "miruku:FriendMessage:10000002",
]

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


class FakeConfig(dict):
    def get(self, key, default=None):  # noqa: D102 - mimic AstrBotConfig
        return dict.get(self, key, default)


def make_guard(mod):
    cfg = FakeConfig(
        strip_history_images=True,
        max_context_chars=400000,
        min_keep_rounds=1,
        restore_history_after_request=False,
        revive_stringified_content=True,
        log_stats=False,
    )
    guard = object.__new__(mod.MirukuContextGuard)
    guard.config = cfg
    guard._stats = {
        "requests": 0,
        "images": 0,
        "chars": 0,
        "revived": 0,
        "dropped_rounds": 0,
        "dropped_chars": 0,
    }
    return guard


class FakeReq:
    def __init__(self, contexts):
        self.contexts = contexts
        self.image_urls = []
        self.system_prompt = "PERSONA"
        self.prompt = "hi"


class FakeEvent:
    def __init__(self):
        self._extra = {}

    def set_extra(self, key, value):
        self._extra[key] = value

    def get_extra(self, key, default=None):
        return self._extra.get(key, default)


def load_history(user_id: str) -> list:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select content from conversations where user_id = ?", (user_id,)
        ).fetchone()
    finally:
        con.close()
    if not row:
        return []
    msgs = json.loads(row[0])
    # Mimic bind_checkpoint_messages: drop checkpoints, keep everything else.
    return [m for m in msgs if m.get("role") != "_checkpoint"]


def dump_payload(mod, message) -> dict:
    """Replay provider.py + openai_source.py payload assembly for one message."""
    role = message.get("role")
    content = message.get("content")

    # openai_source._finally_convert_payload only splits think when content is a list.
    reasoning = None
    if role == "assistant" and isinstance(content, list):
        texts = []
        thinks = []
        for part in content:
            if not isinstance(part, dict):
                part = part.model_dump() if hasattr(part, "model_dump") else part
            ptype = part.get("type")
            if ptype == "think":
                thinks.append(part.get("think") or "")
            elif ptype == "text":
                texts.append(part.get("text") or "")
        reasoning = "\n".join(t for t in thinks if t) or ""
        content = "".join(texts) or None

    return {"role": role, "content": content, "reasoning_content": reasoning}


async def run_guard(mod, guard, contexts):
    req = FakeReq(contexts)
    await guard._apply(FakeEvent(), req)
    return req.contexts


def main() -> int:
    mod_spec = importlib.util.spec_from_file_location("ctx_guard_revive_e2e", PLUGIN)
    mod = importlib.util.module_from_spec(mod_spec)
    assert mod_spec.loader is not None
    mod_spec.loader.exec_module(mod)

    import asyncio

    for user_id in CONVERSATIONS:
        history = load_history(user_id)
        print(f"\n=== {user_id}  ({len(history)} 条)")
        if not history:
            check(f"{user_id} 有历史", False)
            continue

        guard = make_guard(mod)
        contexts = asyncio.run(run_guard(mod, guard, list(history)))

        revived = guard._stats["revived"]
        check(f"{user_id} 发生还原", revived > 0, f"revived={revived}")

        leaked = []
        for i, message in enumerate(contexts):
            payload = dump_payload(mod, message)
            if payload["role"] != "assistant":
                continue
            content = payload["content"]
            if not isinstance(content, str):
                continue
            # A leaked think shows up as the literal repr of a think part.
            if "'type': 'think'" in content or '"type": "think"' in content:
                leaked.append((i, len(content)))

        check(
            f"{user_id} 无反序列化残留",
            not leaked,
            "" if not leaked else f"泄漏 {leaked}",
        )

        # Real turn text must still be there (guard must not eat user/assistant text).
        plain = sum(
            len(m["content"])
            for m in (dump_payload(mod, x) for x in contexts)
            if isinstance(m["content"], str)
        )
        check(f"{user_id} 正文仍在", plain > 0, f"剩余字符 {plain}")

    print()
    if failures:
        print(f"{len(failures)} 项失败：{failures}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
