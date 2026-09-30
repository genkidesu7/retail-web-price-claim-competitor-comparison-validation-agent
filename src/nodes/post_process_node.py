"""AgentCore Platform v1.0"""

from typing import Any, ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.events import emitter
from shared.services.events.types import EventType
from shared.utils.audit_logger import emit_trace_event

DISCLAIMER = (
    "This compliance assessment is generated automatically and does not "
    "constitute legal advice. Please confirm with legal counsel before "
    "publishing any price claim."
)


class PostProcessNode(FunctionNode):
    """ResponseValidate — format and finalize the output."""

    # S-1: explicit by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Finalizing the validation result...",
            metadata={"stage": "post_process"},
        )
        validation_results = state.get("validation_results", [])
        min_competitor_count_met = state.get("min_competitor_count_met", True)

        # Attach the outer state's evidence flag onto each per-claim entry so
        # the S-3 output gate can verify it without re-reading state.
        annotated_results = [
            {**entry, "min_competitor_count_met": min_competitor_count_met} for entry in validation_results
        ]

        result = {
            "product_sku": state.get("product_sku", ""),
            "claims": state.get("claims", []),
            "competitor_prices": state.get("competitor_prices", {}),
            "validation_results": annotated_results,
        }

        emit_trace_event("final_response_audit", {"claim_count": len(validation_results)}, state)

        return {
            "result": result,
            "disclaimer": DISCLAIMER,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3 domain extension: block any PASS verdict lacking
        min_competitor_count_met evidence (prevents false-assurance PASS
        verdicts per the proposal's top risk). Runs after the default
        credential scan.
        """
        payload = result.get("result", {}) or {}
        validation_results = payload.get("validation_results", []) or []
        for entry in validation_results:
            if entry.get("verdict") == "PASS" and entry.get("min_competitor_count_met") is not True:
                raise SecurityViolationError(
                    "PostProcessNode: S-3 blocked PASS verdict lacking "
                    "min_competitor_count_met evidence — false-assurance risk"
                )
        return result
