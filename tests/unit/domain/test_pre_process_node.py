"""Unit tests for PreProcessNode (InputParse) — BL-01, BL-02, BL-03."""

from __future__ import annotations

import pytest

from framework.errors import SecurityViolationError
from framework.schemas.agent_status import AgentStatus
from src.nodes.pre_process_node import PreProcessNode
from tests.conftest import base_state


@pytest.fixture
def node():
    return PreProcessNode()


def _valid_input_context(**overrides):
    ctx = {
        "product_sku": "SKU-123",
        "own_price": 2980.0,
        "claim_text": "当店は業界最安値です！",
        "target_platforms": ["rakuten", "amazon_jp"],
    }
    ctx.update(overrides)
    return ctx


class TestPreProcessSuccessPath:
    def test_valid_input_produces_validated_input_and_success(self, node):
        state = base_state(user_input="当店は業界最安値です！", input_context=_valid_input_context())
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["validated_input"] == "当店は業界最安値です！"
        assert result["product_sku"] == "SKU-123"
        assert result["own_price"] == 2980.0
        assert result["target_platforms"] == ["rakuten", "amazon_jp"]


class TestBL01NegativeOwnPrice:
    """BL-01: pre_process rejects negative own_price."""

    def test_negative_own_price_raises_security_violation(self, node):
        state = base_state(
            user_input="claim text",
            input_context=_valid_input_context(own_price=-100),
        )
        with pytest.raises(SecurityViolationError):
            node._extra_security_gate_input(state)

    def test_negative_own_price_via_full_call_returns_error_status(self, node, bound_test_secrets):
        state = base_state(
            user_input="claim text",
            input_context=_valid_input_context(own_price=-100),
            caller_trust_level="ANONYMOUS",
        )
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value


class TestBL02EmptyClaimText:
    """BL-02: pre_process rejects empty claim_text."""

    def test_empty_claim_text_raises_security_violation(self, node):
        state = base_state(user_input="", input_context=_valid_input_context(claim_text=""))
        with pytest.raises(SecurityViolationError):
            node._extra_security_gate_input(state)


class TestBL03UnrecognizedPlatform:
    """BL-03: pre_process rejects unrecognized target_platforms."""

    def test_unrecognized_platform_raises_security_violation(self, node):
        state = base_state(
            user_input="claim text",
            input_context=_valid_input_context(target_platforms=["unknown_platform"]),
        )
        with pytest.raises(SecurityViolationError):
            node._extra_security_gate_input(state)

    def test_mixed_known_and_unknown_platforms_raises(self, node):
        state = base_state(
            user_input="claim text",
            input_context=_valid_input_context(target_platforms=["rakuten", "totally_unknown"]),
        )
        with pytest.raises(SecurityViolationError):
            node._extra_security_gate_input(state)


class TestPreProcessMissingFields:
    def test_missing_required_field_returns_error_status(self, node):
        state = base_state(user_input="", input_context={})
        result = node.execute(state)
        assert result["status"] == AgentStatus.ERROR.value
        assert result["error_log"]


class TestPreProcessClaimTextSource:
    def test_input_context_claim_text_wins_over_raw_user_input(self, node):
        """A Marketplace message is a JSON blob in user_input; the parsed claim_text must be used."""
        state = base_state(
            user_input='{"claim_text": "業界最安値"}',
            input_context=_valid_input_context(claim_text="業界最安値"),
        )
        result = node.execute(state)
        assert result["validated_input"] == "業界最安値"

    def test_falls_back_to_user_input_when_input_context_has_no_claim_text(self, node):
        context = _valid_input_context()
        context.pop("claim_text", None)
        result = node.execute(base_state(user_input="  業界最安値  ", input_context=context))
        assert result["validated_input"] == "業界最安値"
