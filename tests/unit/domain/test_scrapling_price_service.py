"""Unit tests for ScraplingPriceService — BL-15, BL-16."""

from __future__ import annotations

import pytest

from src.services.scrapling_price_service import ScraplingPriceService


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """retry_with_backoff sleeps between attempts — patch to keep tests fast."""
    import shared.utils.retry_policy as retry_policy_module

    monkeypatch.setattr(retry_policy_module.time, "sleep", lambda *_a, **_k: None)


class TestBL15TransientFailureRetriesBoundedByMaxRetry:
    """BL-15: Scrapling transient failure triggers RETRY bounded by max_retry: 3,
    then falls back to partial data (graceful degradation, no exception).
    """

    async def test_transient_failure_retries_then_degrades_gracefully(self, monkeypatch):
        service = ScraplingPriceService()

        call_count = {"rakuten": 0}

        def flaky_call(sku, platform):
            call_count[platform] = call_count.get(platform, 0) + 1
            raise TimeoutError("simulated transient timeout")

        monkeypatch.setattr(service, "_call_external", flaky_call)

        prices = await service.fetch_competitor_prices("SKU-1", ["rakuten"])

        # ScraplingPriceService.MAX_RETRY = 3 -> retry_with_backoff attempts 1 + 3 = 4 calls total.
        assert call_count["rakuten"] == ScraplingPriceService.MAX_RETRY + 1
        # Graceful degradation: platform omitted from result, no exception raised.
        assert "rakuten" not in prices
        assert prices == {}

    async def test_transient_failure_then_success_returns_partial_data(self, monkeypatch):
        service = ScraplingPriceService()

        attempts = {"count": 0}

        def flaky_then_success(sku, platform):
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise ConnectionError("rate limited")
            return 2980.0

        monkeypatch.setattr(service, "_call_external", flaky_then_success)

        prices = await service.fetch_competitor_prices("SKU-1", ["rakuten"])
        assert prices == {"rakuten": 2980.0}


class TestBL16HardFailureDegradesGracefully:
    """BL-16: Scrapling hard failure (anti-bot block) does not raise, degrades gracefully."""

    async def test_hard_block_on_one_platform_does_not_raise_and_others_succeed(self, monkeypatch):
        service = ScraplingPriceService()

        def per_platform(sku, platform):
            if platform == "amazon_jp":
                raise PermissionError("anti-bot block")
            return 2980.0

        monkeypatch.setattr(service, "_call_external", per_platform)

        prices = await service.fetch_competitor_prices("SKU-1", ["rakuten", "amazon_jp"])

        assert "amazon_jp" not in prices
        assert prices == {"rakuten": 2980.0}

    async def test_all_platforms_hard_blocked_returns_empty_without_raising(self, monkeypatch):
        service = ScraplingPriceService()

        def always_blocked(sku, platform):
            raise PermissionError("anti-bot block")

        monkeypatch.setattr(service, "_call_external", always_blocked)

        prices = await service.fetch_competitor_prices("SKU-1", ["rakuten", "amazon_jp"])
        assert prices == {}


class TestScraplingPriceServiceServesMockData:
    """No live Scrapling client is wired: the mock_data stub answers with or without a mock flag."""

    @pytest.mark.parametrize("flag_value", ["true", "false"])
    async def test_serves_stub_prices_regardless_of_mock_flag(self, monkeypatch, flag_value):
        monkeypatch.setenv("USE_MOCK", flag_value)
        monkeypatch.setenv("STG_MOCK_MODE", flag_value)
        prices = await ScraplingPriceService().fetch_competitor_prices("SKU-1", ["rakuten", "amazon_jp"])
        assert prices == {"rakuten": 2980.0, "amazon_jp": 3080.0}

    async def test_unknown_platform_is_omitted(self):
        prices = await ScraplingPriceService().fetch_competitor_prices("SKU-1", ["rakuten", "no_such_platform"])
        assert prices == {"rakuten": 2980.0}
