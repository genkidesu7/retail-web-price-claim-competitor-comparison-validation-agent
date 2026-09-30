"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption.  Extend AgentState with agent-specific
# fields only.  Do NOT add credentials, secrets, or Pydantic models.

from typing import Any

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Agent state for the Retail Price Claim & Competitor Comparison
    Validation Agent (RET-C2-327).

    All shared fields (user_input, status, session_id, node_history,
    error_log, hitl_*, etc.) are inherited from AgentState.
    """

    # ---- Required input fields (validated by pre_process) ----
    product_sku: str  # Product identifier for the claim under review
    own_price: float  # Merchant's own listed price
    claim_text: str  # Raw marketing copy containing price claim(s)
    target_platforms: list[str]  # Japan EC platforms to fetch competitor prices from

    # ---- Set by pre_process ----
    validated_input: str  # Sanitized/validated version of claim_text after S-1 gate

    # ---- Set by main (inner graph outputs merged into outer state) ----
    claims: list[dict[str, Any]]  # Extracted claims: {claim_type, quote, stated_value}
    competitor_prices: dict[str, float]  # Platform -> fetched competitor price
    fetch_timestamp: str  # ISO 8601 str — when competitor prices were fetched. Never datetime.
    min_competitor_count_met: bool  # Whether >=3 competitor prices were found for 最安値 claims
    rule_check_results: list[dict[str, Any]]  # Per-claim arithmetic/LLM compliance check output (inner-only)
    validation_results: list[
        dict[str, Any]
    ]  # Per-claim verdict: {claim_text, claim_type, verdict, evidence, article, recommendation}

    # ---- Set by post_process ----
    result: dict[str, Any]  # Final structured output returned to caller
    disclaimer: str  # Mandatory "confirm with legal counsel" disclaimer text
