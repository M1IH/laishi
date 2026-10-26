"""Probe the repr-string revive path of astrbot_plugin_miruku_context_guard.

Covers the C-22 defect: some plugin rewrites ``content`` with ``str(...)``, so a
list of content parts is stored as a Python literal string. The provider only
separates ``think`` parts into ``reasoning_content`` when content is a real
list, so a stringified assistant turn replays the model's private reasoning as
ordinary conversation.

Runs without AstrBot: the plugin module is forced in, and the revive helpers are
exercised directly on plain dict/object messages.

Usage:
    python data/probe_context_guard_revive.py
Exit code 0 means every case passed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "astrbot_plugin_miruku_context_guard" / "main.py"

CASES: list[tuple[str, bool]] = []


def _load_plugin():
    spec = importlib.util.spec_from_file_location("miruku_context_guard_revive_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


guard = _load_plugin()


def check(name: str, ok: bool) -> None:
    CASES.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}")


def fresh() -> dict:
    return {"revived": 0}


# --- R1: a stringified think+text assistant turn is revived ------------------
text = "[{'type': 'think', 'think': 'reason here', 'encrypted': None}, {'type': 'text', 'text': 'hello'}]"
msg = {"role": "assistant", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R1 revived", stats["revived"] == 1)
check("R1 content is list", isinstance(out["content"], list))
check("R1 two parts", len(out["content"]) == 2)
check("R1 think kept", out["content"][0]["think"] == "reason here")
check("R1 text kept", out["content"][1]["text"] == "hello")

# --- R2: a plain user text is left exactly as it was -------------------------
msg = {"role": "user", "content": "今天想问你个事"}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R2 untouched", out is msg)
check("R2 nothing counted", stats["revived"] == 0)

# --- R3: a JSON-ish list with double quotes also parses ----------------------
text = '[{"type": "text", "text": "hi"}]'
msg = {"role": "user", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R3 revived", stats["revived"] == 1 and isinstance(out["content"], list))
check("R3 text", out["content"][0]["text"] == "hi")

# --- R4: a literal that is not a part list is left alone ---------------------
text = "[1, 2, 3]"
msg = {"role": "user", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R4 untouched", out is msg and stats["revived"] == 0)

# --- R5: unparsable text is left alone, no exception -------------------------
text = "[{'type': 'text', 'text': 'broken"
msg = {"role": "user", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R5 untouched", out is msg and stats["revived"] == 0)

# --- R6: an unknown part type blocks the revive ------------------------------
text = "[{'type': 'weird_thing', 'x': 1}]"
msg = {"role": "user", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R6 untouched", out is msg and stats["revived"] == 0)

# --- R7: mixed valid/invalid types block the revive --------------------------
text = "[{'type': 'text', 'text': 'a'}, {'type': 'nope'}]"
msg = {"role": "user", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R7 untouched", out is msg and stats["revived"] == 0)

# --- R8: an empty list is not a message body --------------------------------
msg = {"role": "user", "content": "[]"}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R8 untouched", out is msg and stats["revived"] == 0)

# --- R9: an image_url part survives the revive ------------------------------
text = (
    "[{'type': 'text', 'text': '[图片]'}, "
    "{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,AAA', 'id': None}}]"
)
msg = {"role": "user", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R9 revived", stats["revived"] == 1)
check("R9 image part", out["content"][1]["type"] == "image_url")
check("R9 url kept", out["content"][1]["image_url"]["url"].endswith("AAA"))

# --- R10: think-only turn revives (the 410-char leak in the live store) -----
text = "[{'type': 'think', 'think': 'The user asks for a story.', 'encrypted': None}]"
msg = {"role": "assistant", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R10 revived", stats["revived"] == 1)
check("R10 single think", len(out["content"]) == 1 and out["content"][0]["type"] == "think")

# --- R11: a tool message with plain text is untouched -----------------------
msg = {"role": "tool", "content": "Message sent to session miruku:FriendMessage:1"}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R11 untouched", out is msg and stats["revived"] == 0)

# --- R12: leading/trailing whitespace does not block the revive -------------
text = "  [{'type': 'text', 'text': 'hi'}]  \n"
msg = {"role": "user", "content": text}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R12 revived", stats["revived"] == 1 and out["content"][0]["text"] == "hi")

# --- R13: the size ceiling rejects a huge literal ---------------------------
huge = "[" + "{'type': 'text', 'text': 'x'}" + ", " * 1 + "]"
msg = {"role": "user", "content": huge}
stats = fresh()
guard._revive_stringified_content(msg, stats)
check("R13 small literal accepted", stats["revived"] == 1)

msg = {"role": "user", "content": "[" + " " * (guard._REVIVE_MAX_LEN + 10) + "]"}
stats = fresh()
out = guard._revive_stringified_content(msg, stats)
check("R13b oversized untouched", out is msg and stats["revived"] == 0)

# --- R14: Message objects are copied, not mutated in place ------------------
try:
    from astrbot.core.agent.message import Message

    original = Message(role="assistant", content=text)
    stats = fresh()
    out = guard._revive_stringified_content(original, stats)
    check("R14 revived", stats["revived"] == 1)
    check("R14 still Message", isinstance(out, Message))
    check("R14 original untouched", isinstance(original.content, str))
    check("R14 revived parts", isinstance(out.content, list) and len(out.content) == 1)
except Exception as exc:  # pragma: no cover - astrbot absent outside the venv
    print(f"SKIP  R14 (astrbot Message unavailable: {exc})")

# --- R15: base64 strip runs before revive, so the literal stays small -------
payload = "data:image/jpeg;base64," + "A" * 300000
parts = [
    "{'type': 'text', 'text': '[图片]'}",
    "{'type': 'text', 'text': '" + "y" * 5000 + "'}",
    "{'type': 'text', 'text': '" + payload + "'}",
]
msg = {"role": "user", "content": "[" + ", ".join(parts) + "]"}
strip_stats = {"images": 0, "chars": 0}
stripped = guard._strip_message(msg, strip_stats)
check("R15 base64 stripped", strip_stats["images"] == 1)
stats = fresh()
out = guard._revive_stringified_content(stripped, stats)
check("R15 revived after strip", stats["revived"] == 1)
check("R15 placeholder present", "[图片]" in str(out["content"]))


passed = sum(1 for _, ok in CASES if ok)
total = len(CASES)
print(f"\n{passed}/{total} passed")
sys.exit(0 if passed == total else 1)
