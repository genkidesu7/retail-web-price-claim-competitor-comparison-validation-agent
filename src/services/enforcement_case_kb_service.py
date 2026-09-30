"""AgentCore Platform v1.0"""

# Service layer: search over 消費者庁 enforcement case precedents.
# Must NOT contain business logic, routing, or credentials.
# Nodes call this; this calls shared/services/ for external integrations.
#
# No live vector KB is provisioned for this agent, so every call is served by
# the mock_data stub. That holds in real (non-mock) runs too: only the LLM path
# becomes real when mock mode is off.

from __future__ import annotations

from typing import Any

from src.services.mock_data import stub_search_precedents


class EnforcementCaseKBService:
    """Precedent search over 消費者庁 enforcement cases.

    Usage from a node::

        service = EnforcementCaseKBService()
        precedents = await service.search_precedents(claim_type, context)
    """

    async def search_precedents(self, claim_type: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Search enforcement case precedents for a borderline claim.

        Args:
            claim_type: One of the 3 design-specified claim types.
            context: Domain context (e.g. claim quote, computed values) used
                to shape the search query.

        Returns:
            List of precedent dicts.
        """
        return await self._call_external(claim_type, context)

    async def _call_external(self, claim_type: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        return stub_search_precedents(claim_type, context)
