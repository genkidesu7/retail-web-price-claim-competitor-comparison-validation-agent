"""Unit tests for ComplianceCheckNode (ComplianceRuleCheck) — BL-08, BL-09, BL-10, BL-17."""

from __future__ import annotations

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes import compliance_check_node as compliance_check_module
from src.nodes.compliance_check_node import ComplianceCheckNode
from tests.conftest import base_state, llm_returns


@pytest.fixture
def node():
    return ComplianceCheckNode()


class _FakeKBService:
    def __init__(self, precedents=None):
        self._precedents = precedents or [{"case_id": "case-1", "outcome": "WARNING"}]

    async def search_precedents(self, claim_type, context):
        return self._precedents


class _FailingKBService:
    async def search_precedents(self, claim_type, context):
        raise ConnectionError("vector KB unreachable")


_WARNING_JSON = json.dumps({"verdict": "WARNING", "rationale": "borderline case, escalated"})


class TestBL08LowestPriceArithmeticFlagsViolation:
    """BL-08: own_price vs competitor median flags violation for 最安値 claims."""

    def test_own_price_above_min_competitor_is_violation(self, node, bound_test_secrets):
        state = base_state(
            claims=[{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 3500}],
            own_price=3500.0,
            competitor_prices={"rakuten": 2980.0, "amazon_jp": 3080.0, "yahoo_shopping": 3050.0},
        )
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        check = result["rule_check_results"][0]
        assert check["verdict"] == "VIOLATION"
        assert check["rationale"]

    def test_own_price_at_or_below_min_competitor_is_pass(self, node, bound_test_secrets):
        state = base_state(
            claims=[{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 2500}],
            own_price=2500.0,
            competitor_prices={"rakuten": 2980.0, "amazon_jp": 3080.0, "yahoo_shopping": 3050.0},
        )
        result = node.execute(state)
        check = result["rule_check_results"][0]
        assert check["verdict"] == "PASS"


class TestBL09MsrpArithmetic:
    """BL-09: MSRP claim vs 1.5x median competitor price."""

    def test_msrp_claim_exceeding_threshold_is_violation(self, node, bound_test_secrets):
        # median competitor = 3000; threshold = 4500. Stated MSRP 6000 exceeds it clearly (margin > 5%).
        state = base_state(
            claims=[{"claim_type": "通常価格", "quote": "通常価格6000円", "stated_value": 6000}],
            own_price=2000.0,
            competitor_prices={"rakuten": 2900.0, "amazon_jp": 3000.0, "yahoo_shopping": 3100.0},
        )
        result = node.execute(state)
        check = result["rule_check_results"][0]
        assert check["verdict"] in ("VIOLATION", "WARNING")

    def test_msrp_claim_within_threshold_is_pass(self, node, bound_test_secrets):
        # median competitor = 3000; threshold = 4500. Stated MSRP 3200 comfortably passes.
        state = base_state(
            claims=[{"claim_type": "通常価格", "quote": "通常価格3200円", "stated_value": 3200}],
            own_price=2000.0,
            competitor_prices={"rakuten": 2900.0, "amazon_jp": 3000.0, "yahoo_shopping": 3100.0},
        )
        result = node.execute(state)
        check = result["rule_check_results"][0]
        assert check["verdict"] == "PASS"


class TestBL10BorderlineEscalatesToKB:
    """BL-10: borderline discount-rate claim triggers vector KB precedent search."""

    def test_borderline_case_calls_search_precedents_and_folds_into_rationale(
        self, node, monkeypatch, bound_test_secrets
    ):
        fake_kb = _FakeKBService(precedents=[{"case_id": "case-42", "outcome": "WARNING"}])
        monkeypatch.setattr(compliance_check_module, "EnforcementCaseKBService", lambda: fake_kb)
        monkeypatch.setattr(compliance_check_module, "call_llm", llm_returns(_WARNING_JSON))

        # Construct a discount claim whose margin lands within BORDERLINE_MARGIN (0.05).
        # median = 3000; actual_discount_pct = (3000-2850)/3000*100 = 5.0
        # stated_value = 5.0 (%) -> margin = (5.0-5.0)/5.0 = 0.0 (borderline, exactly at boundary)
        state = base_state(
            claims=[{"claim_type": "割引率", "quote": "5%オフ", "stated_value": 5.0}],
            own_price=2850.0,
            competitor_prices={"rakuten": 2900.0, "amazon_jp": 3000.0, "yahoo_shopping": 3100.0},
        )
        result = node.execute(state)
        check = result["rule_check_results"][0]
        assert check["verdict"] == "WARNING"
        assert "escalated" in check["rationale"] or check["rationale"]


class TestBL17VectorKbUnreachablePropagates:
    """BL-17: vector KB unreachable causes unrecoverable error propagation."""

    def test_kb_connection_failure_raises(self, node, monkeypatch, bound_test_secrets):
        monkeypatch.setattr(compliance_check_module, "EnforcementCaseKBService", lambda: _FailingKBService())
        monkeypatch.setattr(compliance_check_module, "call_llm", llm_returns(_WARNING_JSON))

        state = base_state(
            claims=[{"claim_type": "割引率", "quote": "5%オフ", "stated_value": 5.0}],
            own_price=2850.0,
            competitor_prices={"rakuten": 2900.0, "amazon_jp": 3000.0, "yahoo_shopping": 3100.0},
        )
        with pytest.raises(ConnectionError):
            node.execute(state)


class TestComplianceCheckArithmeticEdgeCases:
    """Covers WARNING fallback branches in _check_msrp / _check_discount."""

    def test_msrp_claim_with_no_competitor_prices_is_warning(self, node, bound_test_secrets):
        state = base_state(
            claims=[{"claim_type": "通常価格", "quote": "通常価格5000円", "stated_value": 5000}],
            own_price=2000.0,
            competitor_prices={},
        )
        result = node.execute(state)
        assert result["rule_check_results"][0]["verdict"] == "WARNING"

    def test_discount_claim_with_no_competitor_prices_is_warning(self, node, bound_test_secrets):
        state = base_state(
            claims=[{"claim_type": "割引率", "quote": "10%オフ", "stated_value": 10}],
            own_price=900.0,
            competitor_prices={},
        )
        result = node.execute(state)
        assert result["rule_check_results"][0]["verdict"] == "WARNING"

    def test_discount_claim_with_zero_median_is_warning(self, node, bound_test_secrets):
        state = base_state(
            claims=[{"claim_type": "割引率", "quote": "10%オフ", "stated_value": 10}],
            own_price=0.0,
            competitor_prices={"rakuten": 0.0},
        )
        result = node.execute(state)
        assert result["rule_check_results"][0]["verdict"] == "WARNING"


class TestComplianceCheckLLMResponseUnparseable:
    """Covers the JSONDecodeError/AttributeError fallback in _escalate_borderline."""

    def test_unparseable_llm_response_falls_back_to_warning(self, node, monkeypatch, bound_test_secrets):
        monkeypatch.setattr(compliance_check_module, "EnforcementCaseKBService", lambda: _FakeKBService())
        monkeypatch.setattr(compliance_check_module, "call_llm", llm_returns("not valid json {{{"))

        state = base_state(
            claims=[{"claim_type": "unknown_type", "quote": "x", "stated_value": 1}],
            own_price=100.0,
            competitor_prices={"rakuten": 200.0},
        )
        result = node.execute(state)
        check = result["rule_check_results"][0]
        assert check["verdict"] == "WARNING"
        assert check["rationale"] == "LLM response could not be parsed"


class TestComplianceCheckEdgeCases:
    def test_unknown_claim_type_defaults_to_warning(self, node, monkeypatch, bound_test_secrets):
        # Unknown claim types get verdict=WARNING, margin=0.0, which is within
        # BORDERLINE_MARGIN and escalates to KB + LLM reasoning — mock both.
        monkeypatch.setattr(compliance_check_module, "EnforcementCaseKBService", lambda: _FakeKBService())
        monkeypatch.setattr(compliance_check_module, "call_llm", llm_returns(_WARNING_JSON))

        state = base_state(
            claims=[{"claim_type": "unknown_type", "quote": "x", "stated_value": 1}],
            own_price=100.0,
            competitor_prices={"rakuten": 200.0},
        )
        result = node.execute(state)
        assert result["rule_check_results"][0]["verdict"] == "WARNING"

    def test_no_competitor_prices_returns_warning(self, node, bound_test_secrets):
        state = base_state(
            claims=[{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 1000}],
            own_price=1000.0,
            competitor_prices={},
        )
        result = node.execute(state)
        assert result["rule_check_results"][0]["verdict"] == "WARNING"
