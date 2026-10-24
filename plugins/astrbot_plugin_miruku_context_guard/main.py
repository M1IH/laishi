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

import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.provider.entities import ProviderRequest

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


def _content_chars(content: Any) -> int:
    """Approximate payload size of one message's content."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict):
                holder = part.get("image_url") or part.get("audio_url") or {}
                url = holder.get("url") if isinstance(holder, dict) else None
                if isinstance(url, str):
                    total += len(url)
                else:
                    total += len(str(part.get("text", "")))
            else:
                holder = getattr(part, "image_url", None) or getattr(part, "audio_url", None)
                url = getattr(holder, "url", None)
                if isinstance(url, str):
                    total += len(url)
                else:
                    total += len(getattr(part, "text", "") or getattr(part, "think", "") or "")
        return total
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


class MirukuContextGuard(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._stats = {"requests": 0, "images": 0, "chars": 0, "dropped_rounds": 0, "dropped_chars": 0}

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

        # --- 1. strip inline payloads from *history* only -------------------
        if self._cfg("strip_history_images", True):
            contexts = [_strip_message(msg, strip_stats) for msg in contexts]
            self._stats["images"] += strip_stats["images"]
            self._stats["chars"] += strip_stats["chars"]

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

        changed = strip_stats["images"] or dropped_rounds
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
                "[Miruku context] stripped_images=%d stripped_chars=%d dropped_rounds=%d dropped_chars=%d remaining_chars=%d",
                strip_stats["images"],
                strip_stats["chars"],
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
        if not isinstance(state, dict):
            return
        event.set_extra(_EXTRA_KEY, None)
        event.set_extra(_BEGIN_KEY, None)
        try:
            messages = getattr(run_context, "messages", None)
            original_msgs = state.get("original_msgs") or []
            if not isinstance(messages, list) or not original_msgs:
                return

            # Anchor the current turn. Identity is the strongest signal (a later hook
            # may rewrite content or drop unrelated messages); fall back to the last
            # user message, which is the turn being answered.
            tail_start = -1
            turn = begin.get("turn") if isinstance(begin, dict) else None
            if turn is not None:
                for i, msg in enumerate(messages):
                    if msg is turn:
                        tail_start = i
                        break
            if tail_start < 0:
                for i in range(len(messages) - 1, -1, -1):
                    if _role_of(messages[i]) == "user":
                        tail_start = i
                        break
            if tail_start < 0:
                tail_start = len(messages)

            head: list[Any] = []
            if messages and _role_of(messages[0]) == "system":
                head = [messages[0]]

            restored = head + original_msgs + messages[tail_start:]
            run_context.messages = restored
            if self._cfg("log_stats", True):
                # Counts only: how much of her real history was kept.
                logger.info(
                    "[Miruku context] history restored for save: original_msgs=%d tail_msgs=%d total_msgs=%d",
                    len(original_msgs),
                    len(messages) - tail_start,
                    len(restored),
                )
        except Exception as exc:
            logger.error("[Miruku context] history restore failed: %s", exc, exc_info=True)
