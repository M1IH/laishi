"""Keep one LLM request inside the model's real context budget.

Why this exists
---------------
AstrBot persists tool-loop history verbatim. When a user sends a picture, the
stored history keeps the whole ``data:image/jpeg;base64,...`` payload, and every
later turn re-sends it. AstrBot's own guard does not catch that:

* ``EstimateTokenCounter`` charges ``IMAGE_TOKEN_ESTIMATE = 765`` tokens per
  ``ImageURLPart`` regardless of how many characters the URL actually is
  (``astrbot/core/agent/context/token_counter.py``). Measured on the production
  conversation: the counter reported 24,615 tokens while the API received
  1,554,619 -- a 63.2x underestimate -- so ``should_compress`` never fired.
* When the API does reject the request, ``openai_source`` retries by calling
  ``pop_record``, which drops two text messages per attempt
  (``astrbot/core/provider/provider.py``). The base64 images are never among the
  dropped records, so ten retries cannot fix it.

This plugin fixes both at the request-assembly layer, before the provider sees
the payload:

1. Rewrite history inline ``data:`` payloads into a short text placeholder. Both
   stored shapes are handled: a message whose ``content`` is one long string
   (how this install stores image turns) and a ``content`` list of content
   parts. The current turn's fresh images (``req.image_urls`` /
   ``req.extra_user_content_parts``) are deliberately left alone, so she can
   still look at a picture the moment it arrives.
2. Enforce a character budget over the remaining history by dropping the oldest
   whole rounds, always keeping the most recent round.

Trimming is request-scoped only. ``internal.py`` awaits ``runner.reset()``
*after* the ``OnLLMRequestEvent`` hook and persists ``run_context.messages`` at
the end of the turn, so a plain ``req.contexts`` rewrite would be written back
to the conversation store and silently shorten her memory. To prevent that the
original ``contexts`` are stashed on the event and reinstalled into
``run_context.messages`` from the ``OnAgentDoneEvent`` hook, which runs before
``_save_to_history``. Stored history therefore keeps every message and every
image; only the bytes sent to the model are cut.

It never deletes or rewrites stored conversation history, never touches
``system_prompt``/persona, and never logs message text, accounts or prompts.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.provider.entities import ProviderRequest

try:  # AstrBot >= 4.x
    from astrbot.core.message.components import Plain
except Exception:  # pragma: no cover - keeps the plugin importable on forks
    Plain = None  # type: ignore[assignment]

try:  # AstrBot >= 4.x
    from astrbot.core.agent.message import bind_checkpoint_messages
except Exception:  # pragma: no cover - keeps the plugin importable on forks
    bind_checkpoint_messages = None  # type: ignore[assignment]

# Placeholder text substituted for a stripped history image. Kept short and
# descriptive: the model should know a picture was there without paying for it.
IMAGE_PLACEHOLDER = "[图片]"

# A data URI shorter than this is left alone -- it cannot be a real image and
# stripping it would only destroy information.
_MIN_STRIP_LEN = 2048

# Only these prefixes count as inline binary payloads worth stripping.
_DATA_PREFIXES = (
    "data:image/",
    "data:audio/",
    "data:video/",
    "data:application/",
)

# Matches an inline base64 payload inside a plain string message.
_INLINE_DATA_URI_RE = re.compile(
    r"data:[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]*"
)

# Event extra key holding the restore state between the two hooks.
_EXTRA_KEY = "_miruku_context_guard_restore"
_BEGIN_KEY = "_miruku_context_guard_begin"

# ---------------------------------------------------------------------------
# Injection scrub
# ---------------------------------------------------------------------------
# ``astrbot_plugin_emotionai`` appends three synthetic messages to
# ``req.contexts`` on every single LLM request (``main.py:724-745``):
#
#   user      "（系统自检：请报告当前情感状态）"
#   assistant "<thought>...收到系统自检指令...</thought>当前状态正常。"
#   system    "[PROTOCOL_ENFORCEMENT] ... REQUIRED ACTION: Generate XML block."
#
# EmotionAI intends them as per-turn scaffolding and strips previous copies at
# the top of its own hook. That works for the *request* but not for the
# *conversation store*: ``internal.py:517-527`` saves the whole
# ``run_context.messages`` after the turn, skipping only the leading system
# message. So the three synthetic messages get written to the conversation
# every turn, and because EmotionAI deletes the old set before appending a new
# one, exactly one stale set is always sitting in the stored history. The model
# then reads it on the next turn as if the user had sent it -- which is how she
# once answered "那堆乱码不用理" to a message the user never wrote.
#
# This scrub runs from ``OnAgentDoneEvent`` (before ``_save_to_history``) and
# drops those synthetic messages from what is about to be persisted. It only
# ever removes text that matches EmotionAI's own constants; real user and
# assistant messages are untouched.
_FAKE_SELFCHECK = "（系统自检：请报告当前情感状态）"
_PROTOCOL_MARK = "[PROTOCOL_ENFORCEMENT]"
_FAKE_SAMPLE_HINT = "收到系统自检指令"

_THOUGHT_BLOCK_RE = re.compile(
    r"(?:```(?:xml|text)?\s*)?<(?:thought|thinking)>[\s\S]*?</(?:thought|thinking)>(?:\s*```)?",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Outbound mark scrub
# ---------------------------------------------------------------------------
# Nothing in AstrBot itself guarantees that the model's internal markup never
# reaches the chat. ``astrbot_plugin_emotionai`` does strip ``<thought>`` from
# ``resp.completion_text`` (main.py:886) -- but only while its own
# ``show_thought`` flag is off, and ``/心理显示`` is an ordinary user command
# that flips that flag with no admin check (main.py:391-397, :958-960).
# Measured on 2026-10-26 20:40 through the dashboard path: with the flag on, a
# five-section ``<thought>`` block went out verbatim as reply text.
#
# So the outgoing message is scrubbed here as well, independent of any other
# plugin's settings. Only things that can never be legitimate reply text are
# removed: paired or orphaned thought tags, ``[Profile: ...]``, DSML markers, an
# echoed ``<system_reminder>``, and bare monologue lines such as ``[感知] ...``.
# Semantic checks (invite promises, fabricated scores) stay in
# ``knowledge/outbound.py`` and are deliberately not duplicated here -- this
# hook only enforces "no internal markup on the wire".
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")

# ASCII full-width twins, plus the bracket variants Chinese input methods emit.
_FULLWIDTH_EXTRA = {
    "[": "［【",
    "]": "］】",
    "<": "＜",
    ">": "＞",
    ":": "：",
    "/": "／",
    "|": "｜",
    "\\": "＼",
    ".": "．",
    "-": "－",
    "_": "＿",
}

_LT = r"[<\uFF1C]"
_GT = r"[>\uFF1E]"
_SLASH = r"[/\uFF0F]"


def _mark_lit(text: str) -> str:
    """Compile a literal into a regex that accepts half- and full-width forms.

    ``re.I`` alone is not enough: Python does not fold ``ｔ`` (U+FF54) into
    ``t``, so ``＜ｔｈｏｕｇｈｔ＞`` -- a very common shape from a Chinese IME --
    would slip through an ASCII-only pattern.
    """
    out: list[str] = []
    for ch in text:
        alts = [ch]
        code = ord(ch)
        if 0x21 <= code <= 0x7E:
            alts.append(chr(code + 0xFEE0))
        alts.extend(_FULLWIDTH_EXTRA.get(ch, ""))
        if ch.isalpha():
            alts.extend(alt.upper() for alt in list(alts))
            alts.extend(alt.lower() for alt in list(alts))
        uniq = list(dict.fromkeys(alts))
        out.append("[" + "".join(re.escape(a) for a in uniq) + "]")
    return "".join(out)


def _tag(name: str) -> str:
    """``<name>``, tolerant of full-width brackets and inner spaces."""
    return _LT + r"\s*" + _mark_lit(name) + r"\s*" + _GT


def _close_tag(name: str) -> str:
    """``</name>``, same tolerance."""
    return _LT + r"\s*" + _SLASH + r"\s*" + _mark_lit(name) + r"\s*" + _GT


def _pair(name: str) -> re.Pattern[str]:
    """Innermost-first paired matcher.

    A plain non-greedy match leaves residue when the model nests tags:
    ``<thought>a<thought>b</thought>c</thought>`` would drop only the inner
    part and leave ``c`` in the reply. Forbidding a nested opener inside the
    body makes the engine close the innermost block first, so repeated
    substitution converges on the right answer.
    """
    return re.compile(
        _tag(name) + r"(?:(?!" + _tag(name) + r")[\s\S])*?" + _close_tag(name)
    )


_OPEN_THOUGHT_RE = re.compile(_tag("thought"))
_CLOSE_THOUGHT_RE = re.compile(_close_tag("thought"))

# Paired markup. Ordered innermost-name-first; ``thinking`` must precede
# ``think`` so the longest name wins.
_PAIRED_TAGS = [
    ("thought", _pair("thought")),
    ("thinking", _pair("thinking")),
    ("think", _pair("think")),
]

# Order matters: paired forms before bare tags, so a closing tag left behind by
# a pair rule is not mistaken for an orphan and used to cut real text.
_OUTBOUND_PATTERNS = [
    # [Profile: 爱好=舞萌] -- closing bracket may be ], ］ or 】.
    (re.compile(_mark_lit("[Profile:") + r"[^\]］】\n]*" + _mark_lit("]")), "profile"),
    # Whole metadata line starting with `Profile:`. Anchored at line start so a
    # sentence that merely mentions the word ("我的 profile 没啥好写的") is safe.
    # Inline bare forms are deliberately not eaten: `Profile: 称呼=来世在吗` has
    # no way to tell where the value stops and the reply begins, and cutting it
    # sentence-wise loses real text.
    (re.compile(r"(?im)^[ \t]*Profile\s*[:：][^\n]*"), "profile-line"),
    # An emptied ```xml fence left behind after a thought block was removed.
    (re.compile(r"```[ \t]*(?:xml|text)?[ \t]*\n?[ \t]*```"), "empty-fence"),
    # DSML markers use two pipe characters: ASCII `|` and full-width `｜`.
    (re.compile(r"</?[|｜]{1,3}DSML[|｜]{1,3}[^>＞]*[>＞]?"), "dsml"),
    # An echoed reminder block, paired then unpaired.
    (
        re.compile(
            _tag("system_reminder") + r".*?" + _close_tag("system_reminder"),
            re.S,
        ),
        "sys-reminder",
    ),
    (re.compile(_tag("system_reminder")), "sys-reminder-tag"),
    (re.compile(_close_tag("system_reminder")), "sys-reminder-tag"),
    # Parenthesised internal state: 「（更新：joy:2）」.
    (
        re.compile(
            r"[\(（]\s*(?:感知|评估|决策|更新|代谢|思考|内心|分析|自检|判定)"
            r"\s*[:：][^\)）\n]*[\)）]"
        ),
        "state-paren",
    ),
    # Bare monologue line with no tags at all: `[感知] 对方问在不在…`.
    (
        re.compile(
            r"[\[［【]\s*(?:感知|评估|决策|更新|代谢|思考|内心|分析|自检|判定)"
            r"\s*[\]］】][^\n\[\]［］【】]*"
        ),
        "monologue-line",
    ),
    (re.compile(_mark_lit("tool_calls") + r"\s*[:：]?\s*"), "tool-calls"),
    # Last resort: any bare tag still standing.
    (re.compile(_close_tag("thought") + "|" + _tag("thought")), "thought-tag"),
    (
        re.compile(
            _close_tag("think")
            + "|"
            + _tag("think")
            + "|"
            + _close_tag("thinking")
            + "|"
            + _tag("thinking")
        ),
        "think-tag",
    ),
    (
        re.compile(_close_tag("tool_calls") + "|" + _tag("tool_calls")),
        "tool-tag",
    ),
]


def _strip_outbound_marks(text: str) -> tuple[str, list[str]]:
    """Remove internal markup from one outgoing text segment.

    Returns ``(cleaned, hits)``. An empty ``cleaned`` with non-empty ``hits``
    means the segment was nothing but internal monologue and must not be sent.
    """
    hits: list[str] = []
    if not text:
        return text, hits

    text = _INVISIBLE_RE.sub("", text)
    for _ in range(4):
        before = text

        # Paired blocks first, repeatedly: nesting needs several passes.
        for name, pattern in _PAIRED_TAGS:
            for _ in range(4):
                replaced = pattern.sub("", text)
                if replaced == text:
                    break
                hits.append(name)
                text = replaced

        closes = list(_CLOSE_THOUGHT_RE.finditer(text))
        opens = list(_OPEN_THOUGHT_RE.finditer(text))
        if closes and not opens:
            # The opening tag is gone (truncated output) but the block contents
            # are still there. Drop the orphan marker; the monologue-line rules
            # below handle any bare 感知/决策/更新 lines that remain. Cutting to
            # the marker would also delete legitimate text written after it.
            text = _CLOSE_THOUGHT_RE.sub("", text)
            hits.append("thought-orphan-close")
        elif opens:
            last_close = closes[-1].start() if closes else -1
            unclosed = [m for m in opens if m.start() > last_close]
            if unclosed:
                # Truncated output: the block never closed, so everything from
                # the opener onward is still monologue.
                text = text[: unclosed[0].start()]
                hits.append("thought-unclosed")

        for pattern, name in _OUTBOUND_PATTERNS:
            if pattern.search(text):
                hits.append(name)
                text = pattern.sub("", text)

        if text == before:
            break

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, list(dict.fromkeys(hits))


def _is_data_uri(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) > _MIN_STRIP_LEN
        and value[:24].lower().startswith(_DATA_PREFIXES)
    )


def _strip_inline_payloads(text: str, stats: dict[str, int]) -> str:
    """Replace long inline base64 payloads inside a plain string."""
    if "base64," not in text:
        return text

    def _sub(match: re.Match[str]) -> str:
        uri = match.group(0)
        if len(uri) <= _MIN_STRIP_LEN or not _is_data_uri(uri):
            return uri
        stats["images"] += 1
        stats["chars"] += len(uri)
        return IMAGE_PLACEHOLDER

    return _INLINE_DATA_URI_RE.sub(_sub, text)


def _strip_parts(content: list[Any], stats: dict[str, int]) -> list[Any]:
    """Replace inline data-URI media parts with text placeholders.

    Returns a new list; the caller's objects are not mutated in place so a
    failed request cannot leave the stored history half-rewritten.
    """
    out: list[Any] = []
    for part in content:
        if isinstance(part, dict):
            ptype = str(part.get("type", "")).lower()
            if ptype in ("image_url", "image"):
                holder = part.get("image_url")
                url = holder.get("url") if isinstance(holder, dict) else None
                if _is_data_uri(url):
                    stats["images"] += 1
                    stats["chars"] += len(url)
                    out.append({"type": "text", "text": IMAGE_PLACEHOLDER})
                    continue
            elif ptype in ("input_audio", "audio", "video"):
                holder = part.get(ptype) if isinstance(part.get(ptype), dict) else {}
                url = holder.get("url") or holder.get("data")
                if _is_data_uri(url):
                    stats["images"] += 1
                    stats["chars"] += len(url)
                    out.append({"type": "text", "text": IMAGE_PLACEHOLDER})
                    continue
            elif ptype == "text":
                text = part.get("text")
                if isinstance(text, str) and len(text) > _MIN_STRIP_LEN:
                    stripped = _strip_inline_payloads(text, stats)
                    if stripped != text:
                        out.append({**part, "text": stripped})
                        continue
            out.append(part)
            continue

        # Pydantic parts from AstrBot's own models.
        cls_name = type(part).__name__
        if cls_name in ("ImageURLPart", "AudioURLPart"):
            holder = getattr(part, "image_url", None) or getattr(part, "audio_url", None)
            url = getattr(holder, "url", None)
            if _is_data_uri(url):
                stats["images"] += 1
                stats["chars"] += len(url)
                out.append({"type": "text", "text": IMAGE_PLACEHOLDER})
                continue
        elif cls_name in ("TextPart", "PlainPart"):
            text = getattr(part, "text", None)
            if isinstance(text, str) and len(text) > _MIN_STRIP_LEN:
                stripped = _strip_inline_payloads(text, stats)
                if stripped != text:
                    try:
                        out.append(part.model_copy(update={"text": stripped}))
                    except Exception:
                        out.append(part)
                    continue
        out.append(part)

    return out


def _strip_content(content: Any, stats: dict[str, int]) -> Any:
    """Strip one message's content, returning the original object if untouched."""
    if isinstance(content, str):
        if len(content) <= _MIN_STRIP_LEN:
            return content
        return _strip_inline_payloads(content, stats)
    if isinstance(content, list):
        stripped = _strip_parts(content, stats)
        return stripped
    return content


def _strip_message(msg: Any, stats: dict[str, int]) -> Any:
    """Return a message object with stripped content, or the input unchanged."""
    if isinstance(msg, dict):
        content = msg.get("content")
        stripped = _strip_content(content, stats)
        return msg if stripped is content else {**msg, "content": stripped}

    content = getattr(msg, "content", None)
    stripped = _strip_content(content, stats)
    if stripped is content:
        return msg
    try:
        return msg.model_copy(update={"content": stripped})
    except Exception:
        return msg


# ---------------------------------------------------------------------------
# Revive stringified content
# ---------------------------------------------------------------------------
# AstrBot stores a message's ``content`` either as plain text or as a list of
# content parts. Some plugin rewrites ``content`` with ``str(...)``, so a part
# list is persisted as a *Python literal string*:
#
#   "[{'type': 'think', 'think': '...', 'encrypted': None}, {'type': 'text', ...}]"
#
# Once that happens it never recovers: ``dump_messages_with_checkpoints`` only
# serialises a list (``astrbot/core/agent/message.py:345-361``) and
# ``bind_checkpoint_messages`` only validates (``:327``), so the string is
# reloaded verbatim every turn.
#
# The damage is that ``openai_source._finally_convert_payload``
# (``astrbot/core/provider/sources/openai_source.py:1029-1046``) separates
# ``think`` parts into ``reasoning_content`` **only when content is a list**.
# Stringified assistant turns skip that branch entirely, so the model's private
# reasoning is replayed to itself as if the user had said it. Worse, image
# turns keep their whole base64 payload inside the literal, which then counts as
# ordinary prose.
#
# The provider has a partial rescue for short strings only (``len < 8192``,
# ``openai_source.py:806-828``), which every real turn exceeds. This revives the
# parts here, before the payload is assembled, so the normal think/text
# separation path applies again.
#
# Only the *request* is repaired; the conversation store is left as it is, which
# keeps this plugin's promise not to rewrite stored history. A message is only
# revived when the literal parses and every element is a recognised content
# part -- anything else is left exactly as it was.
_REVIVE_MAX_LEN = 4_000_000

# Part types that ``Message`` accepts; anything else means "not a part list".
_CONTENT_PART_TYPES = frozenset(
    {"text", "think", "image_url", "audio_url", "input_audio", "video", "image", "file"}
)


def _looks_like_parts(value: Any) -> bool:
    """True when ``value`` is a non-empty list of content-part dicts."""
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        ptype = item.get("type")
        if not isinstance(ptype, str) or ptype.lower() not in _CONTENT_PART_TYPES:
            return False
    return True


def _sanitize_revived_parts(value: list[Any]) -> list[Any]:
    """Fix what the strip-then-revive order leaves behind (2026-10-26, server 400).

    The strip pass replaces inline data URIs with ``IMAGE_PLACEHOLDER`` *inside
    the repr string*; the revive pass then parses that string into a real part
    list. Any ``image_url`` part that had held a data URI now carries the
    placeholder text **as its url** -- and the provider sends
    ``{"image_url": {"url": "[图片]"}}`` straight to DeepSeek, which rejects it
    with ``Unsupported image_url format``. Measured on the server: the test
    account's stored history is 180/184 stringified messages, so every
    proactive call with images in context died at ``messages[19]`` while the
    guard happily logged ``stripped_images=24``.

    Rule: a media part whose url is our placeholder becomes a text part (the
    history genuinely says "an image was here"); a media part with an empty
    url is dropped outright. Real ``http(s)``/``data:`` urls are untouched --
    short surviving data URIs below the strip floor stay valid payloads.
    """
    out: list[Any] = []
    for part in value:
        if isinstance(part, dict):
            ptype = str(part.get("type", "")).lower()
            if ptype in ("image_url", "image", "audio", "input_audio", "video"):
                holder = part.get("image_url") or part.get("audio_url") or part.get(ptype)
                url = holder.get("url") if isinstance(holder, dict) else None
                if isinstance(url, str) and url.strip() == IMAGE_PLACEHOLDER:
                    out.append({"type": "text", "text": IMAGE_PLACEHOLDER})
                    continue
                if url is None or (isinstance(url, str) and not url.strip()):
                    continue
        out.append(part)
    return out


def _revive_stringified_content(msg: Any, stats: dict[str, int]) -> Any:
    """Turn a repr-stringified part list back into a real list of parts."""
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
    if not isinstance(content, str):
        return msg

    text = content.strip()
    if len(text) < 4 or len(text) > _REVIVE_MAX_LEN:
        return msg
    if not text.startswith("[") or not text.endswith("]"):
        return msg

    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return msg

    if not _looks_like_parts(value):
        return msg

    value = _sanitize_revived_parts(value)
    stats["revived"] += 1
    if isinstance(msg, dict):
        return {**msg, "content": value}
    try:
        return msg.model_copy(update={"content": value})
    except Exception:
        return msg


def _part_chars(part: Any) -> int:
    """Payload size of one content part.

    ``think`` counts: the provider forwards it as ``reasoning_content``, which is
    still billed, so leaving it out would under-report the budget.
    """
    if isinstance(part, dict):
        holder = part.get("image_url") or part.get("audio_url") or {}
        url = holder.get("url") if isinstance(holder, dict) else None
        if isinstance(url, str):
            return len(url)
        text = part.get("text")
        if isinstance(text, str):
            return len(text)
        think = part.get("think")
        if isinstance(think, str):
            return len(think)
        return 0

    holder = getattr(part, "image_url", None) or getattr(part, "audio_url", None)
    url = getattr(holder, "url", None)
    if isinstance(url, str):
        return len(url)
    text = getattr(part, "text", None)
    if isinstance(text, str):
        return len(text)
    think = getattr(part, "think", None)
    if isinstance(think, str):
        return len(think)
    return 0


def _content_chars(content: Any) -> int:
    """Approximate payload size of one message's content."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(_part_chars(part) for part in content)
    return 0


def _role_of(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    return str(getattr(msg, "role", ""))


def _round_starts(contexts: list[Any]) -> list[int]:
    """Index of the first message of each round.

    A round begins at a ``user`` message. System messages before the first user
    message belong to the preamble and are never dropped.
    """
    starts = [i for i, m in enumerate(contexts) if _role_of(m) == "user"]
    return starts or [0]


def _content_text(content: Any) -> str:
    """Best-effort plain text of one message's content, for marker matching."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    out.append(text)
            else:
                text = getattr(part, "text", None)
                if isinstance(text, str):
                    out.append(text)
        return "".join(out)
    return str(content)


def _is_synthetic(msg: Any) -> bool:
    """True when this message is one of EmotionAI's injected scaffolding turns."""
    role = _role_of(msg)
    text = _content_text(msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None))

    if role == "user" and _FAKE_SELFCHECK in text:
        return True
    if role == "system" and _PROTOCOL_MARK in text:
        return True
    if role == "assistant" and _FAKE_SAMPLE_HINT in text and "<thought" in text:
        return True
    return False


def _strip_thought_inline(msg: Any) -> Any:
    """Remove an inline ``<thought>`` block from a real assistant message.

    EmotionAI normally strips this from the outgoing text, but when it fails the
    raw block reaches the conversation store. Dropping it keeps the stored
    history equal to what was actually sent.
    """
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)

    if isinstance(content, str):
        if "<thought" not in content.lower() and "<thinking" not in content.lower():
            return msg
        new = _THOUGHT_BLOCK_RE.sub("", content).strip()
        if new == content:
            return msg
        if not new:
            return None
        if isinstance(msg, dict):
            return {**msg, "content": new}
        try:
            return msg.model_copy(update={"content": new})
        except Exception:
            return msg

    if isinstance(content, list):
        changed = False
        new_parts: list[Any] = []
        for part in content:
            text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if isinstance(text, str) and "<thought" in text.lower():
                new_text = _THOUGHT_BLOCK_RE.sub("", text).strip()
                if new_text != text:
                    changed = True
                    if not new_text:
                        continue
                    if isinstance(part, dict):
                        new_parts.append({**part, "text": new_text})
                    else:
                        try:
                            new_parts.append(part.model_copy(update={"text": new_text}))
                        except Exception:
                            new_parts.append(part)
                    continue
            new_parts.append(part)
        if not changed:
            return msg
        if isinstance(msg, dict):
            return {**msg, "content": new_parts}
        try:
            return msg.model_copy(update={"content": new_parts})
        except Exception:
            return msg

    return msg


class MirukuContextGuard(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._stats = {
            "requests": 0,
            "images": 0,
            "chars": 0,
            "revived": 0,
            "dropped_rounds": 0,
            "dropped_chars": 0,
            "outbound_scrubbed": 0,
            "outbound_cleared": 0,
        }

    def _cfg(self, key: str, default: Any) -> Any:
        try:
            value = self.config.get(key, default)
        except Exception:
            return default
        return default if value is None else value

    @filter.on_llm_request()
    async def guard(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        try:
            await self._apply(event, req)
        except Exception as exc:  # never break the reply path
            logger.error("[Miruku context] guard failed: %s", exc, exc_info=True)

    async def _apply(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        contexts = getattr(req, "contexts", None)
        if not isinstance(contexts, list) or not contexts:
            return

        original = list(contexts)
        self._stats["requests"] += 1
        strip_stats = {"images": 0, "chars": 0}
        revive_stats = {"revived": 0}

        # --- 1. strip inline payloads from *history* only -------------------
        if self._cfg("strip_history_images", True):
            contexts = [_strip_message(msg, strip_stats) for msg in contexts]
            self._stats["images"] += strip_stats["images"]
            self._stats["chars"] += strip_stats["chars"]

        # --- 2. revive repr-stringified content back into real part lists ----
        # Runs after the strip so a huge base64 literal is first collapsed to a
        # placeholder: parsing 18K characters is cheap, parsing 2.6M is not.
        if self._cfg("revive_stringified_content", True):
            contexts = [_revive_stringified_content(msg, revive_stats) for msg in contexts]
            self._stats["revived"] += revive_stats["revived"]

        # --- 2. enforce a character budget by dropping oldest rounds --------
        limit = int(self._cfg("max_context_chars", 400000) or 0)
        keep_min = max(1, int(self._cfg("min_keep_rounds", 1) or 1))
        dropped_rounds = 0
        dropped_chars = 0
        dropped_msgs = 0
        if limit > 0:
            total = sum(_content_chars(m.get("content") if isinstance(m, dict) else getattr(m, "content", None)) for m in contexts)
            if total > limit:
                starts = _round_starts(contexts)
                preamble = contexts[: starts[0]]
                rounds = [
                    contexts[starts[i] : (starts[i + 1] if i + 1 < len(starts) else len(contexts))]
                    for i in range(len(starts))
                ]
                while len(rounds) > keep_min and total > limit:
                    oldest = rounds.pop(0)
                    dropped_rounds += 1
                    dropped_msgs += len(oldest)
                    for m in oldest:
                        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
                        dropped_chars += _content_chars(c)
                    total = sum(
                        _content_chars(m.get("content") if isinstance(m, dict) else getattr(m, "content", None))
                        for m in preamble + [x for r in rounds for x in r]
                    )
                contexts = preamble + [m for r in rounds for m in r]
                self._stats["dropped_rounds"] += dropped_rounds
                self._stats["dropped_chars"] += dropped_chars

        changed = strip_stats["images"] or dropped_rounds or revive_stats["revived"]
        if not changed:
            return

        # --- 3. write the trimmed list back to the request ------------------
        try:
            req.contexts = contexts
        except Exception:
            logger.error("[Miruku context] cannot assign contexts; leaving request unchanged")
            return

        # --- 4. remember the real history so the save hook can restore it ---
        self._stash_for_restore(event, original)

        if self._cfg("log_stats", True):
            # Lengths and counts only -- never message text, accounts or prompts.
            logger.info(
                "[Miruku context] stripped_images=%d stripped_chars=%d revived_msgs=%d dropped_rounds=%d dropped_chars=%d remaining_chars=%d",
                strip_stats["images"],
                strip_stats["chars"],
                revive_stats["revived"],
                dropped_rounds,
                dropped_chars,
                sum(_content_chars(m.get("content") if isinstance(m, dict) else getattr(m, "content", None)) for m in contexts),
            )

    def _stash_for_restore(self, event: AstrMessageEvent, original: list[Any]) -> None:
        """Record the untrimmed history so the save hook can put it back.

        A later ``on_llm_request`` hook (EmotionAI) rewrites ``req.contexts`` before
        ``agent_runner.reset()`` runs, so the messages that eventually get saved are
        *its* cleaned version (different count, different content shape). Content
        matching therefore cannot be trusted; the restore step anchors on the message
        count recorded by ``on_agent_begin`` instead.
        """
        if not self._cfg("restore_history_after_request", True):
            return
        if event is None or not hasattr(event, "set_extra"):
            return
        if bind_checkpoint_messages is None:
            logger.warning("[Miruku context] bind_checkpoint_messages unavailable; trimmed history will be saved")
            return
        try:
            original_msgs = bind_checkpoint_messages(original)
            if not original_msgs:
                return
            event.set_extra(_EXTRA_KEY, {"original_msgs": original_msgs})
        except Exception as exc:
            logger.warning("[Miruku context] cannot prepare history restore: %s", exc)

    @filter.on_agent_begin()
    async def remember_begin(self, event: AstrMessageEvent, run_context: Any) -> None:
        """Remember how many messages the agent started with (system + history + turn).

        ``on_agent_begin`` fires once per run, right after ``agent_runner.reset()``
        bound the (possibly rewritten) request contexts, so this count is the boundary
        between "history" and "messages produced during this run".
        """
        try:
            if event is None or not hasattr(event, "set_extra"):
                return
            if event.get_extra(_BEGIN_KEY) is not None:
                return
            messages = getattr(run_context, "messages", None)
            if isinstance(messages, list) and messages:
                turn = messages[-1] if _role_of(messages[-1]) == "user" else None
                event.set_extra(_BEGIN_KEY, {"count": len(messages), "turn": turn})
        except Exception as exc:
            logger.warning("[Miruku context] cannot record agent start: %s", exc)

    @filter.on_agent_done()
    async def restore_history(self, event: AstrMessageEvent, run_context: Any, response: Any) -> None:
        if event is None or not hasattr(event, "get_extra"):
            return

        state = event.get_extra(_EXTRA_KEY)
        begin = event.get_extra(_BEGIN_KEY)
        event.set_extra(_EXTRA_KEY, None)
        event.set_extra(_BEGIN_KEY, None)

        try:
            messages = getattr(run_context, "messages", None)
            if not isinstance(messages, list):
                return

            original_msgs = state.get("original_msgs") if isinstance(state, dict) else None
            if not isinstance(original_msgs, list) or not original_msgs:
                # Nothing was trimmed: the saved list is the live one. Scrub in place.
                self._scrub_into(run_context, messages)
                return

            # Anchor the current turn. EmotionAI's synthetic "（系统自检...）" user
            # turn is the *last* user message in this list, so it must be skipped
            # when choosing the fallback anchor -- otherwise the tail slice starts
            # at the fake turn and the whole injected block is preserved.
            tail_start = -1
            turn = begin.get("turn") if isinstance(begin, dict) else None
            if turn is not None:
                for i, msg in enumerate(messages):
                    if msg is turn:
                        tail_start = i
                        break
            if tail_start < 0:
                for i in range(len(messages) - 1, -1, -1):
                    msg = messages[i]
                    if _role_of(msg) == "user" and not _is_synthetic(msg):
                        tail_start = i
                        break
            if tail_start < 0:
                tail_start = len(messages)

            head: list[Any] = []
            if messages and _role_of(messages[0]) == "system":
                head = [messages[0]]

            tail = messages[tail_start:]
            restored = head + original_msgs + tail
            self._scrub_into(
                run_context,
                restored,
                original_count=len(original_msgs),
                tail_count=len(tail),
                report=True,
            )
        except Exception as exc:
            logger.error("[Miruku context] history restore failed: %s", exc, exc_info=True)

    def _scrub_into(
        self,
        run_context: Any,
        messages: list[Any],
        *,
        original_count: int = 0,
        tail_count: int = 0,
        report: bool = False,
    ) -> None:
        """Drop synthetic turns / inline <thought> blocks, then install the result."""
        dropped = 0
        stripped = 0
        kept: list[Any] = []

        if self._cfg("scrub_injected_turns", True):
            for msg in messages:
                if _is_synthetic(msg):
                    dropped += 1
                    continue
                cleaned = _strip_thought_inline(msg)
                if cleaned is None:
                    stripped += 1
                    continue
                if cleaned is not msg:
                    stripped += 1
                kept.append(cleaned)
        else:
            kept = list(messages)

        try:
            run_context.messages = kept
        except Exception as exc:
            logger.error("[Miruku context] cannot assign messages after scrub: %s", exc)
            return

        if not self._cfg("log_stats", True):
            return
        if report or dropped or stripped:
            logger.info(
                "[Miruku context] history restored for save: original_msgs=%d tail_msgs=%d total_msgs=%d scrubbed_dropped=%d scrubbed_stripped=%d",
                original_count,
                tail_count,
                len(kept),
                dropped,
                stripped,
            )

    @filter.on_decorating_result()
    async def scrub_outbound(self, event: AstrMessageEvent) -> None:
        """Strip internal markup from the outgoing chain.

        Runs on every outbound message, including proactive ones (the
        ``proactive_chat`` plugin dispatches this same event itself). Nothing
        here depends on another plugin's settings.
        """
        if not self._cfg("strip_outbound_marks", True):
            return
        try:
            result = event.get_result()
            if result is None:
                return
            chain = getattr(result, "chain", None)
            if not chain:
                return

            hits: list[str] = []
            kept: list[Any] = []
            emptied = 0
            for comp in chain:
                if Plain is not None and isinstance(comp, Plain):
                    original = comp.text or ""
                    cleaned, found = _strip_outbound_marks(original)
                    hits.extend(found)
                    if not cleaned and original.strip():
                        # The segment was pure internal monologue: drop it
                        # rather than send an empty bubble.
                        emptied += 1
                        continue
                    if cleaned != original:
                        comp.text = cleaned
                kept.append(comp)

            if not hits:
                return

            if not kept:
                # Nothing sendable survived. Cancel the reply instead of
                # delivering an empty message.
                event.clear_result()
                self._stats["outbound_cleared"] += 1
                if self._cfg("log_stats", True):
                    logger.info(
                        "[Miruku outbound] cleared empty reply, marks=%s segments_dropped=%d",
                        ",".join(dict.fromkeys(hits)),
                        emptied,
                    )
                return

            result.chain = kept
            self._stats["outbound_scrubbed"] += 1
            if self._cfg("log_stats", True):
                logger.info(
                    "[Miruku outbound] scrubbed marks=%s segments_dropped=%d kept=%d",
                    ",".join(dict.fromkeys(hits)),
                    emptied,
                    len(kept),
                )
        except Exception as exc:  # never break the reply path
            logger.error("[Miruku outbound] scrub failed: %s", exc, exc_info=True)
