"""Attach the existing local knowledge block to one private LLM request."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.provider.entities import ProviderRequest


MARK = "<!-- miruku-knowledge -->"


class MirukuKnowledge(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._build_block = None
        self._root = None
        # DS-06 的 F3：原来三条早退（会话不匹配 / MARK 已存在 / 空消息）完全静默，
        # `target_qq` 打错一位、`platform_id` 写错、`knowledge_root` 指错目录
        # 都会永远不注入且没有任何信号，接通后只能靠猜。
        # 这里只记**计数 + 原因**，永远不打消息正文、不打 QQ 号全量。
        self._stats = {
            "hit": 0,
            "skip_chat": 0,
            "skip_duplicate": 0,
            "skip_empty": 0,
            "skip_no_block": 0,
            "error": 0,
        }
        self._armed_logged = False

    def _bump(self, key: str) -> None:
        """计数。用 getattr 兜住「没走 __init__」的构造方式（探针会 object.__new__）。"""
        stats = getattr(self, "_stats", None)
        if stats is None:
            stats = self._stats = {
                "hit": 0,
                "skip_chat": 0,
                "skip_duplicate": 0,
                "skip_empty": 0,
                "skip_no_block": 0,
                "error": 0,
            }
        stats[key] = stats.get(key, 0) + 1

    def _load_builder(self):
        raw = str(self.config.get("knowledge_root", "")).strip()
        # DS-06 的 F6：空串会让 Path("") 退化成当前目录（`.`），
        # 恰好有同名库时就会读错库。宁可显式报错，也不要靠运气。
        if not raw:
            raise FileNotFoundError("knowledge_root is empty")
        root = Path(raw)
        # 校验和下面传给 build_block 的必须是**同一个路径**（DS-06 的 F5）。
        db_path = root / "miruku_knowledge.sqlite3"
        if not root.is_dir() or not db_path.is_file():
            raise FileNotFoundError("configured Miruku knowledge database is missing")
        if self._build_block is not None and root == self._root:
            return self._build_block
        # inject.py imports its sibling query.py. Keep the existing asset as the
        # only source of scoring and do not copy the database into the plugin.
        module_name = "miruku_runtime_knowledge_inject"
        spec = importlib.util.spec_from_file_location(module_name, root / "inject.py")
        if spec is None or spec.loader is None:
            raise ImportError("cannot load Miruku knowledge injector")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._build_block = module.build_block
        self._root = root
        return self._build_block

    def _matches(self, event: AstrMessageEvent) -> bool:
        target = str(self.config.get("target_qq", "")).strip()
        return (
            bool(target)
            and event.is_private_chat()
            and event.get_platform_id() == self.config.get("platform_id", "miruku")
            and event.get_sender_id() == target
        )

    @filter.on_llm_request()
    async def add_knowledge(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self._matches(event):
            self._bump("skip_chat")
            return
        if MARK in (req.system_prompt or ""):
            self._bump("skip_duplicate")
            return
        message = event.message_str or ""
        if not message.strip():
            self._bump("skip_empty")
            return
        try:
            # 显式传 db_path：校验过的那个库和实际读的必须是同一个文件。
            # 不传时 build_block 会退回 query.DEFAULT_DB，而 query 一旦已经在
            # sys.modules 里（换 knowledge_root 后重载插件），就会读旧目录的库。
            block = self._load_builder()(
                message, db_path=str(self._root / "miruku_knowledge.sqlite3")
            )
        except Exception as exc:
            # Retrieval failure must not take down the normal reply. Never log
            # the message text, prompt, account, or full exception payload.
            self._bump("error")
            logger.error("[Miruku knowledge] lookup failed: %s", type(exc).__name__)
            return
        if not block:
            self._bump("skip_no_block")
            logger.debug("[Miruku knowledge] no block for this message")
            return
        req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n" + MARK
        self._bump("hit")
        if not getattr(self, "_armed_logged", False):
            # 只在一生中打一次：证明钩子真的走到过注入分支。
            # 不打 target_qq / platform_id / 消息正文，只打平台与「已装弹」。
            self._armed_logged = True
            logger.info(
                "[Miruku knowledge] armed: platform=%s, injections=1",
                self.config.get("platform_id", "miruku"),
            )
