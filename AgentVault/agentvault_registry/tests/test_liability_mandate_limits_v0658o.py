"""V0658 (o): a Cockpit mandate's own limits narrow what it conveys, on every call the liability gate decides.

check_liability_gate checked that a signed mandate underwrites the agent, that its scope covers the action, the
standing consent and the presence step-up, and never the mandate's own `limits` (max_per_tx, currency): an amount
above the owner's per-transaction limit, or in another currency, passed. Now the limits clamp every gated call: under
enforce it is refused (403, the reason named, the block in the evidence chain), under shadow the log line says it
would be, and with liability off nothing is read. A mandate without limits, and a call that carries no amount or no
currency, are unchanged. The documented rule (authority "narrowed ... by the mandate's limits") is checked against
the gate. Red on 13d2011ac: the over-limit and wrong-currency calls pass.
"""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.services import liability as liab

DID = "did:theprotocol:sub-agent-0001"
MID = "lm_" + "cd" * 20


class _GateDB:
    def __init__(self, row):
        self.row, self.sql, self.commits = row, [], 0

    async def execute(self, stmt, params=None):
        self.sql.append(" ".join(str(stmt).split()))
        row = self.row
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))

    async def get(self, model, pk):
        return SimpleNamespace(id=pk)

    async def commit(self):
        self.commits += 1


def _row(**kw):
    return {"id": MID, "developer_id": 6, "agent_did": DID, "tier": "T1", "scope": ["contracts.engage"],
            "limits": {"max_per_tx": "50", "currency": "ECU"}, "status": "signed", "expires_at": None, **kw}


@pytest.fixture
def mode(monkeypatch):
    from agentvault_registry.config import settings
    from agentvault_registry.services import org_policy
    evidence = []

    async def org(db, did):
        return {}

    async def resolved(db, m, dev):
        return {"valid": True, "effective_scope": list(m.scope), "reasons": [], "authority_now": []}

    async def ev(db, mid, event_type, payload, **kw):
        evidence.append((event_type, payload))
    monkeypatch.setattr(org_policy, "get_org_settings", org)
    monkeypatch.setattr(liab, "resolve_mandate", resolved)
    monkeypatch.setattr(liab, "append_evidence", ev)
    monkeypatch.setattr(liab, "presence_threshold", lambda: 0.0)

    def set_mode(m):
        monkeypatch.setattr(settings, "LIABILITY_MODE", m, raising=False)
    set_mode.evidence = evidence
    return set_mode


def _gate(db, **kw):
    return asyncio.run(liab.check_liability_gate(db, DID, "contracts.engage", action_ref="contract-release:c-9:1",
                                                 **kw))


def test_under_enforce_an_amount_over_the_mandates_max_per_tx_is_refused_and_one_at_it_passes(mode):
    mode("enforce")
    db = _GateDB(_row())
    with pytest.raises(HTTPException) as e:
        _gate(db, amount="50.000001", currency="ECU")
    assert e.value.status_code == 403 and "over_mandate_max_per_tx:50" in e.value.detail
    assert mode.evidence[-1][0] == "gate_block" and "over_mandate_max_per_tx:50" in mode.evidence[-1][1]["reasons"]
    assert db.commits == 1, "the block's evidence is committed before the 403"
    _gate(_GateDB(_row()), amount="50", currency="ECU")
    assert mode.evidence[-1][0] == "gate_pass"


def test_under_enforce_another_currency_than_the_mandates_is_refused(mode):
    mode("enforce")
    with pytest.raises(HTTPException) as e:
        _gate(_GateDB(_row()), amount="5", currency="ACU")
    assert e.value.status_code == 403 and "mandate_currency:ECU" in e.value.detail


def test_a_standing_consent_does_not_lift_the_mandates_own_limit(mode):
    mode("enforce")
    row = _row(limits={"max_per_tx": "50", "ceiling": {"scope": ["contracts.engage"], "max_per_tx": "500",
                                                       "currency": "ECU"}})
    with pytest.raises(HTTPException) as e:
        _gate(_GateDB(row), amount="60", currency="ECU")
    assert "over_mandate_max_per_tx:50" in e.value.detail


def test_a_mandate_without_limits_and_a_call_without_an_amount_are_unchanged(mode):
    mode("enforce")
    _gate(_GateDB(_row(limits=None)), amount="5000", currency="ACU")
    _gate(_GateDB(_row()), amount=None, currency=None)
    assert [e[0] for e in mode.evidence] == ["gate_pass", "gate_pass"]


def test_under_shadow_the_log_line_says_it_would_be_refused_and_nothing_is_refused(mode, caplog):
    mode("shadow")
    with caplog.at_level(logging.INFO, logger=liab.logger.name):
        _gate(_GateDB(_row()), amount="75", currency="ECU")
    line = next(r.getMessage() for r in caplog.records if "[LIABILITY-SHADOW]" in r.getMessage())
    assert "ok=False" in line and "over_mandate_max_per_tx:50" in line
    assert mode.evidence == [], "shadow writes no evidence and refuses nothing"


def test_with_liability_off_nothing_is_read(mode):
    mode("off")
    db = _GateDB(_row())
    assert _gate(db, amount="5000", currency="ACU") is None and db.sql == []


def test_the_documented_rule_is_the_rule_the_gate_applies(mode):
    doc = (Path(liab.__file__).resolve().parents[1] / "static" / "new_registry_frontend" / "src" / "assets" / "docs"
           / "whitepaper" / "v2-draft.md").read_text(encoding="utf-8")
    assert "narrowed by any capability permit and by the mandate's limits" in doc
    mode("enforce")
    with pytest.raises(HTTPException):
        _gate(_GateDB(_row()), amount="51", currency="ECU")
    assert liab.mandate_limits_refuse({"max_per_tx": "50", "currency": "ECU"}, amount="51", currency="ecu") == \
        ["over_mandate_max_per_tx:50"]
    assert liab.mandate_limits_refuse({"max_per_tx": "x"}, amount="1", currency=None) == \
        ["mandate_limit_unreadable:max_per_tx"], "a money limit nobody can read refuses"
