"""AgentCore Platform v1.0"""

# Inner graph node (src/graph/domain_workflow_graph.py pipeline).
# ComplianceRuleCheck — arithmetic checks (own_price vs competitors, MSRP vs
# 1.5x median, discount rate correctness); borderline cases escalate to
# EnforcementCaseKBService + shared LLM Service for reasoning.

from __future__ import annotations

import asyncio
import json
import statistics
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.services.events import emitter
from shared.services.events.types import EventType
from shared.utils.audit_logger import emit_trace_event

from src.services.enforcement_case_kb_service import EnforcementCaseKBService
from src.services.service import call_llm

LOWEST_PRICE_CLAIM_TYPE = "最安値/最低価格"
MSRP_CLAIM_TYPE = "通常価格"
DISCOUNT_CLAIM_TYPE = "割引率"
MSRP_MULTIPLIER = 1.5
# Verdicts within this fractional margin of the arithmetic boundary are
# considered borderline and escalate to KB precedent + LLM reasoning.
BORDERLINE_MARGIN = 0.05

_REASONING_PROMPT = """A retail price claim needs a compliance judgement under Japan's \
景品表示法 (Act against Unjustifiable Premiums and Misleading Representations).

Claim type: {claim_type}
Claim quote: {quote}
Stated value: {stated_value}
Own price: {own_price}
Competitor prices: {competitor_prices}
Relevant enforcement precedents: {precedents}

Respond ONLY with a JSON object: {{"verdict": "VIOLATION" | "WARNING" | "PASS", "rationale": "<short reasoning>"}}
"""


class ComplianceCheckNode(FunctionNode):
    """ComplianceRuleCheck — inner graph node."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Checking claims against 景品表示法 rules...",
            metadata={"stage": "compliance_check"},
        )
        claims = state.get("claims", [])
        competitor_prices = state.get("competitor_prices", {})
        own_price = state.get("own_price")

        ctx = InvocationContext.from_state(state)

        rule_check_results = []
        for claim in claims:
            result = self._check_claim(claim, own_price, competitor_prices, ctx)
            rule_check_results.append(result)

        emit_trace_event(
            "compliance_check_completed", {"claim_count": len(claims), "result_count": len(rule_check_results)}, state
        )

        return {
            "rule_check_results": rule_check_results,
            "status": AgentStatus.SUCCESS.value,
        }

    def _check_claim(
        self,
        claim: dict[str, Any],
        own_price: float | None,
        competitor_prices: dict[str, float],
        ctx: InvocationContext,
    ) -> dict[str, Any]:
        claim_type = claim.get("claim_type")
        stated_value = claim.get("stated_value")
        prices = list(competitor_prices.values())

        if claim_type == LOWEST_PRICE_CLAIM_TYPE:
            verdict, margin = self._check_lowest_price(own_price, prices)
        elif claim_type == MSRP_CLAIM_TYPE:
            verdict, margin = self._check_msrp(stated_value, prices)
        elif claim_type == DISCOUNT_CLAIM_TYPE:
            verdict, margin = self._check_discount(stated_value, own_price, prices)
        else:
            verdict, margin = "WARNING", 0.0

        if margin is not None and abs(margin) <= BORDERLINE_MARGIN:
            verdict, rationale = self._escalate_borderline(claim, own_price, competitor_prices, ctx)
        else:
            rationale = f"Arithmetic check: {verdict} (margin={margin})"

        return {
            "claim_type": claim_type,
            "quote": claim.get("quote"),
            "stated_value": stated_value,
            "verdict": verdict,
            "rationale": rationale,
        }

    def _check_lowest_price(self, own_price: float | None, competitor_prices: list[float]) -> tuple[str, float | None]:
        if own_price is None or not competitor_prices:
            return "WARNING", None
        min_competitor = min(competitor_prices)
        if own_price <= min_competitor:
            return "PASS", (min_competitor - own_price) / min_competitor if min_competitor else 0.0
        return "VIOLATION", (min_competitor - own_price) / min_competitor if min_competitor else 0.0

    def _check_msrp(self, stated_value: float | None, competitor_prices: list[float]) -> tuple[str, float | None]:
        if stated_value is None or not competitor_prices:
            return "WARNING", None
        median = statistics.median(competitor_prices)
        threshold = median * MSRP_MULTIPLIER
        margin = (threshold - stated_value) / threshold if threshold else 0.0
        return ("PASS" if stated_value <= threshold else "VIOLATION"), margin

    def _check_discount(
        self, stated_value: float | None, own_price: float | None, competitor_prices: list[float]
    ) -> tuple[str, float | None]:
        if stated_value is None or own_price is None or not competitor_prices:
            return "WARNING", None
        median = statistics.median(competitor_prices)
        if median <= 0:
            return "WARNING", None
        actual_discount_pct = (median - own_price) / median * 100
        margin = (actual_discount_pct - stated_value) / stated_value if stated_value else 0.0
        return ("PASS" if actual_discount_pct >= stated_value else "VIOLATION"), margin

    def _escalate_borderline(
        self,
        claim: dict[str, Any],
        own_price: float | None,
        competitor_prices: dict[str, float],
        ctx: InvocationContext,
    ) -> tuple[str, str]:
        kb_service = EnforcementCaseKBService()
        precedents = asyncio.run(kb_service.search_precedents(claim.get("claim_type", ""), claim))

        prompt = _REASONING_PROMPT.format(
            claim_type=claim.get("claim_type"),
            quote=claim.get("quote"),
            stated_value=claim.get("stated_value"),
            own_price=own_price,
            competitor_prices=competitor_prices,
            precedents=precedents,
        )
        content = call_llm("compliance_reasoning", prompt, ctx.secrets)

        try:
            parsed = json.loads(content)
            verdict = parsed.get("verdict", "WARNING")
            rationale = parsed.get("rationale", "LLM reasoning unavailable")
        except (json.JSONDecodeError, TypeError, AttributeError):
            verdict, rationale = "WARNING", "LLM response could not be parsed"

        return verdict, rationale
