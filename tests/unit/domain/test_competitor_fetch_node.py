"""Unit tests for CompetitorFetchNode (CompetitorPriceFetch) — BL-06, BL-07."""

from __future__ import annotations

import datetime

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes import competitor_fetch_node as competitor_fetch_module
from src.nodes.competitor_fetch_node import CompetitorFetchNode
from tests.conftest import base_state


@pytest.fixture
def node():
    return CompetitorFetchNode()


class _FakeScraplingService:
    def __init__(self, prices: dict[str, float]):
        self._prices = prices

    async def fetch_competitor_prices(self, sku, platforms):
        return dict(self._prices)


def _patch_service(monkeypatch, prices: dict[str, float]):
    monkeypatch.setattr(
        competitor_fetch_module,
        "ScraplingPriceService",
        lambda: _FakeScraplingService(prices),
    )


class TestBL06MinCompetitorCountEnforced:
    """BL-06: competitor_fetch enforces min_competitor_count >= 3 for 最安値 claims."""

    def test_two_competitor_prices_fails_min_count_for_lowest_price_claim(self, node, monkeypatch, bound_test_secrets):
        _patch_service(monkeypatch, {"rakuten": 2980.0, "amazon_jp": 3080.0})
        state = base_state(
            claims=[{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 2980}],
            target_platforms=["rakuten", "amazon_jp"],
            product_sku="SKU-1",
        )
        result = node.execute(state)
        assert result["min_competitor_count_met"] is False

    def test_three_or_more_competitor_prices_meets_min_count(self, node, monkeypatch, bound_test_secrets):
        _patch_service(
            monkeypatch, {"rakuten": 2980.0, "amazon_jp": 3080.0, "yahoo_shopping": 3050.0}
        )
        state = base_state(
            claims=[{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 2980}],
            target_platforms=["rakuten", "amazon_jp", "yahoo_shopping"],
            product_sku="SKU-1",
        )
        result = node.execute(state)
        assert result["min_competitor_count_met"] is True

    def test_non_lowest_price_claims_do_not_require_min_count(self, node, monkeypatch, bound_test_secrets):
        _patch_service(monkeypatch, {"rakuten": 2980.0})
        state = base_state(
            claims=[{"claim_type": "通常価格", "quote": "通常価格5000円", "stated_value": 5000}],
            target_platforms=["rakuten"],
            product_sku="SKU-1",
        )
        result = node.execute(state)
        assert result["min_competitor_count_met"] is True


class TestBL07CompetitorPricesAndTimestamp:
    """BL-07: competitor_fetch populates competitor_prices + ISO 8601 fetch_timestamp string."""

    def test_competitor_prices_populated(self, node, monkeypatch, bound_test_secrets):
        prices = {"rakuten": 2980.0, "amazon_jp": 3080.0, "yahoo_shopping": 3050.0}
        _patch_service(monkeypatch, prices)
        state = base_state(
            claims=[],
            target_platforms=list(prices.keys()),
            product_sku="SKU-1",
        )
        result = node.execute(state)
        assert result["competitor_prices"] == prices

    def test_fetch_timestamp_is_iso8601_string_not_datetime(self, node, monkeypatch, bound_test_secrets):
        _patch_service(monkeypatch, {"rakuten": 2980.0})
        state = base_state(claims=[], target_platforms=["rakuten"], product_sku="SKU-1")
        result = node.execute(state)

        assert isinstance(result["fetch_timestamp"], str)
        # Must be parseable as ISO 8601 — round-trips through datetime.fromisoformat.
        parsed = datetime.datetime.fromisoformat(result["fetch_timestamp"])
        assert parsed.tzinfo is not None

    def test_status_success(self, node, monkeypatch, bound_test_secrets):
        _patch_service(monkeypatch, {"rakuten": 2980.0})
        state = base_state(claims=[], target_platforms=["rakuten"], product_sku="SKU-1")
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value
