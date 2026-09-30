"""AgentCore Platform v1.0"""

# Inner graph for RET-C2-327 (Cat 2). Fully custom linear topology, so this
# inherits BaseGraph directly (not the pre_process/main/post_process shape).
# Instantiated by PriceValidationGraphNode.get_subgraph() in src/graph/graph.py.

from typing import Any

from framework.errors import ConfigError
from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from langgraph.graph import END, START

from src.nodes.claim_extract_node import ClaimExtractNode
from src.nodes.competitor_fetch_node import CompetitorFetchNode
from src.nodes.compliance_check_node import ComplianceCheckNode
from src.nodes.report_assemble_node import ReportAssembleNode
from src.schemas.state import State


class PriceValidationWorkflowGraph(BaseGraph):
    """Inner domain workflow graph for the price claim validation pipeline.

    Linear topology: claim_extract -> competitor_fetch -> compliance_check
    -> report_assemble. error_strategy: propagate (set on the outer
    PriceValidationGraphNode) surfaces failures here as SubgraphError.
    """

    @property
    def name(self) -> str:
        return "price_validation_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        """No mandatory config keys for this inner graph."""
        if self.config is None:
            raise ConfigError("PriceValidationWorkflowGraph: config must not be None")

    def register_nodes(self) -> None:
        """No super() call — BaseGraph.register_nodes() is abstract.

        Do NOT register initialize/finalize here; those are outer backbone
        concerns handled by PriceValidationAgent in graph.py.
        """
        self._nodes["claim_extract"] = ClaimExtractNode()
        self._nodes["competitor_fetch"] = CompetitorFetchNode()
        self._nodes["compliance_check"] = ComplianceCheckNode()
        self._nodes["report_assemble"] = ReportAssembleNode()

    def add_edges(self) -> None:
        """Linear topology: claim_extract -> competitor_fetch -> compliance_check -> report_assemble."""
        self._sg.add_edge(START, "claim_extract")
        self._sg.add_edge("claim_extract", "competitor_fetch")
        self._sg.add_edge("competitor_fetch", "compliance_check")
        self._sg.add_edge("compliance_check", "report_assemble")
        self._sg.add_edge("report_assemble", END)

    def route(self, state: AgentState) -> str:
        """Required by BaseGraph ABC; never called (no conditional branching).

        A missing/insufficient competitor price count is represented as an
        "INSUFFICIENT DATA" per-claim verdict in report_assemble, not a
        graph-level route.
        """
        return END if state.get("status") == AgentStatus.ERROR.value else "report_assemble"

    def _extra_initial_state(self) -> dict[str, Any]:
        """Forward product_sku/own_price/target_platforms from the outer graph.

        Populated by PriceValidationGraphNode._parent_config() into self.config.
        The inner graph's initial_state built by BaseGraph.invoke() only contains
        user_input by default; this hook injects the additional fields so
        claim_extract (and downstream nodes) can read them via state.get(...).
        """
        return {
            "product_sku": self.config.get("product_sku", ""),
            "own_price": self.config.get("own_price"),
            "target_platforms": self.config.get("target_platforms", []),
        }

    def get_output(self, state: AgentState) -> dict[str, Any]:
        """Shape the sub_result dict returned to PriceValidationGraphNode.merge_output()."""
        return {
            "claims": state.get("claims", []),
            "competitor_prices": state.get("competitor_prices", {}),
            "validation_results": state.get("validation_results", []),
            "status": state.get("status"),
        }
