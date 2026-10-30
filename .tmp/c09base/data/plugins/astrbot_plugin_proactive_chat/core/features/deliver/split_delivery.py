"""DELIVER 阶段默认功能：发送主动消息（含装饰/分段/TTS）。"""

from __future__ import annotations

from typing import Any

from astrbot.api import logger

from ...domain.domain_enums import HookPoint, StageResult
from ...pipeline.stage_protocol import BaseStage


class DeliverStage(BaseStage):
    """消息投递阶段。"""

    name = "deliver_stage"
    hook = HookPoint.DELIVER
    priority = 10

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator

    async def handle(self, ctx) -> StageResult:
        """投递主动消息（C-09 四级判定）。

        partial / all_segments_accepted：至少一段被平台接受——照常存档计数
        （partial 口径认「出去过」，不补发），并把投递结果传给 RECORD；
        只有 skipped / attempted（0 段出去）才 abort 重调度。
        """
        plugin = self.orchestrator.plugin
        session_id = ctx.session_id
        # extra 承载上游阶段产出的待发送内容。
        extra = getattr(ctx, "extra", {}) or {}

        outcome = await plugin.sender_service.send_proactive_message(
            session_id,
            extra.get("response_text", ""),
            event=ctx.event,
            initial_chain=extra.get("result_chain"),
        )
        status = getattr(outcome, "status", None)
        if status in ("partial", "all_segments_accepted"):
            extra["delivery_outcome"] = outcome
            if status == "partial":
                logger.warning(
                    f"[主动消息] {plugin.session_service.get_session_log_str(session_id)} 的本次主动消息部分送达"
                    f"（{getattr(outcome, 'segment_count_sent', '?')}/"
                    f"{getattr(outcome, 'segment_count_planned', '?')} 段，失败段 "
                    f"{getattr(outcome, 'segment_index_failed', [])}），已照常存档计数喵。"
                )
            return StageResult.CONTINUE
        logger.warning(
            f"[主动消息] {plugin.session_service.get_session_log_str(session_id)} 的本次主动消息未能送达"
            f"（{status}），已跳过存档与计数并重新调度喵。"
        )
        ctx.abort("send_failed")
        return StageResult.RESCHEDULE


class SplitDeliveryFeature:
    """DELIVER 阶段功能（默认发送行为）。"""

    name = "split_delivery_feature"

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator

    def register(self, registry) -> None:
        registry.add_stage(
            hook=HookPoint.DELIVER, stage=DeliverStage(self.orchestrator), priority=10
        )
