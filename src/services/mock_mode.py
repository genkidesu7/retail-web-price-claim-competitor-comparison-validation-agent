"""AgentCore Platform v1.0"""

# Single source of truth for "is mock mode on?". Every service that gates
# real-vs-mock behaviour imports mock_mode_enabled() from here — never
# re-implement the flag lookup per service.
#
# Two flags are accepted:
#   USE_MOCK       canonical; what tests and local runs set.
#   STG_MOCK_MODE  what the scaffold `deploy-stg` CI job actually sets.
# Mock mode is on when either resolves truthy. The values are feature flags,
# not credentials, so reading os.environ (and a local .env) directly is OK.

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

MOCK_FLAG_NAMES: tuple[str, ...] = ("USE_MOCK", "STG_MOCK_MODE")
_TRUTHY = frozenset({"1", "true", "yes"})

_env: dict[str, str | None] = dotenv_values(Path(__file__).parent.parent.parent / ".env")


def _get_flag(key: str) -> str:
    """OS env takes precedence over .env file."""
    return os.environ.get(key) or _env.get(key) or ""


def mock_mode_enabled() -> bool:
    """True when any accepted mock flag (USE_MOCK / STG_MOCK_MODE) is truthy."""
    return any(_get_flag(name).strip().lower() in _TRUTHY for name in MOCK_FLAG_NAMES)
