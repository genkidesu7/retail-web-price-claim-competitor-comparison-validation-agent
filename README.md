# RET-C2-327 — Retail Web Price Claim & Competitor Comparison Validation Agent

> **Category**: Cat 2 (Domain-specific ToolCallingAgent)
> **Industry**: RET (Retail)

## Overview

Validates price claims in marketing copy against competitor prices before publication, using 景品表示法
(Act against Unjustifiable Premiums and Misleading Representations) compliance rules. The agent extracts
and classifies three claim types — 最安値/最低価格 (lowest price), 通常価格 (regular price) and 割引率
(discount rate) — checks each one against competitor prices, and returns a per-claim verdict
(VIOLATION / WARNING / PASS / INSUFFICIENT DATA) with an article citation and a remediation recommendation.
Borderline cases are escalated to LLM reasoning over enforcement-case precedents. A PASS is never issued
without enough competitor data behind it.

Competitor price lookup and the enforcement-case knowledge base are service seams
(`ScraplingPriceService`, `EnforcementCaseKBService`) with **no live backend wired**: they always return
sample data from `src/services/mock_data.py`. Only the LLM call is real when mock mode is off.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |
| Azure OpenAI (real, non-mock runs only) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` (bare resource endpoint) and `AZURE_OPENAI_DEPLOYMENT`. |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

Set `USE_MOCK=true` (or `STG_MOCK_MODE=true`) to run without any secrets; the LLM calls then return
deterministic stubs. Without either flag a missing Azure OpenAI secret fails fast.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specification
```

See `docs/02_design.md` for the design and `docs/03_test_spec.md` for the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own: wire real clients behind
   `ScraplingPriceService` and `EnforcementCaseKBService`, replacing the `mock_data.py` stubs.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

The automated verdicts are assistance, not legal advice — confirm with legal counsel before publishing a claim.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.

---
