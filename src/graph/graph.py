"""AgentCore Platform v1.0"""

# RET-C2-327 — Retail Web Price Claim & Competitor Comparison Validation Agent
# Cat 2: outer graph is the standard 5-node backbone; domain complexity (claim
# extraction, competitor price fetch, compliance check, report assembly) is
# encapsulated in the inner PriceValidationWorkflowGraph, wrapped by
# PriceValidationGraphNode in the `main` slot.

from typing import Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState

from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class PriceValidationGraphNode(GraphNode):
    """Wraps PriceValidationWorkflowGraph; assigned to the outer `main` slot."""

    # Scrapling anti-bot blocks and insufficient data are modeled as in-band
    # per-claim "INSUFFICIENT DATA" verdicts, not exceptions; genuine
    # unexpected errors (e.g. vector KB down) fail fast to the outer caller.
    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def get_subgraph(self) -> Any:
        """Called by GraphNode.execute() with no state access — per-request
        fields (product_sku, own_price, target_platforms) are attached via
        _parent_config(state) below and threaded through by the overridden
        execute() since get_subgraph() itself cannot see state.
        """
        from src.graph.domain_workflow_graph import PriceValidationWorkflowGraph

        return PriceValidationWorkflowGraph(config=self._pending_config)

    def extract_input(self, state: AgentState) -> str:
        """Prefer validated_input (set by pre_process) over raw user_input."""
        text: str = state.get("validated_input", state.get("user_input", ""))
        return text

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        """Map PriceValidationWorkflowGraph.get_output() into the outer state."""
        return {
            "claims": sub_result.get("claims", []),
            "competitor_prices": sub_result.get("competitor_prices", {}),
            "validation_results": sub_result.get("validation_results", []),
            "status": sub_result.get("status"),
        }

    def _parent_config(self, state: AgentState) -> dict[str, Any]:
        """Forward product_sku, own_price, target_platforms to the inner graph."""
        return {
            "product_sku": state.get("product_sku", ""),
            "own_price": state.get("own_price"),
            "target_platforms": state.get("target_platforms", []),
        }

    def execute(self, state: AgentState) -> dict[str, Any]:
        """Override to thread per-request config into get_subgraph().

        GraphNode.get_subgraph() takes no arguments (base contract), so the
        parent config computed from `state` is stashed on the instance just
        before delegating to the framework's GraphNode.execute(), which
        immediately calls get_subgraph() synchronously within this same call.
        """
        self._pending_config = self._parent_config(state)
        try:
            result: dict[str, Any] = super().execute(state)
            return result
        finally:
            self._pending_config = {}


class PriceValidationAgent(AgentBaseGraph):
    """Outer graph — Cat 2 fixed 5-node backbone.

    initialize -> pre_process -> main -> post_process -> finalize, with a
    retry loop (main -> route -> pre_process, max_retry=3).
    """

    @property
    def name(self) -> str:
        return "ret-c2-327"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize

        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = PriceValidationGraphNode()
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
