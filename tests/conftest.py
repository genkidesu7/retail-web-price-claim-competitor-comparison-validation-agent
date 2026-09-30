"""Shared pytest fixtures for RET-C2-327 (PriceValidationAgent) tests."""

from __future__ import annotations

import pytest

from framework.secrets.context import bound_secrets
from shared.secrets.inmemory_provider import InMemoryProvider


@pytest.fixture
def secrets():
    """InMemoryProvider pre-loaded with mock credential handles for all
    the only real integration this agent has (the Azure OpenAI LLM).
    Never real credentials — mock values only, per SDK test conventions.
    """
    return InMemoryProvider(
        {
            "AZURE_OPENAI_API_KEY": "mock-azure-key-for-testing",
            "AZURE_OPENAI_ENDPOINT": "https://mock-resource.services.ai.azure.com",
            "AZURE_OPENAI_DEPLOYMENT": "mock-deployment",
        }
    )


@pytest.fixture
def bound_test_secrets(secrets):
    """Bind mock secrets for the duration of a test."""
    with bound_secrets(secrets):
        yield secrets


def base_state(**overrides) -> dict:
    """Build a minimal-but-complete AgentState dict for node-level unit tests."""
    state = {
        "user_input": "",
        "input_context": {},
        "session_id": "test-session",
        "correlation_id": "test-correlation",
        "trace_id": "test-trace",
        "thread_id": "test-thread",
        "caller_trust_level": "ANONYMOUS",
        "caller_id": "",
        "hitl_allowed": True,
        "status": "pending",
        "retry_count": 0,
        "node_history": [],
        "error_log": [],
        "execution_time": {},
    }
    state.update(overrides)
    return state


def llm_returns(content: str):
    """call_llm replacement returning a fixed completion, whatever the prompt."""

    def _call_llm(kind, prompt, secrets, **_kwargs):  # noqa: ARG001
        return content

    return _call_llm
