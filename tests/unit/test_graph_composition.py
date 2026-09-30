"""Unit tests for outer/inner graph identity, config validation, and routing.

Covers small glue methods (name, state_schema, route, _validate_config) on
PriceValidationAgent (outer) and PriceValidationWorkflowGraph (inner) that
aren't exercised by the domain node tests or the full e2e integration test.
"""

from __future__ import annotations

import pytest
from langgraph.graph import END

from framework.errors import ConfigError
from framework.schemas.agent_status import AgentStatus
from src.graph.domain_workflow_graph import PriceValidationWorkflowGraph
from src.graph.graph import PriceValidationAgent
from src.schemas.state import State


class TestPriceValidationAgentIdentity:
    def test_name(self):
        agent = PriceValidationAgent()
        assert agent.name == "ret-c2-327"

    def test_state_schema_is_state(self):
        agent = PriceValidationAgent()
        assert agent.state_schema is State

    def test_register_nodes_fills_required_slots(self):
        agent = PriceValidationAgent()
        agent.register_nodes()
        assert agent._nodes["pre_process"] is not None
        assert agent._nodes["main"] is not None
        assert agent._nodes["post_process"] is not None


class TestPriceValidationWorkflowGraphIdentity:
    def test_name(self):
        graph = PriceValidationWorkflowGraph(config={})
        assert graph.name == "price_validation_workflow"

    def test_state_schema_is_state(self):
        graph = PriceValidationWorkflowGraph(config={})
        assert graph.state_schema is State

    def test_validate_config_raises_on_none_config(self):
        graph = PriceValidationWorkflowGraph(config={})
        graph.config = None
        with pytest.raises(ConfigError):
            graph._validate_config()

    def test_validate_config_passes_with_empty_dict(self):
        graph = PriceValidationWorkflowGraph(config={})
        graph._validate_config()  # should not raise

    def test_route_returns_report_assemble_on_non_error_status(self):
        graph = PriceValidationWorkflowGraph(config={})
        assert graph.route({"status": AgentStatus.SUCCESS.value}) == "report_assemble"

    def test_route_returns_end_on_error_status(self):
        graph = PriceValidationWorkflowGraph(config={})
        assert graph.route({"status": AgentStatus.ERROR.value}) == END

    def test_extra_initial_state_forwards_config_keys(self):
        graph = PriceValidationWorkflowGraph(
            config={"product_sku": "SKU-1", "own_price": 100.0, "target_platforms": ["rakuten"]}
        )
        extra = graph._extra_initial_state()
        assert extra == {"product_sku": "SKU-1", "own_price": 100.0, "target_platforms": ["rakuten"]}

    def test_get_output_shape(self):
        graph = PriceValidationWorkflowGraph(config={})
        state = {
            "claims": [{"claim_type": "通常価格", "quote": "q", "stated_value": 1}],
            "competitor_prices": {"rakuten": 100.0},
            "validation_results": [{"verdict": "PASS"}],
            "status": AgentStatus.SUCCESS.value,
        }
        output = graph.get_output(state)
        assert output["claims"] == state["claims"]
        assert output["competitor_prices"] == state["competitor_prices"]
        assert output["validation_results"] == state["validation_results"]
        assert output["status"] == AgentStatus.SUCCESS.value
