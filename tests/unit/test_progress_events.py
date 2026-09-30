"""Every node emits a PROGRESS_UPDATE on entry — and never a terminal event."""

from __future__ import annotations

import json

import pytest

from shared.services.events import EventEmitter, EventType, bound_emitter
from src.nodes.claim_extract_node import ClaimExtractNode
from src.nodes.competitor_fetch_node import CompetitorFetchNode
from src.nodes.compliance_check_node import ComplianceCheckNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.nodes.report_assemble_node import ReportAssembleNode
from tests.conftest import base_state


class _RecordingEmitter(EventEmitter):
    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict]] = []

    def emit_event(self, *, event_type, message, metadata=None, sub_event_type=None) -> None:
        self.events.append((event_type, metadata or {}))


_CLAIM = {"claim_type": "通常価格", "quote": "通常価格3000円", "stated_value": 3000}

_CASES = [
    ("pre_process", PreProcessNode, {
        "user_input": "claim",
        "input_context": {
            "product_sku": "SKU-1", "own_price": 100.0, "claim_text": "claim", "target_platforms": ["rakuten"],
        },
    }),
    ("claim_extract", ClaimExtractNode, {"validated_input": "当店は業界最安値です"}),
    ("competitor_fetch", CompetitorFetchNode, {"claims": [_CLAIM], "target_platforms": ["rakuten"]}),
    ("compliance_check", ComplianceCheckNode, {"claims": [_CLAIM], "competitor_prices": {"rakuten": 2000.0}}),
    ("report_assemble", ReportAssembleNode, {"rule_check_results": []}),
    ("post_process", PostProcessNode, {"validation_results": []}),
]


@pytest.mark.parametrize(("stage", "node_cls", "state_fields"), _CASES, ids=[c[0] for c in _CASES])
def test_node_emits_one_progress_update_on_entry(monkeypatch, bound_test_secrets, stage, node_cls, state_fields):
    monkeypatch.setenv("USE_MOCK", "true")
    recorder = _RecordingEmitter()
    with bound_emitter(recorder):
        node_cls().execute(base_state(**state_fields))

    progress = [meta for event_type, meta in recorder.events if event_type is EventType.PROGRESS_UPDATE]
    assert [meta["stage"] for meta in progress] == [stage]
    assert all(event_type is EventType.PROGRESS_UPDATE for event_type, _ in recorder.events)


def test_mock_llm_stub_is_valid_json_for_each_kind():
    from src.services.mock_data import stub_llm_response

    assert isinstance(json.loads(stub_llm_response("claim_extract")), list)
    assert json.loads(stub_llm_response("compliance_reasoning"))["verdict"] == "WARNING"
