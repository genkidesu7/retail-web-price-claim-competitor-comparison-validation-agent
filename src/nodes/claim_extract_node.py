"""AgentCore Platform v1.0"""

# Inner graph node (src/graph/domain_workflow_graph.py pipeline).
# PriceClaimExtract — uses the shared LLM service to extract and classify
# price claims from the raw claim text into 3 types:
#   最安値/最低価格 (lowest price), 通常価格 MSRP, 割引率 (discount rate)

from __future__ import annotations

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.services.events import emitter
from shared.services.events.types import EventType
from shared.utils.audit_logger import emit_trace_event

from src.services.service import call_llm

CLAIM_TYPES = ("最安値/最低価格", "通常価格", "割引率")

_EXTRACT_PROMPT = """You are a compliance assistant. Extract every price claim from the \
marketing copy below and classify each into exactly one of these types: \
最安値/最低価格 (lowest/cheapest price claim), 通常価格 (regular/MSRP price claim), \
割引率 (discount rate claim).

For each claim, return a verbatim quote from the source text and the numeric value \
stated (price in JPY or percentage for discount claims).

Respond ONLY with a JSON array of objects shaped exactly as:
[{{"claim_type": "<one of the 3 types above>", "quote": "<verbatim quote>", "stated_value": <number>}}]
If no price claims are present, respond with [].

Marketing copy:
{text}
"""


class ClaimExtractNode(FunctionNode):
    """PriceClaimExtract — inner graph entry node."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Extracting price claims from the marketing copy...",
            metadata={"stage": "claim_extract"},
        )
        # Inner-graph fallback rule (mandatory): validated_input is not carried
        # over by GraphNode.execute() -> subgraph.invoke(user_input, ...).
        text = state.get("validated_input", state.get("user_input", "")) or state.get("claim_text", "")

        if not text:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ClaimExtractNode: no claim text available"],
            }

        ctx = InvocationContext.from_state(state)
        content = call_llm("claim_extract", _EXTRACT_PROMPT.format(text=text), ctx.secrets)
        claims = _parse_claims(content)

        emit_trace_event("price_claim_extracted", {"claim_count": len(claims)}, state)

        # product_sku / own_price / target_platforms are forwarded into inner
        # state by PriceValidationWorkflowGraph._extra_initial_state() (populated
        # from PriceValidationGraphNode._parent_config()) — pass them through
        # unchanged so downstream inner nodes (competitor_fetch, compliance_check)
        # can read them via state.get(...).
        return {
            "claims": claims,
            "product_sku": state.get("product_sku", ""),
            "own_price": state.get("own_price"),
            "target_platforms": state.get("target_platforms", []),
            "status": AgentStatus.SUCCESS.value,
        }


def _parse_claims(content: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    claims: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        claim_type = item.get("claim_type")
        quote = item.get("quote")
        stated_value = item.get("stated_value")
        if claim_type in CLAIM_TYPES and isinstance(quote, str) and isinstance(stated_value, (int, float)):
            claims.append({"claim_type": claim_type, "quote": quote, "stated_value": stated_value})
    return claims
