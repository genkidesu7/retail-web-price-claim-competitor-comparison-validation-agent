"""AGENTIC STAR Marketplace entrypoint — one-shot Pod process.

Referenced by agenticstar-deploy/Dockerfile's `CMD ["python", "cli.py"]`. Compiles
the agent, provisions its secrets, then hands off to
shared.bootstrap.marketplace_app for the Marketplace lifecycle (identity,
input, events, terminal delivery, exit).
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from framework.utils.config_loader import load_agent_config
from shared.bootstrap.marketplace_app import run_agent_marketplace
from src.graph.graph import PriceValidationAgent

# Add config overrides here if needed, instead of editing config/config.yaml.
extend_config: dict[str, Any] = {}

# input_context keys PreProcessNode reads; anything else in the message is ignored.
_REQUEST_FIELDS = ("product_sku", "own_price", "claim_text", "target_platforms")


def build_input_context(*, history: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Lift the structured request fields out of the latest user message.

    A Marketplace call delivers only chat text, but PreProcessNode needs
    product_sku / own_price / target_platforms (and claim_text) in input_context.
    The caller sends them as a JSON object in the message; a message that is not
    such an object contributes nothing, and PreProcessNode then rejects the request
    with its own "missing required field(s)" error.
    """
    for message in reversed(history or []):
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {key: payload[key] for key in _REQUEST_FIELDS if key in payload}
    return {}


if __name__ == "__main__":
    run_agent_marketplace(
        PriceValidationAgent,
        agent_name="ret-c2-327",
        config={**load_agent_config(Path(__file__).resolve().parent), **extend_config},
        build_input_context=build_input_context,
    )
