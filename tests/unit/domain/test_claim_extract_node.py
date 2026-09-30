"""Unit tests for ClaimExtractNode (PriceClaimExtract, inner graph entry) — BL-04, BL-05."""

from __future__ import annotations

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes import claim_extract_node as claim_extract_module
from src.nodes.claim_extract_node import ClaimExtractNode, _parse_claims
from tests.conftest import base_state, llm_returns


_CLAIMS_JSON = json.dumps([{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 2980}])
_NO_CLAIMS_JSON = "[]"


@pytest.fixture
def node():
    return ClaimExtractNode()


class TestBL04ClassifiesClaimIntoCorrectType:
    """BL-04: claim_extract classifies claim into correct type."""

    def test_extracts_and_classifies_lowest_price_claim(self, node, monkeypatch, bound_test_secrets):
        monkeypatch.setattr(claim_extract_module, "call_llm", llm_returns(_CLAIMS_JSON))
        state = base_state(validated_input="当店は業界最安値です！2980円")
        result = node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert len(result["claims"]) == 1
        claim = result["claims"][0]
        assert claim["claim_type"] == "最安値/最低価格"
        assert claim["quote"] == "業界最安値"
        assert claim["stated_value"] == 2980

    def test_no_claims_found_returns_empty_list(self, node, monkeypatch, bound_test_secrets):
        monkeypatch.setattr(claim_extract_module, "call_llm", llm_returns(_NO_CLAIMS_JSON))
        state = base_state(validated_input="Just a plain product description with no price claims.")
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["claims"] == []


class TestBL05InnerNodeFallback:
    """BL-05: claim_extract inner-node fallback reads user_input when validated_input absent."""

    def test_falls_back_to_user_input_when_validated_input_absent(self, node, monkeypatch, bound_test_secrets):
        monkeypatch.setattr(claim_extract_module, "call_llm", llm_returns(_CLAIMS_JSON))
        state = base_state(user_input="当店は業界最安値です！2980円")
        state.pop("validated_input", None)

        result = node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert len(result["claims"]) == 1

    def test_no_key_error_when_only_user_input_set(self, node, monkeypatch, bound_test_secrets):
        monkeypatch.setattr(claim_extract_module, "call_llm", llm_returns(_CLAIMS_JSON))
        state = {
            "user_input": "当店は業界最安値です！",
            "correlation_id": "c",
            "session_id": "s",
            "thread_id": "t",
            "trace_id": "",
            "caller_trust_level": "ANONYMOUS",
            "caller_id": "",
            "hitl_allowed": True,
        }
        # Should not raise KeyError despite validated_input being entirely absent.
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value


class TestClaimExtractNoTextAvailable:
    def test_no_text_returns_error(self, node):
        state = base_state(user_input="", validated_input="")
        result = node.execute(state)
        assert result["status"] == AgentStatus.ERROR.value
        assert result["error_log"]


class TestParseClaimsEdgeCases:
    """Direct unit tests for the _parse_claims LLM-response-parsing helper."""

    def test_malformed_json_returns_empty_list(self):
        assert _parse_claims("not valid json {{{") == []

    def test_non_list_json_returns_empty_list(self):
        assert _parse_claims(json.dumps({"not": "a list"})) == []

    def test_non_dict_items_are_skipped(self):
        assert _parse_claims(json.dumps(["just a string", 123])) == []

    def test_items_with_invalid_claim_type_are_skipped(self):
        payload = json.dumps([{"claim_type": "not_a_real_type", "quote": "q", "stated_value": 1}])
        assert _parse_claims(payload) == []

    def test_items_missing_required_fields_are_skipped(self):
        payload = json.dumps([{"claim_type": "通常価格", "quote": "q"}])  # missing stated_value
        assert _parse_claims(payload) == []

    def test_valid_and_invalid_items_mixed_keeps_only_valid(self):
        payload = json.dumps(
            [
                {"claim_type": "通常価格", "quote": "valid", "stated_value": 100},
                {"claim_type": "bogus", "quote": "invalid", "stated_value": 1},
                "not a dict",
            ]
        )
        result = _parse_claims(payload)
        assert len(result) == 1
        assert result[0]["quote"] == "valid"


class TestClaimExtractForwardsFields:
    def test_forwards_product_sku_own_price_target_platforms(self, node, monkeypatch, bound_test_secrets):
        monkeypatch.setattr(claim_extract_module, "call_llm", llm_returns(_NO_CLAIMS_JSON))
        state = base_state(
            validated_input="claim",
            product_sku="SKU-9",
            own_price=1000.0,
            target_platforms=["rakuten"],
        )
        result = node.execute(state)
        assert result["product_sku"] == "SKU-9"
        assert result["own_price"] == 1000.0
        assert result["target_platforms"] == ["rakuten"]
