# PB-6: Invoke Execution Order Verification
# Verifies BaseNode.__call__() enforces: S-1 trust gate -> S-4 node_start ->
# S-2 _security_gate_input() -> execute() -> S-3 _security_gate_output() ->
# S-4 node_complete, for every concrete node under src/nodes/.

import importlib
import inspect
import pkgutil

import pytest

from framework.secrets.context import bound_secrets
from shared.secrets.inmemory_provider import InMemoryProvider

# Domain-specific state overrides so every node under src/nodes/ can reach its
# success path (S-3 gate) rather than short-circuiting on missing required
# fields. Keyed by node class name; falls back to {} (base state only) for
# any node not listed here — keeps the discovery generic/reusable.
_DOMAIN_STATE_OVERRIDES: dict[str, dict] = {
    "PreProcessNode": {
        "user_input": "claim text",
        "input_context": {
            "product_sku": "SKU-1",
            "own_price": 100.0,
            "claim_text": "claim text",
            "target_platforms": ["rakuten"],
        },
    },
    "ClaimExtractNode": {"validated_input": "claim text"},
    "CompetitorFetchNode": {
        "claims": [],
        "target_platforms": ["rakuten"],
        "product_sku": "SKU-1",
    },
    "ComplianceCheckNode": {
        "claims": [],
        "own_price": 100.0,
        "competitor_prices": {"rakuten": 200.0},
    },
    "ReportAssembleNode": {"rule_check_results": [], "min_competitor_count_met": True},
    "PostProcessNode": {
        "validation_results": [],
        "min_competitor_count_met": True,
        "claims": [],
        "competitor_prices": {},
        "product_sku": "SKU-1",
    },
}

_MOCK_SECRETS = InMemoryProvider(
    {
        "AZURE_OPENAI_API_KEY": "mock-azure-key-for-testing",
        "AZURE_OPENAI_ENDPOINT": "https://mock-resource.services.ai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT": "mock-deployment",
    }
)


def _discover_node_classes() -> list[type]:
    """Import every module under src/nodes/ and collect concrete BaseNode subclasses."""
    from framework.nodes.base_node import BaseNode

    try:
        pkg = importlib.import_module("src.nodes")
    except ImportError:
        return []

    discovered = []
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix="src.nodes."):
        module = importlib.import_module(modname)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseNode)
                and attr is not BaseNode
                and attr.__module__ == modname
                and not inspect.isabstract(attr)
            ):
                discovered.append(attr)
    return discovered


class TestInvokeOrder:
    """PB-6: __call__ must run S-1 -> node_start -> S-2 -> execute() -> S-3 -> node_complete."""

    def test_call_order_for_every_node(self, monkeypatch):
        node_classes = _discover_node_classes()
        if not node_classes:
            pytest.skip("no concrete BaseNode subclasses found under src/nodes/")

        import framework.nodes.base_node as base_node_module

        # Mock external service calls so domain nodes that need LLM/Scrapling/
        # KB access can reach their success path within this generic order test.
        import src.nodes.claim_extract_node as claim_extract_module
        import src.nodes.compliance_check_node as compliance_check_module
        import src.nodes.competitor_fetch_node as competitor_fetch_module

        class _FakeScrapling:
            async def fetch_competitor_prices(self, _sku, _platforms):
                return {"rakuten": 100.0, "amazon_jp": 110.0, "yahoo_shopping": 120.0}

        monkeypatch.setattr(claim_extract_module, "call_llm", lambda _kind, _prompt, _secrets, **_kw: "[]")
        monkeypatch.setattr(compliance_check_module, "call_llm", lambda _kind, _prompt, _secrets, **_kw: "[]")
        monkeypatch.setattr(competitor_fetch_module, "ScraplingPriceService", _FakeScrapling)

        failures: list[str] = []
        for node_cls in node_classes:
            order: list[str] = []
            monkeypatch.setattr(
                base_node_module,
                "emit_trace_event",
                lambda event_type, _payload, _state, _o=order: _o.append(f"event:{event_type}"),
            )

            for method_name, label in (
                ("_security_gate_input", "security_gate_input"),
                ("execute", "execute"),
                ("_security_gate_output", "security_gate_output"),
            ):
                original = getattr(node_cls, method_name)

                def spy(self, arg, _o=order, _label=label, _orig=original):
                    _o.append(_label)
                    return _orig(self, arg)

                monkeypatch.setattr(node_cls, method_name, spy)

            instance = node_cls()
            state = {
                "caller_trust_level": node_cls.required_trust_level.value,
                "correlation_id": "pb6-invoke-order-test",
                "session_id": "pb6-session",
                "thread_id": "pb6-thread",
                "trace_id": "",
                "caller_id": "",
                "hitl_allowed": True,
                "error_log": [],
                "node_history": [],
                "execution_time": {},
            }
            state.update(_DOMAIN_STATE_OVERRIDES.get(node_cls.__name__, {}))

            with bound_secrets(_MOCK_SECRETS):
                instance(state)

            expected = [
                "event:node_start",
                "security_gate_input",
                "execute",
                "security_gate_output",
                "event:node_complete",
            ]
            if order != expected:
                failures.append(
                    f"{node_cls.__name__}: invoke order violation.\n" f"expected: {expected}\nactual:   {order}"
                )

        assert not failures, "\n\n".join(failures)
