"""AgentCore Platform v1.0"""

# Mock stubs served through the sanctioned mock-mode gate (LLM) or as the
# only backend for integrations that have no live client (Scrapling, KB).
# Never import real credentials here.

from __future__ import annotations

import json
from typing import Any

from framework.errors import ConfigError

_MOCK_PRICES: dict[str, float] = {
    "rakuten": 2980.0,
    "amazon_jp": 3080.0,
    "yahoo_shopping": 3050.0,
    "mercari": 2890.0,
    "au_pay_market": 3120.0,
}

_MOCK_LLM_RESPONSES: dict[str, str] = {
    "claim_extract": json.dumps(
        [{"claim_type": "最安値/最低価格", "quote": "業界最安値", "stated_value": 2980}],
        ensure_ascii=False,
    ),
    "compliance_reasoning": json.dumps(
        {"verdict": "WARNING", "rationale": "Mock LLM reasoning: borderline claim, review before publication."},
        ensure_ascii=False,
    ),
}


def stub_fetch_competitor_price(sku: str, platform: str) -> float | None:
    """Return a deterministic mock competitor price for `platform`."""
    return _MOCK_PRICES.get(platform)


def stub_search_precedents(claim_type: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a deterministic mock enforcement-case precedent list."""
    return [
        {
            "case_id": "mock-case-001",
            "claim_type": claim_type,
            "summary": "Mock 消費者庁 enforcement precedent for testing.",
            "outcome": "WARNING",
        }
    ]


def stub_llm_response(kind: str) -> str:
    """Return a deterministic mock LLM completion for the given prompt kind."""
    try:
        return _MOCK_LLM_RESPONSES[kind]
    except KeyError:
        raise ConfigError(
            f"stub_llm_response: unknown prompt kind {kind!r} (expected one of {sorted(_MOCK_LLM_RESPONSES)})"
        ) from None
