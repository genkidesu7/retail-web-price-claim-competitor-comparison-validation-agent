"""AgentCore Platform v1.0"""

# Service layer: competitor price lookup for Japan EC platforms.
# Must NOT contain business logic, routing, or credentials.
# Nodes call this; this calls shared/services/ for external integrations.
#
# No live Scrapling (D4Vinci/Scrapling) client is provisioned for this agent,
# so every call is served by the mock_data stub. That holds in real (non-mock)
# runs too: only the LLM path becomes real when mock mode is off.

from __future__ import annotations

from shared.utils.retry_policy import retry_with_backoff

from src.services.mock_data import stub_fetch_competitor_price


class ScraplingPriceService:
    """Fetches Japan EC competitor prices.

    Usage from a node::

        service = ScraplingPriceService()
        prices = await service.fetch_competitor_prices(sku, platforms)
    """

    MAX_RETRY = 3
    TIMEOUT_SECONDS = 30

    async def fetch_competitor_prices(self, sku: str, platforms: list[str]) -> dict[str, float]:
        """Fetch competitor prices for `sku` across `platforms`.

        Returns:
            dict mapping platform -> fetched price. Platforms that fail after
            all retries are omitted (graceful degradation — never raises for
            transient/anti-bot failures).
        """
        prices: dict[str, float] = {}
        for platform in platforms:
            try:
                price = await self._fetch_one_with_retry(sku, platform)
            except Exception:
                # ConnectionPolicy retry exhausted or anti-bot block: graceful
                # degradation per design — proceed with partial data rather
                # than failing the whole invocation.
                continue
            if price is not None:
                prices[platform] = price
        return prices

    async def _fetch_one_with_retry(self, sku: str, platform: str) -> float | None:
        retrying_call = retry_with_backoff(max_retries=self.MAX_RETRY, max_delay=self.TIMEOUT_SECONDS)(
            self._call_external
        )
        result: float | None = retrying_call(sku, platform)
        return result

    def _call_external(self, sku: str, platform: str) -> float | None:
        return stub_fetch_competitor_price(sku, platform)
