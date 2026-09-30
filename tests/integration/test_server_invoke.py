"""The async /invoke route must survive nodes that call asyncio.run().

Regression for the sync/async boundary: calling agent.invoke() directly inside the
running event loop makes asyncio.run() raise, which the node's error boundary turns
into a 200 response with status "error". Runs the real route in mock mode, through
the app's lifespan (httpx's ASGITransport does not trigger it on its own).
"""

from __future__ import annotations

import httpx
import pytest

from src.api.server import app

_BODY = {
    "product_sku": "SKU-1",
    "own_price": 2980.0,
    "claim_text": "当店は業界最安値です！",
    "target_platforms": ["rakuten", "amazon_jp", "yahoo_shopping"],
    "session_id": "server-test",
}


async def _post(headers: dict[str, str] | None = None) -> httpx.Response:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/invoke", json=_BODY, headers=headers)


@pytest.fixture(autouse=True)
def _mock_mode_via_ci_flag(monkeypatch):
    # STG_MOCK_MODE is what the deploy-stg job sets; USE_MOCK must not be needed.
    monkeypatch.delenv("USE_MOCK", raising=False)
    monkeypatch.setenv("STG_MOCK_MODE", "true")
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "test-token")
    monkeypatch.delenv("STG_INTERNAL_RUNNER_TOKEN", raising=False)


async def test_invoke_runs_the_graph_on_a_worker_thread_and_succeeds():
    response = await _post({"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success", body
    assert body["output"]["validation_results"], body


async def test_invoke_rejects_a_wrong_bearer_token():
    response = await _post({"Authorization": "Bearer wrong"})
    assert response.status_code == 401


async def test_health():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.json() == {"status": "ok", "agent": "ret-c2-327"}
