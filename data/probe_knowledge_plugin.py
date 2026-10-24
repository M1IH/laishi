"""Offline checks of the production LLM request handler; no QQ traffic."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CORE = Path(r"C:\Users\OTTO\.astrbot_launcher\instances\298681be-6ba8-4137-818c-28ed67ec9176\core")
sys.path.insert(0, str(CORE))
PLUGIN = ROOT / "plugins/astrbot_plugin_miruku_knowledge/main.py"
spec = importlib.util.spec_from_file_location("miruku_knowledge_probe", PLUGIN)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Event:
    def __init__(self, message, private=True, sender="target", platform="miruku"):
        self.message_str = message
        self.private = private
        self.sender = sender
        self.platform = platform

    def is_private_chat(self):
        return self.private

    def get_sender_id(self):
        return self.sender

    def get_platform_id(self):
        return self.platform


async def main():
    plugin = object.__new__(module.MirukuKnowledge)
    plugin.config = {"knowledge_root": str(ROOT / "knowledge"), "target_qq": "target", "platform_id": "miruku"}
    plugin._build_block = None
    plugin._root = None
    cases = [
        (Event("KING 你多少分"), True, "KING"),
        (Event("ロキ你多少分"), True, module.MARK),
        (Event("你也打街霸6吗"), True, "街霸"),
        (Event("今天吃什么"), False, ""),
        (Event("KING 你多少分", private=False), False, ""),
        (Event("KING 你多少分", sender="other"), False, ""),
        (Event("KING 你多少分", platform="other"), False, ""),
    ]
    for event, expected, needle in cases:
        request = SimpleNamespace(system_prompt="base")
        await plugin.add_knowledge(event, request)
        got = module.MARK in request.system_prompt
        assert got == expected, (event.message_str, got, expected)
        if expected:
            assert needle in request.system_prompt
            before = request.system_prompt
            await plugin.add_knowledge(event, request)
            assert request.system_prompt == before
    missing = object.__new__(module.MirukuKnowledge)
    missing.config = {"knowledge_root": str(ROOT / "missing"), "target_qq": "target", "platform_id": "miruku"}
    missing._build_block = None
    missing._root = None
    req = SimpleNamespace(system_prompt="base")
    await missing.add_knowledge(Event("KING 你多少分"), req)
    assert req.system_prompt == "base"
    print("knowledge plugin: 8/8 PASS")


if __name__ == "__main__":
    asyncio.run(main())
