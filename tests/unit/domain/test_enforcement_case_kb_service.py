"""Unit tests for EnforcementCaseKBService."""

from __future__ import annotations

import pytest

from src.services.enforcement_case_kb_service import EnforcementCaseKBService


class TestEnforcementCaseKBServiceServesMockData:
    """No live vector KB is wired: the mock_data stub answers with or without a mock flag."""

    @pytest.mark.parametrize("flag_value", ["true", "false"])
    async def test_search_precedents_returns_stub_regardless_of_mock_flag(self, monkeypatch, flag_value):
        monkeypatch.setenv("USE_MOCK", flag_value)
        monkeypatch.setenv("STG_MOCK_MODE", flag_value)
        precedents = await EnforcementCaseKBService().search_precedents("最安値/最低価格", {"quote": "業界最安値"})
        assert isinstance(precedents, list)
        assert len(precedents) >= 1
        assert precedents[0]["claim_type"] == "最安値/最低価格"
