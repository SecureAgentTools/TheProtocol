"""Agent card management contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/agent-cards/", auth="developer", category="agent_cards", idempotent=False)
class CreateAgentCard:
    """Create an agent card (legacy)."""
    def body(self, ctx):
        return {
            "card_data": {
                "name": "AAA+ Test Card",
                "description": "Auto-created by contract",
                "humanReadableId": "aaa-test-card",
                "schemaVersion": "1.0",
                "agentVersion": "1.0.0",
                "url": "https://example.com/agent",
                "provider": {"name": "Test", "url": "https://example.com"},
                "capabilities": {"text-generation": {"description": "test"}},
                "authSchemes": [{"scheme": "oauth2", "tokenUrl": "https://example.com/token"}],
                "metadata": {},
            }
        }
    expected_status = [200, 201, 422]


@Endpoint(method="GET", path="/agent-cards/", auth="developer", category="agent_cards", idempotent=True, slow_timeout_sec=60.0)
class ListAgentCardsExtras:
    """List agent cards (also in discover.py — registers idempotent)."""
    expected_status = 200
