"""AgentCore Platform v1.0"""

# Inner graph node (src/graph/domain_workflow_graph.py pipeline).
# ValidationReport — assembles per-claim verdict, evidence, 景品表示法 article
# citation, and remediation recommendation. Emits the primary audit record
# (compliance_verdict_issued) for 消費者庁 inquiry evidence.

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.events import emitter
from shared.services.events.types import EventType
from shared.utils.audit_logger import emit_trace_event

_ARTICLE_CITATION = "景品表示法第5条（優良誤認表示・有利誤認表示）"

_REMEDIATION = {
    "VIOLATION": "Remove or correct the claim before publication; consult legal counsel.",
    "WARNING": "Review claim wording and supporting evidence before publication.",
    "PASS": "No action required.",
    "INSUFFICIENT DATA": "Re-run competitor price collection before publishing this claim.",
}


class ReportAssembleNode(FunctionNode):
    """ValidationReport — inner graph node (final step)."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Assembling the validation report...",
            metadata={"stage": "report_assemble"},
        )
        rule_check_results = state.get("rule_check_results", [])
        min_competitor_count_met = state.get("min_competitor_count_met", True)

        validation_results = []
        for check in rule_check_results:
            verdict = check.get("verdict", "WARNING")
            claim_type = check.get("claim_type")

            # Missing/insufficient competitor data for a 最安値 claim is a
            # per-claim data-sufficiency outcome, not a graph-level route.
            if claim_type == "最安値/最低価格" and not min_competitor_count_met:
                verdict = "INSUFFICIENT DATA"

            report = {
                "claim_text": check.get("quote"),
                "claim_type": claim_type,
                "verdict": verdict,
                "evidence": check.get("rationale"),
                "article": _ARTICLE_CITATION,
                "recommendation": _REMEDIATION.get(verdict, _REMEDIATION["WARNING"]),
            }
            validation_results.append(report)
            emit_trace_event("compliance_verdict_issued", report, state)

        return {
            "validation_results": validation_results,
            "status": AgentStatus.SUCCESS.value,
        }
