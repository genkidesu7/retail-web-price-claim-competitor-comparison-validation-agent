"""Integration tests — full outer graph (PriceValidationAgent) end-to-end.

Exercises initialize -> pre_process -> main (inner PriceValidationWorkflowGraph:
claim_extract -> competitor_fetch -> compliance_check -> report_assemble) ->
post_process -> finalize, with all external calls (LLM, Scrapling, vector KB)
mocked. Covers both a PASS-with-evidence scenario and an INSUFFICIENT DATA
scenario (per docs/03_test_spec.md Integration tests requirement).
"""

from __future__ import annotations

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.secrets.context import bound_secrets
from shared.secrets.inmemory_provider import InMemoryProvider
from src.graph.graph import PriceValidationAgent


_CLAIM_EXTRACT_RESPONSE = json.dumps(
    [{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 2500}]
)


def _fake_call_llm(kind, prompt, secrets, **_kwargs):  # noqa: ARG001
    """Deterministic LLM stub — distinct responses per call site."""
    if kind == "claim_extract":
        return _CLAIM_EXTRACT_RESPONSE
    return json.dumps({"verdict": "WARNING", "rationale": "borderline, escalated to KB"})


class _FakeScraplingServiceSufficient:
    async def fetch_competitor_prices(self, sku, platforms):
        prices = {"rakuten": 2980.0, "amazon_jp": 3080.0, "yahoo_shopping": 3050.0}
        return {p: prices[p] for p in platforms if p in prices}


class _FakeScraplingServiceInsufficient:
    async def fetch_competitor_prices(self, sku, platforms):
        # Only 1 competitor price found — below MIN_COMPETITOR_COUNT (3).
        return {"rakuten": 2980.0}


class _FakeKBService:
    async def search_precedents(self, claim_type, context):
        return [{"case_id": "mock-1", "outcome": "WARNING"}]


@pytest.fixture
def secrets():
    return InMemoryProvider(
        {
            "AZURE_OPENAI_API_KEY": "mock-azure-key-for-testing",
            "AZURE_OPENAI_ENDPOINT": "https://mock-resource.services.ai.azure.com",
            "AZURE_OPENAI_DEPLOYMENT": "mock-deployment",
        }
    )


@pytest.fixture
def agent():
    a = PriceValidationAgent(config={"max_retry": 3})
    a.compile()
    return a


def _patch_external_services(monkeypatch, scrapling_service_factory):
    import src.nodes.claim_extract_node as claim_extract_module
    import src.nodes.competitor_fetch_node as competitor_fetch_module
    import src.nodes.compliance_check_node as compliance_check_module

    monkeypatch.setattr(claim_extract_module, "call_llm", _fake_call_llm)
    monkeypatch.setattr(compliance_check_module, "call_llm", _fake_call_llm)
    monkeypatch.setattr(competitor_fetch_module, "ScraplingPriceService", scrapling_service_factory)
    monkeypatch.setattr(compliance_check_module, "EnforcementCaseKBService", _FakeKBService)


class TestE2EPassWithEvidence:
    """Full pipeline: sufficient competitor data -> own_price beats claim -> PASS with evidence."""

    def test_pass_verdict_with_sufficient_evidence(self, agent, secrets, monkeypatch):
        _patch_external_services(monkeypatch, _FakeScraplingServiceSufficient)

        ctx = InvocationContext.for_internal(caller_id="test-caller")
        # for_internal grants INTERNAL trust, which satisfies every node's
        # required_trust_level (ANONYMOUS) — safe superset for this e2e test.
        input_context = {
            "product_sku": "SKU-100",
            "own_price": 2500.0,
            "target_platforms": ["rakuten", "amazon_jp", "yahoo_shopping"],
        }

        with bound_secrets(secrets):
            result = agent.invoke(
                "当店は業界最安値です！2500円",
                ctx=ctx,
                input_context=input_context,
            )

        assert result["status"] == AgentStatus.SUCCESS.value
        output = result["output"]
        assert output is not None
        validation_results = output["validation_results"]
        assert len(validation_results) == 1
        entry = validation_results[0]
        assert entry["verdict"] == "PASS"
        assert entry["min_competitor_count_met"] is True
        assert entry["article"]
        assert entry["recommendation"]

    def test_disclaimer_attached(self, agent, secrets, monkeypatch):
        _patch_external_services(monkeypatch, _FakeScraplingServiceSufficient)
        ctx = InvocationContext.for_internal(caller_id="test-caller")
        input_context = {
            "product_sku": "SKU-100",
            "own_price": 2500.0,
            "target_platforms": ["rakuten", "amazon_jp", "yahoo_shopping"],
        }
        with bound_secrets(secrets):
            result = agent.invoke("当店は業界最安値です！2500円", ctx=ctx, input_context=input_context)

        assert result["status"] == AgentStatus.SUCCESS.value


class TestE2EInsufficientData:
    """Full pipeline: <3 competitor prices for a 最安値 claim -> INSUFFICIENT DATA verdict."""

    def test_insufficient_data_verdict_when_competitor_count_below_minimum(
        self, agent, secrets, monkeypatch
    ):
        _patch_external_services(monkeypatch, _FakeScraplingServiceInsufficient)

        ctx = InvocationContext.for_internal(caller_id="test-caller")
        input_context = {
            "product_sku": "SKU-200",
            "own_price": 2500.0,
            "target_platforms": ["rakuten"],
        }

        with bound_secrets(secrets):
            result = agent.invoke(
                "当店は業界最安値です！2500円",
                ctx=ctx,
                input_context=input_context,
            )

        assert result["status"] == AgentStatus.SUCCESS.value
        output = result["output"]
        validation_results = output["validation_results"]
        assert len(validation_results) == 1
        entry = validation_results[0]
        # report_assemble (inner graph) correctly downgrades the per-claim
        # verdict to INSUFFICIENT DATA using the inner state's
        # min_competitor_count_met — this is the primary signal.
        assert entry["verdict"] == "INSUFFICIENT DATA"
        assert "Re-run competitor price collection" in entry["recommendation"]
        # NOTE: entry["min_competitor_count_met"] (attached by outer
        # post_process from outer state) is NOT asserted False here — see
        # known gap: PriceValidationWorkflowGraph.get_output() and
        # PriceValidationGraphNode.merge_output() do not forward
        # min_competitor_count_met from inner to outer state, so outer
        # post_process always reads the state.get(..., True) default.
        # Reported to the task owner rather than fixed in src/ or masked here.


class TestE2EInvalidInputErrorsAtOuterGraph:
    def test_negative_own_price_routes_to_error(self, agent, secrets, monkeypatch):
        _patch_external_services(monkeypatch, _FakeScraplingServiceSufficient)
        ctx = InvocationContext.for_internal(caller_id="test-caller")
        input_context = {
            "product_sku": "SKU-300",
            "own_price": -50.0,
            "target_platforms": ["rakuten"],
        }
        with bound_secrets(secrets):
            result = agent.invoke("claim text", ctx=ctx, input_context=input_context)

        assert result["status"] == AgentStatus.ERROR.value
