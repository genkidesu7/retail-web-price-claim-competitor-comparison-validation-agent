"""Unit tests for PostProcessNode (ResponseValidate) — BL-13, BL-14."""

from __future__ import annotations

import pytest

from framework.errors import SecurityViolationError
from framework.schemas.agent_status import AgentStatus
from src.nodes.post_process_node import DISCLAIMER, PostProcessNode
from tests.conftest import base_state


@pytest.fixture
def node():
    return PostProcessNode()


class TestBL13S3GateBlocksFalseAssurance:
    """BL-13: post_process S-3 gate blocks false-assurance PASS verdict."""

    def test_pass_verdict_without_evidence_is_blocked_via_extra_gate(self, node):
        result = {
            "result": {
                "validation_results": [
                    {"verdict": "PASS", "min_competitor_count_met": False},
                ]
            }
        }
        with pytest.raises(SecurityViolationError):
            node._extra_security_gate_output(result)

    def test_full_call_blocks_false_assurance_pass_and_returns_error(self, node, bound_test_secrets):
        state = base_state(
            validation_results=[
                {
                    "claim_text": "業界最安値",
                    "claim_type": "最安値/最低価格",
                    "verdict": "PASS",
                    "evidence": "arithmetic pass",
                    "article": "景品表示法第5条",
                    "recommendation": "No action required.",
                }
            ],
            min_competitor_count_met=False,
            claims=[],
            competitor_prices={},
            product_sku="SKU-1",
            caller_trust_level="ANONYMOUS",
        )
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value

    def test_pass_verdict_with_evidence_is_allowed(self, node):
        result = {
            "result": {
                "validation_results": [
                    {"verdict": "PASS", "min_competitor_count_met": True},
                ]
            }
        }
        assert node._extra_security_gate_output(result) == result

    def test_violation_verdict_without_evidence_is_not_blocked(self, node):
        """Only PASS verdicts require min_competitor_count_met evidence."""
        result = {
            "result": {
                "validation_results": [
                    {"verdict": "VIOLATION", "min_competitor_count_met": False},
                ]
            }
        }
        assert node._extra_security_gate_output(result) == result


class TestBL14MandatoryDisclaimer:
    """BL-14: post_process attaches mandatory disclaimer to every response."""

    def test_disclaimer_present_and_non_empty(self, node):
        state = base_state(
            validation_results=[
                {
                    "claim_text": "通常価格5000円",
                    "claim_type": "通常価格",
                    "verdict": "PASS",
                    "evidence": "e",
                    "article": "景品表示法第5条",
                    "recommendation": "No action required.",
                }
            ],
            min_competitor_count_met=True,
            claims=[],
            competitor_prices={},
            product_sku="SKU-1",
        )
        result = node.execute(state)
        assert result["disclaimer"]
        assert result["disclaimer"] == DISCLAIMER

    def test_disclaimer_present_even_with_no_validation_results(self, node):
        state = base_state(validation_results=[], min_competitor_count_met=True, claims=[], competitor_prices={})
        result = node.execute(state)
        assert result["disclaimer"]


class TestPostProcessResultShape:
    def test_result_contains_expected_keys(self, node):
        state = base_state(
            product_sku="SKU-1",
            claims=[{"claim_type": "通常価格", "quote": "q", "stated_value": 1}],
            competitor_prices={"rakuten": 100.0},
            validation_results=[
                {
                    "claim_text": "q",
                    "claim_type": "通常価格",
                    "verdict": "PASS",
                    "evidence": "e",
                    "article": "a",
                    "recommendation": "r",
                }
            ],
            min_competitor_count_met=True,
        )
        result = node.execute(state)
        assert result["result"]["product_sku"] == "SKU-1"
        assert result["result"]["claims"]
        assert result["result"]["competitor_prices"] == {"rakuten": 100.0}
        assert result["result"]["validation_results"][0]["min_competitor_count_met"] is True
