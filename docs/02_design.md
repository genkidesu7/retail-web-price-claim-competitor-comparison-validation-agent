# Template Design Specification

Status: completed
Date: 2026-07-02
Reviewer: [TBD]

## Position in AgentCore Architecture

- **Agent Class**: PriceValidationAgent
- **L1 Base**: AgentBaseGraph (Cat 2 — fixed multi-step workflow for one job-to-be-done)
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

RET-C2-327 is a **Cat 2** template: it is not a single reusable capability (Cat 1), and
it does not need an autonomous think/act/observe loop to decide its own steps — the
6-stage workflow described in the proposal (InputParse → PriceClaimExtract →
CompetitorPriceFetch → ComplianceRuleCheck → ValidationReport → ResponseValidate) is a
fixed pipeline. The outer graph stays the standard 5-node backbone; the four domain
steps in the middle (PriceClaimExtract, CompetitorPriceFetch, ComplianceRuleCheck,
ValidationReport) are implemented as an **inner graph** wrapped by a `GraphNode` in the
outer `main` slot, per the Cat 2 composition pattern.

## Architecture Overview

### Node Configuration — Outer Graph (`src/graph/graph.py`)

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Framework default — sets up trace/correlation context | — | — | InitializeNode (default) |
| pre_process | **InputParse** — validate required fields (`product_sku`, `own_price`, `claim_text`, `target_platforms`), reject negative/implausible prices, resolve target platforms; S-1 gate (automatic) | `user_input` | `validated_input`, `product_sku`, `own_price`, `claim_text`, `target_platforms`, `status` | FunctionNode |
| main | **PriceValidationGraphNode** — wraps inner domain workflow graph (4 steps below) | `validated_input`, `product_sku`, `own_price`, `claim_text`, `target_platforms` | `claims`, `competitor_prices`, `validation_results`, `status` | GraphNode |
| post_process | **ResponseValidate** — S-3 output gate (block "safe"/PASS verdicts lacking `min_competitor_count` evidence), attach mandatory disclaimer, format final response; S-4 audit trail write | `validation_results`, `claims`, `competitor_prices` | `result`, `disclaimer`, `status` | FunctionNode |
| finalize | Framework default — emits final trace event | — | — | FinalizeNode (default) |

### Node Configuration — Inner Graph (`src/graph/domain_workflow_graph.py`, `PriceValidationWorkflowGraph`, inherits `BaseGraph`)

| Node | Responsibility | Input State | Output State |
|------|---------------|-------------|--------------|
| claim_extract | **PriceClaimExtract** — LLM extracts and classifies price claims into 3 types (最安値/最低価格, 通常価格 MSRP, 割引率); tags each with verbatim quote | `validated_input` (fallback `user_input`), `claim_text` | `claims` (list of `{claim_type, quote, stated_value}`) |
| competitor_fetch | **CompetitorPriceFetch** — calls Scrapling API for live Japan EC competitor prices across `target_platforms`; validates `min_competitor_count >= 3` for 最安値 claims | `claims`, `target_platforms` | `competitor_prices` (dict: platform → price), `fetch_timestamp`, `min_competitor_count_met` |
| compliance_check | **ComplianceRuleCheck** — arithmetic checks (own_price vs competitors, MSRP vs 1.5× median, discount rate correctness); borderline cases → vector KB search on 消費者庁 enforcement precedents + LLM reasoning | `claims`, `competitor_prices`, `own_price` | `rule_check_results` (per-claim verdict + rationale) |
| report_assemble | **ValidationReport** — assembles per-claim verdict (VIOLATION/WARNING/PASS), evidence, 景品表示法 article citation, remediation recommendation | `rule_check_results`, `competitor_prices`, `fetch_timestamp` | `validation_results` (list of per-claim report objects) |

Inner graph topology: linear, `claim_extract → competitor_fetch → compliance_check → report_assemble`.
No conditional branching needed — a missing/insufficient competitor price count is
represented as a per-claim "INSUFFICIENT DATA" verdict in `report_assemble`, not a
graph-level route, so the pipeline always runs to completion and produces an auditable
result.

**⚠️ Inner-node fallback rule:** `claim_extract` (the inner graph's entry node) must
read `state.get("validated_input", state.get("user_input", ""))`, not `validated_input`
alone — the inner graph receives a fresh state from `GraphNode.execute()` that only
contains `user_input` unless `extract_input()` is designed to carry the richer fields
forward (see Composition Pattern below).

### Data Flow

```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                            ↓ (retry, max_retry=3)
                                          pre_process
```

```
main slot (PriceValidationGraphNode.execute()):
  claim_extract → competitor_fetch → compliance_check → report_assemble
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| product_sku | str | Product identifier for the claim under review | Yes |
| own_price | float | Merchant's own listed price | Yes |
| claim_text | str | Raw marketing copy containing price claim(s) | Yes |
| target_platforms | list[str] | Japan EC platforms to fetch competitor prices from (e.g. `["rakuten", "amazon_jp"]`) | Yes |
| validated_input | str | Sanitized/validated version of claim_text after S-1 gate | No (set by pre_process) |
| claims | list[dict] | Extracted claims: `{claim_type: str, quote: str, stated_value: float}` | No (set by main) |
| competitor_prices | dict[str, float] | Platform → fetched competitor price | No (set by main) |
| fetch_timestamp | str (ISO 8601) | When competitor prices were fetched | No (set by main) |
| min_competitor_count_met | bool | Whether ≥3 competitor prices were found for 最安値 claims | No (set by main) |
| rule_check_results | list[dict] | Per-claim arithmetic/LLM compliance check output | No (set by main, inner-only) |
| validation_results | list[dict] | Per-claim verdict: `{claim_text, claim_type, verdict, evidence, article, recommendation}` | No (set by main) |
| result | dict | Final structured output returned to caller | No (set by post_process) |
| disclaimer | str | Mandatory "confirm with legal counsel" disclaimer text | No (set by post_process) |
| status | str (AgentStatus) | Node execution status | Yes (framework-managed) |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)
- `fetch_timestamp` stored as ISO 8601 string, not `datetime` (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle) — used to resolve Scrapling API credential handle and vector KB connection in `src/services/`
- [x] ConnectionPolicy (retry/timeout strategy) — applied to Scrapling API calls (transient network failures → RETRY, bounded by `max_retry`)
- [x] SecurityViolationError — raised by S-1 gate on malformed/negative-price input
- [x] S-2: `_extra_security_gate_input()` — domain-specific input check hook
      implemented on the `pre_process` FunctionNode: reject negative `own_price`,
      reject empty `claim_text`, validate `target_platforms` against an allow-list of
      known Japan EC platforms. Runs after the default PII scan.
- [x] S-3: `_extra_security_gate_output()` — domain-specific output check hook
      implemented on the `post_process` FunctionNode: block any `validation_results`
      entry with `verdict == "PASS"` that lacks `min_competitor_count_met == True`
      evidence (prevents false-assurance PASS verdicts per the proposal's top risk).
      Runs after the default credential scan.
- [x] S-4: `emit_trace_event()` — domain-specific events emitted inside `execute()`:
      `price_claim_extracted` (in inner `claim_extract`), `competitor_prices_fetched`
      (in inner `competitor_fetch`, includes `fetch_timestamp` and platform count),
      `compliance_verdict_issued` (in inner `report_assemble`, one per claim — this is
      the primary audit record for 消費者庁 inquiry evidence per the proposal).
      Framework `node_start`/`node_complete`/`node_error` are NOT re-emitted.

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

`pre_process` and `post_process` are `FunctionNode` subclasses (automatic gates apply).
`main` is a `GraphNode` (deliberate no-op — the outer S-1/S-3 gates on `pre_process`/
`post_process` already bound the boundary; inner nodes are plain `BaseGraph` nodes not
individually gated).

### Composition Pattern

- **Pattern**: GraphNode (subgraph)
- **Composition target**: `src/graph/domain_workflow_graph.py` → `PriceValidationWorkflowGraph`, inheriting `BaseGraph` (fully custom linear topology: `claim_extract → competitor_fetch → compliance_check → report_assemble`; not the standard pre_process/main/post_process shape, so `BaseGraph` rather than `AgentBaseGraph` for the inner graph)
- **Error propagation strategy**: `propagate` — Scrapling API failures or compliance-check errors surface as `SubgraphError` to the outer graph, which routes to `ERROR` status rather than silently degrading. Per the proposal's risk table, a Scrapling anti-bot block should not become a false PASS; the inner `competitor_fetch` node validates `min_competitor_count_met` and includes an "INSUFFICIENT DATA" verdict path in `report_assemble` (graceful degradation lives in the inner graph's own logic, not via `error_strategy: handle`, since the failure is a legitimate per-claim outcome — not an unexpected exception).
- `propagate_hitl`: `False` — this template has no HITL requirement per the proposal (no `hitl.enabled` in scope).
- `PriceValidationGraphNode.extract_input()` returns `state.get("validated_input", state.get("user_input", ""))`, mirroring `claim_text`. Because the inner graph's `claim_extract` node needs `product_sku`, `own_price`, and `target_platforms` too (not just the claim text string), `_parent_config()` is overridden to forward these as inner-graph config keys, and `claim_extract` reads them via `config["configurable"]` rather than relying solely on the single string passed through `extract_input()`.
- `merge_output()` maps the inner graph's `get_output()` dict (`{claims, competitor_prices, validation_results, status}`) directly into outer state keys of the same name.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required); Scrapling API client and vector KB client live under `src/services/` and are the only place external SDKs (Scrapling, vector DB client) are imported

## Services (`src/services/`)

- **ScraplingPriceService** — wraps the Scrapling API (D4Vinci/Scrapling) HTTP client;
  resolves API credential via `InvocationContext.credential_handle`; exposes
  `fetch_competitor_prices(sku, platforms) -> dict[str, float]`; applies
  `ConnectionPolicy` retry/timeout; supports mock mode for tests.
- **EnforcementCaseKBService** — vector KB search over 消費者庁 enforcement case
  precedents; exposes `search_precedents(claim_type, context) -> list[dict]` for
  borderline compliance reasoning in `compliance_check`.
- **LLM Service** (shared, existing framework service) — used by `claim_extract` for
  claim classification and by `compliance_check` for borderline-case reasoning.

## Error Handling

- **S-1 (input)**: `pre_process` rejects missing required fields, negative prices, and
  unrecognized platform names → `SecurityViolationError`, routed to outer `ERROR`.
- **Scrapling API transient failure** (timeout, rate limit): `RETRY` via
  `ConnectionPolicy`, bounded by `max_retry: 3` (config/agent.yaml); on exhaustion,
  inner graph proceeds with partial `competitor_prices` and `report_assemble` marks
  affected claims "INSUFFICIENT DATA" rather than failing the whole invocation.
- **Scrapling API hard failure / anti-bot block** (proposal risk, 🔴 High): inner graph
  does not raise for this case — it is modeled as a per-claim data-sufficiency
  condition, not an exception, per the proposal's mitigation ("graceful degradation:
  return INSUFFICIENT DATA").
- **S-3 (output)**: `post_process` blocks any PASS verdict lacking sufficient evidence
  (`min_competitor_count_met`), enforcing the proposal's top mitigation for false
  assurance risk.
- **Unrecoverable errors** (e.g. vector KB unreachable): inner `compliance_check` raises;
  `error_strategy: propagate` surfaces as `SubgraphError` → outer graph `ERROR` status.

## Security Considerations

- `own_price`, `claim_text` are not credentials/PII — no masking required beyond default
  S-2 scan.
- The LLM (Azure OpenAI) credentials are resolved exclusively via `ctx.secrets.require(...)`
  inside `src/services/service.py`; never placed in State or logs. The Scrapling and
  enforcement-case KB services have no live client wired and serve `mock_data` stubs, so
  they hold no credentials.
- `required_trust_level: VERIFIED_EXTERNAL` (already set in `config/agent.yaml`) — this
  agent is invoked by authenticated publishing pipelines / compliance officers, not
  anonymous callers.
- S-4 audit trail (`compliance_verdict_issued` events) is the defensible record for
  消費者庁 inquiry evidence called out in the proposal — every claim's verdict, evidence,
  and fetch timestamp must be captured, not just success/failure.

## Performance Requirements

- Target end-to-end latency: <2 minutes per proposal ("Success Metrics" / "Business
  Value" in `docs/01_proposal.md`), dominated by Scrapling API round-trip time across
  target platforms and LLM claim extraction/reasoning calls.
- `timeout_seconds: 30` (config/agent.yaml) applies per external call; overall pipeline
  budget is enforced by the caller (publishing pipeline), not by this agent internally.

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed 6-step workflow with no need for autonomous step planning; matches Cat 2 classification already confirmed in `config/agent.yaml` (`category: "Cat 2"`) and `docs/01_proposal.md` |
| Composition pattern | Standalone (all in pre/main/post) | GraphNode (inner graph) | **GraphNode** | 4 of the 6 conceptual steps (extract, fetch, check, report) are themselves a multi-node pipeline that doesn't fit inside a single `main` FunctionNode; Cat 2 convention wraps this complexity in an inner `BaseGraph` |
| Inner graph base | BaseGraph | AgentBaseGraph | **BaseGraph** | Inner topology is a fully custom linear chain (`claim_extract → competitor_fetch → compliance_check → report_assemble`), not the pre_process/main/post_process shape |
| Error propagation | propagate | handle | **propagate** | Scrapling anti-bot blocks and insufficient data are modeled as in-band per-claim verdicts ("INSUFFICIENT DATA"), not exceptions; genuine unexpected errors (e.g. vector KB down) should fail fast and surface to the outer caller rather than being silently swallowed |
| Graceful degradation for Scrapling failures | Raise SubgraphError | Per-claim INSUFFICIENT DATA verdict | **Per-claim INSUFFICIENT DATA verdict** | Matches proposal's explicit mitigation for the 🔴 High "Scrapling blocked" risk; preserves audit trail and avoids failing the whole request over one platform's block |
