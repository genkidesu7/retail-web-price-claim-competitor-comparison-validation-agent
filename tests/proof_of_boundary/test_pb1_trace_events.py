"""PB-1: BaseNode -> EventEmitter boundary.

emit_trace_event() fires on every invocation path (success, S-1 denial,
S-2 rejection, execute() error) — no silent failures.
"""

from __future__ import annotations

import framework.nodes.base_node as base_node_module
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.nodes.function_node import FunctionNode
from tests.conftest import base_state


class _AlwaysSucceedsNode(FunctionNode):
    required_trust_level = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        return {"status": AgentStatus.SUCCESS.value}


class _AlwaysErrorsNode(FunctionNode):
    required_trust_level = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        raise RuntimeError("boom")


class TestPB1TraceEventsFireOnEveryPath:
    def test_success_path_emits_start_and_complete(self, monkeypatch):
        events: list[str] = []
        monkeypatch.setattr(
            base_node_module,
            "emit_trace_event",
            lambda event_type, payload, state: events.append(event_type),
        )
        node = _AlwaysSucceedsNode()
        node(base_state(caller_trust_level=TrustLevel.ANONYMOUS.value))
        assert "node_start" in events
        assert "node_complete" in events

    def test_s1_denial_path_emits_s1_denied(self, monkeypatch):
        events: list[str] = []
        monkeypatch.setattr(
            base_node_module,
            "emit_trace_event",
            lambda event_type, payload, state: events.append(event_type),
        )

        class _InternalOnlyNode(FunctionNode):
            required_trust_level = TrustLevel.INTERNAL

            def execute(self, state: dict) -> dict:
                return {"status": AgentStatus.SUCCESS.value}

        node = _InternalOnlyNode()
        node(base_state(caller_trust_level=TrustLevel.ANONYMOUS.value))
        assert "s1_denied" in events
        assert "node_start" not in events  # S-1 short-circuits before node_start

    def test_execute_error_path_emits_node_error(self, monkeypatch):
        events: list[str] = []
        monkeypatch.setattr(
            base_node_module,
            "emit_trace_event",
            lambda event_type, payload, state: events.append(event_type),
        )
        node = _AlwaysErrorsNode()
        result = node(base_state(caller_trust_level=TrustLevel.ANONYMOUS.value))
        assert "node_error" in events
        assert result["status"] == AgentStatus.ERROR.value
