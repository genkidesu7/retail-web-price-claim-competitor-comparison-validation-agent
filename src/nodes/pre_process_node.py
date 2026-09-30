"""AgentCore Platform v1.0"""

# Node contract (agents_layer_design.md §1):
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus enum constants — never plain strings [A1]
#  - Read input_context via state.get("input_context", {}) — read-only [C1]
#  - Never import from mediator/, api/, or other agents

from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.events import emitter
from shared.services.events.types import EventType
from shared.utils.audit_logger import emit_trace_event

# Known Japan EC platforms allow-listed for competitor price lookups.
ALLOWED_PLATFORMS = frozenset({"rakuten", "amazon_jp", "yahoo_shopping", "mercari", "au_pay_market"})


class PreProcessNode(FunctionNode):
    """InputParse — validate required fields and enrich claim input before main processing."""

    # S-1: explicit by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Validating the price claim request...",
            metadata={"stage": "pre_process"},
        )
        input_context = state.get("input_context", {})  # read-only [C1]
        product_sku = input_context.get("product_sku", "")
        own_price = input_context.get("own_price")
        claim_text = input_context.get("claim_text") or state.get("user_input", "")
        target_platforms = input_context.get("target_platforms", [])

        missing = [
            name
            for name, value in (
                ("product_sku", product_sku),
                ("own_price", own_price),
                ("claim_text", claim_text),
                ("target_platforms", target_platforms),
            )
            if not value
        ]
        if missing:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"PreProcessNode: missing required field(s): {', '.join(missing)}"],
            }

        emit_trace_event(
            "input_validated", {"product_sku": product_sku, "platform_count": len(target_platforms)}, state
        )

        return {
            "validated_input": claim_text.strip(),
            "product_sku": product_sku,
            "own_price": own_price,
            "claim_text": claim_text,
            "target_platforms": target_platforms,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2 domain extension: reject negative own_price, empty claim_text,
        and unrecognized target_platforms. Runs after the default PII scan.
        """
        input_context = state.get("input_context", {})

        own_price = input_context.get("own_price")
        if own_price is not None and (not isinstance(own_price, (int, float)) or own_price < 0):
            raise SecurityViolationError("PreProcessNode: own_price must be a non-negative number")

        claim_text = state.get("user_input", "")
        if claim_text is not None and isinstance(claim_text, str) and not claim_text.strip():
            raise SecurityViolationError("PreProcessNode: claim_text must not be empty")

        target_platforms = input_context.get("target_platforms") or []
        unknown = [p for p in target_platforms if p not in ALLOWED_PLATFORMS]
        if unknown:
            raise SecurityViolationError(f"PreProcessNode: unrecognized target platform(s): {', '.join(unknown)}")

        return state
