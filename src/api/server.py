"""AgentCore Platform v1.0"""

# Standalone HTTP entry point for the agent.
# Entry points are adapters only — no business logic here.
# For platform-level routing, AgentGateway calls agent.invoke() directly.

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from framework.utils.config_loader import load_config
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from shared.secrets import factory as secrets_factory
from shared.secrets.chained_provider import ChainedSecretProvider
from shared.secrets.env_provider import EnvProvider

from src.graph.graph import PriceValidationAgent

_NAMESPACE = "RET"
_AGENT_NAME = "ret-c2-327"

# Same config_dir / "config.yaml" convention as AgentRegistry._compile_and_cache() —
# absent config.yaml is tolerated. Without this the adapter would run with
# config={}, so hitl.enabled / memory_enabled / max_retry never reach the graph.
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
_config = load_config(str(_CONFIG_PATH)) if _CONFIG_PATH.exists() else {}

# Process env first (Marketplace "User-defined Environment Variables" and local
# `export`s), dotenv files second. EnvProvider is unscoped, which is safe here:
# this process runs exactly one agent.
_secrets_provider = ChainedSecretProvider(
    EnvProvider(namespace=_NAMESPACE, agent_name=_AGENT_NAME),
    secrets_factory(namespace=_NAMESPACE, agent_name=_AGENT_NAME),
    namespace=_NAMESPACE,
    agent_name=_AGENT_NAME,
)

agent = PriceValidationAgent(config=_config)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Compile and provision secrets once per process — not at import time, so a
    bare `import src.api.server` never has the side effect of compiling the graph."""
    # Mirror AgentRegistry._compile_and_cache()'s conditional checkpointer: hitl or
    # memory needs one, or interrupt()/memory silently no-ops on this path.
    needs_checkpointer = agent.config.get("memory_enabled") or agent.config.get("hitl", {}).get("enabled", False)
    agent.compile(checkpointer=MemorySaver() if needs_checkpointer else None)
    agent.provision_secrets(_secrets_provider)
    yield


app = FastAPI(title="Retail Price Claim & Competitor Comparison Validation Agent", lifespan=_lifespan)


class InvokeRequest(BaseModel):
    product_sku: str
    own_price: float
    claim_text: str
    target_platforms: list[str]
    session_id: str = ""


def _bearer_matches(supplied: str, expected: str) -> bool:
    """Constant-time bearer comparison that is safe for non-ASCII header input."""
    return secrets.compare_digest(supplied.encode(), f"Bearer {expected}".encode())


def _resolve_standalone_trust(
    current: TrustLevel, authorization: str, invoke_auth_token: str | None, internal_runner_token: str | None
) -> TrustLevel:
    """Authenticate standalone callers without allowing external-token elevation.

    STG_INTERNAL_RUNNER_TOKEN is a distinct, CI-generated deployment credential.
    It is considered only for an anonymous caller and maps exactly to INTERNAL;
    INVOKE_AUTH_TOKEN remains VERIFIED_EXTERNAL. Middleware-established trust is
    never changed.
    """
    if current is not TrustLevel.ANONYMOUS:
        return current
    if internal_runner_token and _bearer_matches(authorization, internal_runner_token):
        return TrustLevel.INTERNAL
    if invoke_auth_token and _bearer_matches(authorization, invoke_auth_token):
        return TrustLevel.VERIFIED_EXTERNAL
    if internal_runner_token or invoke_auth_token:
        raise HTTPException(status_code=401, detail="Token is invalid or expired.")
    return TrustLevel.ANONYMOUS


@app.post("/invoke")
async def invoke(req: InvokeRequest, request: Request) -> Any:
    # This adapter is the entry-point auth boundary (standalone equivalent of
    # platform AuthMiddleware). Both values are deployment-level caller credentials,
    # not agent secrets: no InvocationContext exists before this boundary, so
    # ctx.secrets cannot apply.
    trust = _resolve_standalone_trust(
        getattr(request.state, "trust_level", TrustLevel.ANONYMOUS),
        request.headers.get("authorization", ""),
        os.environ.get("INVOKE_AUTH_TOKEN"),
        os.environ.get("STG_INTERNAL_RUNNER_TOKEN"),
    )
    with bound_secrets(agent._secrets_provider):
        ctx = InvocationContext(
            session_id=req.session_id or str(uuid4()),
            caller_trust_level=trust,
            caller_id=getattr(request.state, "caller_id", ""),
        )
        input_context = {
            "product_sku": req.product_sku,
            "own_price": req.own_price,
            "target_platforms": req.target_platforms,
        }
        # Nodes call asyncio.run() internally, which raises inside uvicorn's running
        # event loop — offload the sync invoke to a worker thread. to_thread copies the
        # current contextvars, so the bound_secrets() ContextVar stays visible there.
        return await asyncio.to_thread(agent.invoke, req.claim_text, ctx=ctx, input_context=input_context)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": _AGENT_NAME}
