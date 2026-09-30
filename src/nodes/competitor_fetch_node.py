"""AgentCore Platform v1.0"""

# Inner graph node (src/graph/domain_workflow_graph.py pipeline).
# CompetitorPriceFetch — calls ScraplingPriceService for live Japan EC
# competitor prices; validates min_competitor_count >= 3 for 最安値 claims.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.events import emitter
from shared.services.events.types import EventType
from shared.utils.audit_logger import emit_trace_event

from src.services.scrapling_price_service import ScraplingPriceService

MIN_COMPETITOR_COUNT = 3
LOWEST_PRICE_CLAIM_TYPE = "最安値/最低価格"


class CompetitorFetchNode(FunctionNode):
    """CompetitorPriceFetch — inner graph node."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Fetching competitor prices...",
            metadata={"stage": "competitor_fetch"},
        )
        claims = state.get("claims", [])
        target_platforms = state.get("target_platforms", [])
        # Inner-graph fallback rule: mirror validated_input access pattern for
        # any input-text consumers; this node consumes claims/platforms instead,
        # already forwarded by claim_extract via _extra_initial_state()/state passthrough.

        service = ScraplingPriceService()
        competitor_prices = asyncio.run(service.fetch_competitor_prices(state.get("product_sku", ""), target_platforms))

        has_lowest_price_claim = any(c.get("claim_type") == LOWEST_PRICE_CLAIM_TYPE for c in claims)
        min_competitor_count_met = len(competitor_prices) >= MIN_COMPETITOR_COUNT if has_lowest_price_claim else True

        fetch_timestamp = datetime.now(UTC).isoformat()

        emit_trace_event(
            "competitor_prices_fetched",
            {"fetch_timestamp": fetch_timestamp, "platform_count": len(competitor_prices)},
            state,
        )

        return {
            "competitor_prices": competitor_prices,
            "fetch_timestamp": fetch_timestamp,
            "min_competitor_count_met": min_competitor_count_met,
            "status": AgentStatus.SUCCESS.value,
        }
