# -*- coding: utf-8 -*-
"""Miruku 出站闸门（C-12 / C-14 / L3 编造成绩共用一层）。

判定与验收见 docs/outbound-guard-verdict.md：
- 四层全不重生成，分层改写（L1 剥离 / L2 删承诺句 / L2.5 改动词 / L3 删数字降级）。
- 必须挂 on_agent_done：它是唯一同时拿到 run_context 与 llm_response 的钩子。
  只改 resp 不改历史 → 下一轮模型会看见自己说过违规的话（当面一套背后一套）。
- 主动消息绕过 agent 管线（proactive 直连 provider），改挂 on_decorating_result
  在发送前对 result.chain 里的 Plain 再过一遍（guard 幂等，已干净则零改动）。

隐私铁律：日志只打类别计数，不打消息正文。
"""
import os
import sys
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.agent.message import TextPart
from astrbot.core.message.message_event_result import MessageChain, ResultContentType

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# 必须先设再 import：outbound_core 模块级 TRUTH_PATH/SONGLIST_PATH 在 import 时
# 就固化 _data_dir() 结果，晚设环境变量会让它缓存到不存在的回退路径（songs=0 的根因）。
os.environ.setdefault("OUTBOUND_DATA_DIR", "/AstrBot/data/plugin_data/miruku_outbound")

import outbound_core as outbound  # noqa: E402

PROD_DATA_DIR = "/AstrBot/data/plugin_data/miruku_outbound"
PLATFORM = "miruku"  # 只对 QQ 平台生效；webchat/其他跳过


class OutboundGuard(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.stats = {
            "agent_rewritten": 0,
            "agent_fallback": 0,
            "agent_blocked": 0,
            "decorating_rewritten": 0,
            "decorating_fallback": 0,
            "decorating_blocked": 0,
        }
        try:
            songs = outbound.song_levels()
            truth = outbound._load_truth()
        except Exception as e:  # 真值表缺失不炸插件，L3 退化为纯范围检查
            logger.error(f"[miruku_outbound] 真值/曲库加载失败: {e!r}")
            songs, truth = {}, {}
        logger.info(
            f"[miruku_outbound] armed: platform={PLATFORM} "
            f"songs={len(songs)} truth_keys={len(truth)} data_dir={outbound._data_dir()}"
        )

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _active(event: AstrMessageEvent) -> bool:
        try:
            return event.get_platform_name() == PLATFORM
        except Exception:
            return False

    @staticmethod
    def _patch_history(run_context, text: str) -> bool:
        """把历史里最后一条 assistant 的 TextPart 同步成改写后文本。

        messages[-1] 在有工具调用的轮次里不一定是那条 assistant 文本消息，
        必须从后往前找（verdict §五）。
        """
        messages = getattr(run_context, "messages", None) or []
        for msg in reversed(messages):
            if getattr(msg, "role", None) != "assistant":
                continue
            for part in getattr(msg, "content", None) or []:
                if isinstance(part, TextPart):
                    try:
                        part.text = text
                        return True
                    except Exception as e:
                        logger.error(f"[miruku_outbound] 历史改写失败: {e!r}")
                        return False
        return False

    @staticmethod
    def _clean_chain(chain):
        """对 chain（str / MessageChain / list）里的 Plain 过一遍 guard。

        返回 (chain, changed, used_fallback)；chain 保持原容器类型。
        """
        changed = False
        used_fallback = False
        blocked_count = 0

        def _fix(text: str):
            nonlocal changed, used_fallback, blocked_count
            outcome = outbound.guard3(text)
            if outcome.state == "blocked":
                # C-23：原文非空、清洗后为空 = 整条都是内部标记。
                # 退回原文等于把 <thought>/[Profile:] 原样发出去，必须清空这一段。
                blocked_count += 1
                changed = True
                return ""
            if not outcome.sendable:
                return text  # 本来就没内容，保持原样
            if outcome.text != text:
                changed = True
            used_fallback = used_fallback or outcome.used_fallback
            return outcome.text

        if isinstance(chain, str):
            fixed = _fix(chain)
            return fixed, changed, used_fallback
        if isinstance(chain, MessageChain):
            for comp in chain.chain:
                if isinstance(comp, Plain) and comp.text:
                    comp.text = _fix(comp.text)
            return chain, changed, used_fallback
        if isinstance(chain, list):
            for comp in chain:
                if isinstance(comp, Plain) and comp.text:
                    comp.text = _fix(comp.text)
            return chain, changed, used_fallback
        return chain, changed, used_fallback

    # --------------------------------------------------------------- hooks

    @filter.on_agent_done(priority=1)  # 1 < emotionai 100000 → 晚跑，能清掉它追加的情感状态
    async def guard_agent_done(self, event: AstrMessageEvent, run_context, resp):
        if not self._active(event):
            return
        text = getattr(resp, "completion_text", None)
        if not text or not text.strip():
            return
        try:
            outcome = outbound.guard3(text)
        except Exception as e:
            logger.error(f"[miruku_outbound] guard 异常(放行原文): {e!r}")
            return
        if outcome.state == "blocked":
            # C-23：整条都是内部标记。既不能发原文，也不能发空消息——阻断发送。
            # stop_event 会让 respond 阶段不再送出这条 result。
            event.stop_event()
            resp.completion_text = ""
            self._patch_history(run_context, "")
            self.stats["agent_blocked"] += 1
            logger.warning(
                f"[miruku_outbound] agent_done 阻断：清洗后无正文 "
                f"(history_cleared=True, count={self.stats['agent_blocked']})"
            )
            return
        if not outcome.sendable:
            return  # 本来就没内容，无需动作
        fixed = outcome.text
        used_fallback = outcome.used_fallback
        if fixed == text:
            return
        resp.completion_text = fixed
        patched = self._patch_history(run_context, fixed)
        if used_fallback:
            self.stats["agent_fallback"] += 1
            logger.info(
                f"[miruku_outbound] agent_done 兜底改写 (history_patched={patched}, "
                f"count={self.stats['agent_fallback']})"
            )
        else:
            self.stats["agent_rewritten"] += 1
            logger.info(
                f"[miruku_outbound] agent_done 改写 (history_patched={patched}, "
                f"count={self.stats['agent_rewritten']})"
            )

    @filter.on_decorating_result(priority=1)
    async def guard_decorating(self, event: AstrMessageEvent):
        """主动消息绕过 agent 管线，只在 decorating 拦截；对已干净的文本幂等。"""
        if not self._active(event):
            return
        result = event.get_result()
        if not result:
            return
        if getattr(result, "result_content_type", None) == ResultContentType.STREAMING_RESULT:
            return  # 流式增量已发出，改不了；其余类型链路文本还在 chain 里
        chain = getattr(result, "chain", None)
        if chain is None:
            return
        try:
            fixed_chain, changed, used_fallback = self._clean_chain(chain)
        except Exception as e:
            logger.error(f"[miruku_outbound] decorating guard 异常(放行原文): {e!r}")
            return
        if not changed:
            return
        result.chain = fixed_chain
        # C-23：若整条链的 Plain 都被判 blocked（清成空串），链里已经没有可发正文。
        # 只保留图片/表情等非文本段；纯文本全空时阻断发送，不发空消息也不发原文。
        remaining_text = "".join(
            getattr(comp, "text", "") or ""
            for comp in (
                fixed_chain.chain if isinstance(fixed_chain, MessageChain)
                else fixed_chain if isinstance(fixed_chain, list)
                else []
            )
            if isinstance(comp, Plain)
        ).strip()
        has_non_text = any(
            not isinstance(comp, Plain)
            for comp in (
                fixed_chain.chain if isinstance(fixed_chain, MessageChain)
                else fixed_chain if isinstance(fixed_chain, list)
                else []
            )
        )
        if not remaining_text and not has_non_text:
            event.stop_event()
            self.stats["decorating_blocked"] += 1
            logger.warning(
                f"[miruku_outbound] decorating 阻断：清洗后无正文 "
                f"(count={self.stats['decorating_blocked']})"
            )
            return
        if used_fallback:
            self.stats["decorating_fallback"] += 1
            logger.info(
                f"[miruku_outbound] decorating 兜底改写 (count={self.stats['decorating_fallback']})"
            )
        else:
            self.stats["decorating_rewritten"] += 1
            logger.info(
                f"[miruku_outbound] decorating 改写 (count={self.stats['decorating_rewritten']})"
            )
