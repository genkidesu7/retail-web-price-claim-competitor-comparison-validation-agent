"""PB-3: Level 2 (src/services/) -> External service boundary.

Verifies every external-facing service reaches its call path end-to-end and
retrieves data:
- ScraplingPriceService / EnforcementCaseKBService have no live backend and always
  answer from their mock_data stubs, so they are reachable with no credentials.
- call_llm (the one real integration) short-circuits to its stub in mock mode
  *before* requiring any secret, and outside mock mode fails fast with
  MissingSecret instead of proceeding on a placeholder credential.
"""

from __future__ import annotations

import pytest

from framework.secrets.base import MissingSecret
from shared.secrets.inmemory_provider import InMemoryProvider
from src.services.enforcement_case_kb_service import EnforcementCaseKBService
from src.services.mock_mode import MOCK_FLAG_NAMES
from src.services.scrapling_price_service import ScraplingPriceService
from src.services.service import call_llm


class TestPB3ScraplingExternalServiceReachable:
    async def test_fetch_competitor_prices_retrieves_data(self):
        prices = await ScraplingPriceService().fetch_competitor_prices("SKU-1", ["rakuten", "amazon_jp"])
        assert prices == {"rakuten": 2980.0, "amazon_jp": 3080.0}


class TestPB3EnforcementKBExternalServiceReachable:
    async def test_search_precedents_retrieves_data(self):
        precedents = await EnforcementCaseKBService().search_precedents("最安値/最低価格", {"quote": "test"})
        assert isinstance(precedents, list)
        assert precedents[0]["claim_type"] == "最安値/最低価格"


class TestPB3LLMServiceBoundary:
    @pytest.mark.parametrize("flag", MOCK_FLAG_NAMES)
    def test_mock_flag_reaches_stub_without_any_secret(self, monkeypatch, flag):
        for name in MOCK_FLAG_NAMES:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(flag, "true")
        content = call_llm("claim_extract", "prompt", InMemoryProvider({}))
        assert "最安値/最低価格" in content

    def test_no_mock_flag_real_path_raises_missing_secret(self, monkeypatch):
        # Every accepted alias must be cleared, or the negative test stops testing what it claims to.
        for name in MOCK_FLAG_NAMES:
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(MissingSecret):
            call_llm("claim_extract", "prompt", InMemoryProvider({}))

    def test_unknown_kind_in_mock_mode_raises_config_error(self, monkeypatch):
        from framework.errors import ConfigError

        monkeypatch.setenv("USE_MOCK", "true")
        with pytest.raises(ConfigError):
            call_llm("no_such_kind", "prompt", InMemoryProvider({}))
