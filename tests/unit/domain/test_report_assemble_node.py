"""Unit tests for ReportAssembleNode (ValidationReport) — BL-11, BL-12."""

from __future__ import annotations

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes.report_assemble_node import ReportAssembleNode
from tests.conftest import base_state


@pytest.fixture
def node():
    return ReportAssembleNode()


class TestBL11InsufficientDataVerdict:
    """BL-11: INSUFFICIENT DATA verdict when competitor data insufficient."""

    def test_lowest_price_claim_with_insufficient_data_downgrades_verdict(self, node):
        state = base_state(
            rule_check_results=[
                {
                    "claim_type": "最安値/最低価格",
                    "quote": "業界最安値",
                    "stated_value": 2980,
                    "verdict": "PASS",
                    "rationale": "arithmetic pass",
                }
            ],
            min_competitor_count_met=False,
        )
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        entry = result["validation_results"][0]
        assert entry["verdict"] == "INSUFFICIENT DATA"

    def test_non_lowest_price_claim_not_affected_by_insufficient_data_flag(self, node):
        state = base_state(
            rule_check_results=[
                {
                    "claim_type": "通常価格",
                    "quote": "通常価格5000円",
                    "stated_value": 5000,
                    "verdict": "PASS",
                    "rationale": "arithmetic pass",
                }
            ],
            min_competitor_count_met=False,
        )
        result = node.execute(state)
        entry = result["validation_results"][0]
        assert entry["verdict"] == "PASS"

    def test_sufficient_data_preserves_verdict(self, node):
        state = base_state(
            rule_check_results=[
                {
                    "claim_type": "最安値/最低価格",
                    "quote": "業界最安値",
                    "stated_value": 2980,
                    "verdict": "PASS",
                    "rationale": "arithmetic pass",
                }
            ],
            min_competitor_count_met=True,
        )
        result = node.execute(state)
        entry = result["validation_results"][0]
        assert entry["verdict"] == "PASS"


class TestBL12ArticleCitationAndRecommendation:
    """BL-12: 景品表示法 article citation + remediation recommendation included."""

    def test_validation_results_include_article_and_recommendation(self, node):
        state = base_state(
            rule_check_results=[
                {
                    "claim_type": "最安値/最低価格",
                    "quote": "業界最安値",
                    "stated_value": 2980,
                    "verdict": "VIOLATION",
                    "rationale": "own_price exceeds competitor minimum",
                }
            ],
            min_competitor_count_met=True,
        )
        result = node.execute(state)
        entry = result["validation_results"][0]
        assert "article" in entry and entry["article"]
        assert "景品表示法" in entry["article"]
        assert "recommendation" in entry and entry["recommendation"]

    def test_recommendation_varies_by_verdict(self, node):
        state = base_state(
            rule_check_results=[
                {"claim_type": "通常価格", "quote": "q1", "stated_value": 1, "verdict": "VIOLATION", "rationale": "r"},
                {"claim_type": "通常価格", "quote": "q2", "stated_value": 2, "verdict": "PASS", "rationale": "r"},
            ],
            min_competitor_count_met=True,
        )
        result = node.execute(state)
        recs = {entry["verdict"]: entry["recommendation"] for entry in result["validation_results"]}
        assert recs["VIOLATION"] != recs["PASS"]


class TestReportAssembleEmitsAuditEvent:
    def test_emits_compliance_verdict_issued_per_claim(self, node, monkeypatch):
        import src.nodes.report_assemble_node as module

        events = []
        monkeypatch.setattr(module, "emit_trace_event", lambda et, payload, state: events.append(et))

        state = base_state(
            rule_check_results=[
                {"claim_type": "通常価格", "quote": "q1", "stated_value": 1, "verdict": "PASS", "rationale": "r"},
                {"claim_type": "通常価格", "quote": "q2", "stated_value": 2, "verdict": "PASS", "rationale": "r"},
            ],
            min_competitor_count_met=True,
        )
        node.execute(state)
        assert events.count("compliance_verdict_issued") == 2
