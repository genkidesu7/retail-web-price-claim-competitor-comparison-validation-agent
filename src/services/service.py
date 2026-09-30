"""AgentCore Platform v1.0"""

# Service layer: the one place that constructs the LLM client.
# Must NOT contain business logic or routing. Nodes call call_llm(); it calls
# shared/services/llm for the real (non-mock) path.

from __future__ import annotations

from framework.secrets.base import SecretProvider

from src.services.mock_data import stub_llm_response
from src.services.mock_mode import mock_mode_enabled


def call_llm(
    kind: str,
    prompt: str,
    secrets: SecretProvider,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> str:
    """Return the LLM completion text for `prompt`.

    Mock mode short-circuits *before* any credential is required, so a checkout
    with no provisioned secrets (fresh CI runner) still reaches the stub path.
    Outside mock mode all three Azure OpenAI secrets are required and a missing
    one fails fast with MissingSecret — never a placeholder credential.

    Args:
        kind: Prompt kind ("claim_extract" or "compliance_reasoning"); selects
            the mock stub.
        prompt: User prompt text.
        secrets: Invocation-scoped provider (ctx.secrets).
    """
    if mock_mode_enabled():
        return stub_llm_response(kind)

    from shared.services.llm.azure_openai_client import AzureOpenAIClient  # lazy import

    api_key = secrets.require("AZURE_OPENAI_API_KEY")
    azure_endpoint = secrets.require("AZURE_OPENAI_ENDPOINT")
    azure_deployment = secrets.require("AZURE_OPENAI_DEPLOYMENT")

    client = AzureOpenAIClient(
        config={
            "api_key": api_key,
            "azure_endpoint": azure_endpoint,
            "azure_deployment": azure_deployment,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
    )
    return str(client.complete([{"role": "user", "content": prompt}])["content"])
