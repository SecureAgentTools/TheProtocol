"""§FRAMEKIT P3.1 (2026-09-12) — the CONSUL compliance overview lists every peer_registries row, not only the
diagnostics targets. EU and ASIA (sovereign frames, no Command Center slugs) showed NO peers while ten
first-sight baselines existed (§TRUSTCHAIN, named not fixed)."""
from datetime import datetime, timezone

import pytest

from agentvault_registry import models
from agentvault_registry.routers import consul_admin as ca


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    """Answers the two SELECTs get_overview issues, in order: peers, then compliance rows."""
    def __init__(self, peers, compliances):
        self._answers = [peers, compliances]

    async def execute(self, _stmt):
        return _Result(self._answers.pop(0))


def _peer(i, name, status="ACTIVE", td=None, ptype="frame", url=None):
    p = models.PeerRegistry(name=name, base_url=url or f"https://{name}.example", status=status, peer_type=ptype, trust_domain=td)
    p.id = i
    return p


@pytest.mark.asyncio
async def test_overview_rows_for_peers_without_a_target(monkeypatch):
    peers = [_peer(1, "asia", td="asia.theprotocol.cloud"), _peer(2, "amsterdam", ptype="cloud_operator"),
             _peer(3, "ghost", status="INACTIVE"), _peer(4, "quarantined-once", status="INACTIVE")]
    c1 = models.FederatedRegistryCompliance(peer_registry_id=1, federation_status="federated", policy_hash="a" * 64,
                                            last_poll_at=datetime.now(timezone.utc), consecutive_poll_failures=0, drift_events_count=0)
    c4 = models.FederatedRegistryCompliance(peer_registry_id=4, federation_status="quarantined", policy_hash="b" * 64,
                                            last_poll_at=None, consecutive_poll_failures=3, drift_events_count=2)

    class _State:
        compliance_enforcement_mode = "dry_run"

    async def _no_targets(_db):
        return []

    async def _state(_db):
        return _State()

    async def _no_reach(_db, include_ok=True):
        return None

    monkeypatch.setattr(ca, "list_diag_targets", _no_targets)
    monkeypatch.setattr(ca, "_get_singleton_state", _state)
    from agentvault_registry.services import federation_reachability
    monkeypatch.setattr(federation_reachability, "build_report", _no_reach)
    ov = await ca.get_overview(db=_FakeDB(peers, [c1, c4]))
    by = {r.operator_id: r for r in ov.peers}
    # the ACTIVE frame with a baseline, the ACTIVE operator without one, the INACTIVE row that holds a record;
    # the INACTIVE ghost with no record is NOT a row (a deactivated peer with nothing to say is noise)
    assert set(by) == {"asia", "amsterdam", "quarantined-once"}
    assert by["asia"].peer_registry_id == 1 and by["asia"].has_compliance_record and by["asia"].federation_status == "federated"
    assert by["asia"].frame == "asia.theprotocol.cloud" and by["asia"].role == "frame" and by["asia"].cloud_url == "https://asia.example"
    assert by["amsterdam"].has_compliance_record is False and by["amsterdam"].role == "cloud_operator"
    assert by["quarantined-once"].federation_status == "quarantined" and by["quarantined-once"].peer_status == "INACTIVE"
    assert ov.peers_total == 3 and ov.peers_with_compliance == 2
    assert ov.peers_federated == 1 and ov.peers_quarantined == 1 and ov.peers_never_polled == 1 and ov.peers_unreachable_streak == 1


def test_peer_only_row_names_the_peer_by_itself():
    p = _peer(7, "Some Frame", td="some.example", ptype="frame", url="https://some.example")
    row = ca._peer_only_row(p, None)
    assert row.operator_id == "some-frame" and row.display_name == "Some Frame" and row.frame == "some.example"
    assert row.peer_registry_id == 7 and row.has_compliance_record is False and row.cloud_url == "https://some.example"


class _Scalar:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _DetailDB:
    """Answers the detail's SELECTs in order: every peer, then the one compliance row of the peer it resolved."""
    def __init__(self, peers, compliance_by_peer):
        self._peers, self._by = peers, compliance_by_peer
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        if self.calls == 1:
            return _Result(self._peers)
        pid = next((p.id for p in self._peers if f"= {p.id}" in str(stmt.compile(compile_kwargs={"literal_binds": True}))), None)
        return _Scalar(self._by.get(pid))


@pytest.mark.asyncio
async def test_every_operator_id_the_overview_lists_resolves_at_the_detail(monkeypatch):
    """§MCPTEST30 (2026-10-01): the detail searched only the diagnostics targets, so the overview's peer-only rows
    answered 404 there: the MCP tester took the overview's first row with a compliance record and got
    "operator_id='sandbox-alpha' not found in live Docker-discovery"."""
    peers = [_peer(1, "Sandbox Alpha", td="sandbox-a.example"), _peer(2, "amsterdam", ptype="cloud_operator")]
    c1 = models.FederatedRegistryCompliance(peer_registry_id=1, federation_status="federated", policy_hash="a" * 64,
                                            last_poll_at=datetime.now(timezone.utc), consecutive_poll_failures=0,
                                            drift_events_count=0, policy_json=None)

    async def _no_targets(_db):
        return []

    async def _no_fetch(url, **_kw):   # V0561: the detail asks for the whole answer (full=True)
        return None, None, "not fetched in a test"
    monkeypatch.setattr(ca, "list_diag_targets", _no_targets)
    monkeypatch.setattr(ca, "_fetch_live_policy", _no_fetch)
    d = await ca.get_peer_detail_by_operator("sandbox-alpha", db=_DetailDB(peers, {1: c1}))
    assert d.operator_id == "sandbox-alpha" and d.peer_registry_id == 1 and d.has_compliance_record is True
    assert d.federation_status == "federated" and d.frame == "sandbox-a.example" and d.role == "frame"
    d2 = await ca.get_peer_detail_by_operator("amsterdam", db=_DetailDB(peers, {}))
    assert d2.peer_registry_id == 2 and d2.has_compliance_record is False and d2.role == "cloud_operator"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await ca.get_peer_detail_by_operator("nobody", db=_DetailDB(peers, {}))
    assert e.value.status_code == 404 and "neither a live Docker-discovered target nor a peer row" in e.value.detail


@pytest.mark.asyncio
async def test_a_peer_a_target_already_names_is_not_found_by_its_own_slug(monkeypatch):
    """The overview names a peer that a target matched by the TARGET's operator_id, never by the peer's slug: the
    detail must agree, or one peer would answer under two names."""
    peers = [_peer(1, "amsterdam", ptype="cloud_operator")]

    async def _one_target(_db):
        return [{"operator_id": "op-amsterdam", "display_name": "amsterdam", "role": "operator", "containers": {}}]

    async def _frame(_t):
        return "eu"
    monkeypatch.setattr(ca, "list_diag_targets", _one_target)
    monkeypatch.setattr(ca, "_resolve_frame", _frame)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await ca.get_peer_detail_by_operator("amsterdam", db=_DetailDB(peers, {}))
    assert e.value.status_code == 404
