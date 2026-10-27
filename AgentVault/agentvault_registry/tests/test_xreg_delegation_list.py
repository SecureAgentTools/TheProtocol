"""§FESUITE V0595 ("also close console gaps"): GET /agents/delegate-cross-registry lists what the acting agent delegated
to agents on other registries. The issue side persists no table of its own (sign and ship only), so the list folds its
audit record: the issue rows (with the credential's permissions, expiry and whether the delegate's home took it) and the
revoke rows (a revoke the delegate's home took marks it revoked). The database is a fake that answers those rows.
"""
import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import agent_delegation_api as ada

NOW = dt.datetime.now(dt.timezone.utc)


def _issue(cid, outcome="success", hours=24, delegate="did:theprotocol:far1"):
    return {"timestamp": NOW, "action": "ironkey.xreg_delegation_issue", "outcome": outcome, "target_id": delegate,
            "details": json.dumps({"credential_id": cid, "delegate_registry": "https://sandbox-a.theprotocol.cloud",
                                   "permissions": ["transfer.local"], "caveats": {},
                                   "expires_at": (NOW + dt.timedelta(hours=hours)).isoformat()})}


def _revoke(cid, outcome="success"):
    return {"timestamp": NOW, "action": "ironkey.xreg_delegation_revoke", "outcome": outcome, "target_id": cid,
            "details": json.dumps({"delegate_registry": "https://sandbox-a.theprotocol.cloud", "side": "issuer"})}


class _Db:
    def __init__(self, rows, owed=()):
        self.rows, self.asked, self.owed = rows, [], list(owed)

    async def execute(self, stmt, params=None):
        if "xreg_revokes_owed" in str(stmt):   # D6-272: the owed deliveries of this issuer's revokes
            owed = self.owed
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: owed))
        self.asked.append(params)
        rows = self.rows
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


def test_the_list_folds_issues_and_revokes_into_states(monkeypatch):
    monkeypatch.setenv("AGENT_XREG_DELEGATION_ENABLED", "true")
    db = _Db([_revoke("c2"), _issue("c1"), _issue("c2"), _issue("c3", outcome="ship_failed"), _issue("c4", hours=-1)])
    out = asyncio.run(ada.list_my_xreg_delegations(issuer=SimpleNamespace(did="did:theprotocol:me"), db=db))
    assert db.asked[0] == {"d": "did:theprotocol:me"}, "only this agent's own record is read"
    by = {d["credential_id"]: d for d in out["delegations"]}
    assert by["c1"]["state"] == "active" and by["c1"]["delivered"] is True and by["c1"]["permissions"] == ["transfer.local"]
    assert by["c2"]["state"] == "revoked" and by["c2"]["revoke_delivered"] is True
    assert by["c3"]["state"] == "not_delivered"
    assert by["c4"]["state"] == "expired"


def test_a_revoke_their_registry_has_not_taken_yet_is_revoked_and_says_its_delivery(monkeypatch):
    """Corrected for D6-272 (2026-10-17). This test read a revoke whose message had not arrived as no revoke ("active").
    Since V0620 the issuer-side record decides: the delegate's registry asks this one at use and is told the delegation
    is revoked, so the list says `revoked`, `revoke_delivered` false, and how the delivery stands (`revoke_delivery`,
    from the owed row the worker sends again; a revoke recorded before the owed table existed reads not_queued)."""
    from agentvault_registry import models
    monkeypatch.setenv("AGENT_XREG_DELEGATION_ENABLED", "true")
    owed = models.XRegRevokeOwed(credential_id="c1", issuer_did="did:theprotocol:me",
                                 delegate_registry="https://sandbox-a.theprotocol.cloud", attempts=2,
                                 next_attempt_at=NOW + dt.timedelta(minutes=5), created_at=NOW, last_status=503,
                                 last_error="HTTP 503: unavailable", credential_expires_at=None, done_at=None,
                                 dead_at=None)
    db = _Db([_revoke("c1", outcome="ship_failed"), _revoke("c2", outcome="ship_failed"), _issue("c1"), _issue("c2")],
             owed=[owed])
    out = asyncio.run(ada.list_my_xreg_delegations(issuer=SimpleNamespace(did="did:theprotocol:me"), db=db))
    by = {d["credential_id"]: d for d in out["delegations"]}
    assert by["c1"]["state"] == "revoked" and by["c1"]["revoke_delivered"] is False
    assert by["c1"]["revoke_delivery"]["state"] == "retrying" and by["c1"]["revoke_delivery"]["attempts"] == 2
    assert by["c2"]["state"] == "revoked" and by["c2"]["revoke_delivery"]["state"] == "not_queued"


def test_the_rail_off_answers_so(monkeypatch):
    monkeypatch.setenv("AGENT_XREG_DELEGATION_ENABLED", "false")
    with pytest.raises(HTTPException) as e:
        asyncio.run(ada.list_my_xreg_delegations(issuer=SimpleNamespace(did="did:theprotocol:me"), db=_Db([])))
    assert e.value.status_code == 403 and "disabled" in str(e.value.detail)
