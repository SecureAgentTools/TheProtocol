"""§MCPTEST30 (V0561, agentvault2-09): the compliance page (CONSUL) as the sandbox measured it on 2026-10-03.

1. The overview sent no peer identity, so the console's roster read "identity pending" on every peer and grouped all
   of them under "Unmapped": each row now carries the trust domain a cross-frame operation would resolve (the
   resolver's order: the row's column, its signed card, the topology cache), the frame of this federation sharing it,
   and that frame's currency. A registry's row for itself (the fan-out's echo) is not one of its peers.
2. A peer whose policy hash moved without a governance change (a release changed a shipped default) drifted every
   cycle with no way back but lift-quarantine: accept-baseline makes its CURRENT policy the baseline, refused unless it
   is the exact hash the admin reviewed, with a reason, on the ledger.
3. The quarantine preview walked the Docker targets only (one operator of the three peers Sandbox Alpha's poller
   reads); it now walks the poller's population.
4. An unreadable event store read as an empty ledger, which the console explained as "the poller has not run".
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agentvault_registry import models
from agentvault_registry.routers import consul_admin as ca


class _Result:
    def __init__(self, rows=None, one=None):
        self._rows, self._one = rows, one

    def scalars(self):
        return self

    def all(self):
        return list(self._rows or [])

    def scalar_one_or_none(self):
        return self._one


class _QueueDB:
    """Answers each execute() with the next queued result; counts commits."""
    def __init__(self, *answers):
        self._answers = list(answers)
        self.commits = 0

    async def execute(self, _stmt):
        return self._answers.pop(0)

    async def commit(self):
        self.commits += 1


def _card(name, td, tier, ccy):
    return {"identity": {"registry_name": name, "display_name": name, "trust_domain": td, "tier": tier},
            "fees": {"settlement_currency": ccy}}


def _peer(i, name, *, status="ACTIVE", td=None, ptype="frame", card=None, verified=True, url=None):
    p = models.PeerRegistry(name=name, base_url=url or f"https://{name.lower().replace(' ', '-')}.example:8443",
                            status=status, peer_type=ptype, trust_domain=td)
    p.id = i
    p.cached_registry_card = card
    p.card_signature_verified = verified
    return p


def _baseline(peer_id, h="a" * 64, *, status="federated", version=0, source="factory_default", failures=0):
    return models.FederatedRegistryCompliance(
        peer_registry_id=peer_id, federation_status=status, policy_hash=h, policy_version=version,
        policy_json={"baseline_source": "compliance_poller:first_sight", "policy_hash": h, "policy_version": version,
                     "policy_source": source},
        admitted_by="compliance_poller:first_sight", last_poll_at=datetime.now(timezone.utc),
        consecutive_poll_failures=failures, drift_events_count=0)


@pytest.fixture
def as_sandbox_alpha(monkeypatch):
    """This registry is a frame named Sandbox Alpha on sandbox-a.example, settling in SBXA."""
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "Sandbox Alpha")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.example")
    monkeypatch.setenv("FRAME_CURRENCY", "SBXA")
    monkeypatch.delenv("MINTING_AUTHORITY", raising=False)

    class _State:
        compliance_enforcement_mode = "dry_run"

    async def _state(_db):
        return _State()

    async def _no_targets(_db):
        return []

    async def _no_reach(_db, include_ok=True):
        return None

    monkeypatch.setattr(ca, "_get_singleton_state", _state)
    monkeypatch.setattr(ca, "list_diag_targets", _no_targets)
    from agentvault_registry.services import federation_reachability
    monkeypatch.setattr(federation_reachability, "build_report", _no_reach)


# ── 1. the overview's peer identity ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_overview_rows_carry_identity_home_frame_and_currency(monkeypatch, as_sandbox_alpha):
    peers = [
        _peer(1, "sbxalphaop", td="sandbox-a.example", ptype="cloud_operator",
              card=_card("sbxalphaop", "sandbox-a.example", "cloud-operator", "SBXA")),
        _peer(2, "Sandbox Beta", td="sandbox-b.example", card=_card("Sandbox Beta", "sandbox-b.example", "sovereign-mainframe", "SBXB")),
        _peer(3, "sbxbetaop", ptype="discovered", card=_card("sbxbetaop", "sandbox-b.example", "cloud-operator", "SBXB")),
        _peer(4, "far-op", ptype="discovered"),
        _peer(5, "nobody", ptype="discovered"),
        _peer(6, "Salut", status="INACTIVE", td="salut.example", card=_card("Salut", "salut.example", "sovereign-mainframe", "SLT")),
        _peer(7, "Sandbox Alpha", ptype="discovered", td="sandbox-a.example"),   # this registry's own echo
    ]
    compliances = [_baseline(1), _baseline(2), _baseline(6)]

    async def _topology():
        return {"far-op": "far.example"}
    monkeypatch.setattr(ca, "_topology_trust_domains", _topology)

    ov = await ca.get_overview(db=_QueueDB(_Result(peers), _Result(compliances)))
    by = {r.peer_name: r for r in ov.peers}
    assert set(by) == {"sbxalphaop", "Sandbox Beta", "sbxbetaop", "far-op", "nobody", "Salut"}, "the self echo is not a peer"
    assert ov.peers_total == 6 and ov.peers_with_compliance == 3

    a = by["sbxalphaop"]
    assert (a.trust_domain, a.resolution_state, a.resolution_source) == ("sandbox-a.example", "resolved", "column")
    assert (a.home_frame, a.currency_zone) == ("Sandbox Alpha", "SBXA"), "an operator of this frame belongs to this frame"
    b = by["Sandbox Beta"]
    assert (b.trust_domain, b.resolution_source, b.home_frame, b.currency_zone) == ("sandbox-b.example", "column", "Sandbox Beta", "SBXB")
    c = by["sbxbetaop"]
    assert (c.trust_domain, c.resolution_source, c.home_frame, c.currency_zone) == ("sandbox-b.example", "card", "Sandbox Beta", "SBXB")
    f = by["far-op"]
    assert (f.trust_domain, f.resolution_state, f.resolution_source, f.home_frame) == ("far.example", "resolved", "bfs", None)
    n = by["nobody"]
    assert (n.trust_domain, n.resolution_state, n.resolution_source, n.home_frame) == (None, "unidentified", "unresolved", None)
    s = by["Salut"]
    assert (s.trust_domain, s.resolution_source, s.home_frame) == ("salut.example", "column", None), \
        "an inactive frame is no frame of this federation: its peers are unmapped, never placed in a live frame"


@pytest.mark.asyncio
async def test_the_topology_cache_is_read_only_when_the_column_and_card_leave_a_row_unresolved(monkeypatch, as_sandbox_alpha):
    peers = [_peer(2, "Sandbox Beta", td="sandbox-b.example", card=_card("Sandbox Beta", "sandbox-b.example", "sovereign-mainframe", "SBXB"))]

    async def _boom():
        raise AssertionError("the topology cache was read although every row resolved by its column")
    monkeypatch.setattr(ca, "_topology_trust_domains", _boom)
    ov = await ca.get_overview(db=_QueueDB(_Result(peers), _Result([_baseline(2)])))
    assert [r.resolution_source for r in ov.peers] == ["column"]


def test_an_unverified_card_does_not_name_a_frame():
    """The manifest's rule: a display name comes from a VERIFIED card only (it is not covered by the signature)."""
    peers = [_peer(2, "sbx-b-row", td="sandbox-b.example", card=_card("Fancy Name", "sandbox-b.example", "sovereign-mainframe", "SBXB"),
                   verified=False)]
    frames = ca._frames_by_trust_domain(peers)
    assert frames["sandbox-b.example"]["name"] == "sbx-b-row"


@pytest.mark.asyncio
async def test_a_self_echo_that_holds_a_compliance_record_stays_visible(monkeypatch, as_sandbox_alpha):
    peers = [_peer(7, "Sandbox Alpha", ptype="discovered", td="sandbox-a.example")]

    async def _topology():
        return {}
    monkeypatch.setattr(ca, "_topology_trust_domains", _topology)
    ov = await ca.get_overview(db=_QueueDB(_Result(peers), _Result([_baseline(7)])))
    assert [r.peer_name for r in ov.peers] == ["Sandbox Alpha"], "nothing the poller wrote disappears unseen"


# ── 2. accept-baseline ───────────────────────────────────────────────────────

def test_accept_baseline_on_moves_the_baseline_and_keeps_the_drift_history():
    c = _baseline(1, "a" * 64, version=72, source=None)
    c.drift_events_count = 9
    seen = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    c.last_hash_mismatch_at = seen
    now = datetime(2026, 10, 3, 13, 0, tzinfo=timezone.utc)
    payload = ca.accept_baseline_on(c, {"policy_hash": "b" * 64, "policy_version": 72, "policy_source": "amended"},
                                    admin_email="admin@test.sandbox", reason="release default change", now=now)
    assert (c.policy_hash, c.policy_version, c.admitted_by, c.admitted_at) == ("b" * 64, 72, "admin@test.sandbox", now)
    assert c.policy_json["baseline_source"] == "admin:accepted" and c.policy_json["previous_hash"] == "a" * 64
    assert c.policy_json["reason"] == "release default change" and c.policy_json["policy_source"] == "amended"
    assert (c.drift_events_count, c.last_hash_mismatch_at) == (9, seen), "accepting a policy does not unsay its drift"
    assert payload["previous_hash"] == "a" * 64 and payload["new_hash"] == "b" * 64 and payload["accepted_by"] == "admin@test.sandbox"


@pytest.mark.parametrize("body", [
    {"expected_hash": "B" * 64, "reason": "valid reason"},       # upper case is not the hash the endpoint publishes
    {"expected_hash": "b" * 63, "reason": "valid reason"},
    {"expected_hash": "b" * 64, "reason": "why"},                # a reason of four characters says nothing
])
def test_accept_baseline_request_refuses_a_malformed_hash_or_a_reason_that_says_nothing(body):
    with pytest.raises(ValidationError):
        ca.AcceptBaselineRequest(**body)


class _Admin:
    email = "admin@test.sandbox"


class _Poller:
    def __init__(self, answer=None, error=None, raises=None):
        self.answer, self.error, self.raises, self.calls = answer, error, raises, 0

    async def _fetch_policy_compliance(self, _peer):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.answer, self.error


class _Emitter:
    """Records what reached the emitter under `received` (tests/test_doubles_assert_receipt.py reads receipt by name)."""
    def __init__(self, fail=False):
        self.fail, self.received = fail, []

    async def emit(self, **kw):
        if self.fail:
            raise RuntimeError("store down")
        self.received.append(kw)


def _wire(monkeypatch, poller, emitter=None):
    monkeypatch.setattr(ca, "get_compliance_poller", lambda: poller)
    em = emitter or _Emitter()
    monkeypatch.setattr(ca, "get_event_emitter", lambda: em)
    return em


async def _accept(db, h="b" * 64, reason="release default change"):
    return await ca.accept_peer_baseline(1, ca.AcceptBaselineRequest(expected_hash=h, reason=reason), db=db, admin=_Admin())


@pytest.mark.asyncio
async def test_accept_baseline_stores_the_reviewed_hash_and_records_it_on_the_ledger(monkeypatch):
    em = _wire(monkeypatch, _Poller({"policy_hash": "b" * 64, "policy_version": 0, "policy_source": "factory_default"}))
    c = _baseline(1, "a" * 64)
    db = _QueueDB(_Result(one=_peer(1, "Sandbox Beta")), _Result(one=c))
    out = await _accept(db)
    assert out["status"] == "accepted" and out["ledger_recorded"] is True and db.commits == 1
    assert c.policy_hash == "b" * 64
    assert [e["event_type"] for e in em.received] == ["ComplianceBaselineAccepted"]
    assert em.received[0]["data"]["previous_hash"] == "a" * 64 and em.received[0]["data"]["peer_name"] == "Sandbox Beta"


@pytest.mark.asyncio
async def test_accept_baseline_says_when_the_ledger_did_not_record_it(monkeypatch):
    _wire(monkeypatch, _Poller({"policy_hash": "b" * 64}), _Emitter(fail=True))
    db = _QueueDB(_Result(one=_peer(1, "Sandbox Beta")), _Result(one=_baseline(1)))
    out = await _accept(db)
    assert out["status"] == "accepted" and out["ledger_recorded"] is False


@pytest.mark.asyncio
async def test_accept_baseline_refuses_a_hash_the_admin_did_not_review(monkeypatch):
    em = _wire(monkeypatch, _Poller({"policy_hash": "c" * 64}))
    c = _baseline(1, "a" * 64)
    db = _QueueDB(_Result(one=_peer(1, "Sandbox Beta")), _Result(one=c))
    with pytest.raises(HTTPException) as e:
        await _accept(db)
    assert e.value.status_code == 409 and "you reviewed" in e.value.detail
    assert c.policy_hash == "a" * 64 and db.commits == 0 and em.received == []


@pytest.mark.asyncio
async def test_accept_baseline_of_the_stored_hash_changes_nothing(monkeypatch):
    em = _wire(monkeypatch, _Poller({"policy_hash": "a" * 64}))
    db = _QueueDB(_Result(one=_peer(1, "Sandbox Beta")), _Result(one=_baseline(1, "a" * 64)))
    out = await _accept(db, h="a" * 64)
    assert out["status"] == "unchanged" and db.commits == 0 and em.received == []


@pytest.mark.asyncio
@pytest.mark.parametrize("peer,compliance,poller,code,words", [
    (None, None, _Poller(), 404, "not found"),
    (_peer(1, "x"), None, _Poller(), 404, "no baseline yet"),
    (_peer(1, "x"), _baseline(1, status="quarantined"), _Poller(), 409, "lift-quarantine"),
    (_peer(1, "x"), _baseline(1, status="blacklisted"), _Poller(), 409, "blacklisted"),
    (_peer(1, "x", status="INACTIVE"), _baseline(1), _Poller(), 409, "nothing to accept"),
    (_peer(1, "x"), _baseline(1), _Poller(None, "HTTP 401"), 502, "HTTP 401"),
])
async def test_accept_baseline_refusals(monkeypatch, peer, compliance, poller, code, words):
    _wire(monkeypatch, poller)
    answers = [_Result(one=peer)] + ([_Result(one=compliance)] if peer is not None else [])
    with pytest.raises(HTTPException) as e:
        await _accept(_QueueDB(*answers))
    assert e.value.status_code == code and words in e.value.detail


@pytest.mark.asyncio
async def test_accept_baseline_reports_a_transport_failure_as_the_peer_not_answering(monkeypatch):
    import httpx
    _wire(monkeypatch, _Poller(raises=httpx.ConnectError("refused")))
    with pytest.raises(HTTPException) as e:
        await _accept(_QueueDB(_Result(one=_peer(1, "x")), _Result(one=_baseline(1))))
    assert e.value.status_code == 502 and "ConnectError" in e.value.detail


def test_accept_baseline_needs_the_enforcement_flag():
    """The same flag as lift-quarantine and the quarantine routes: moving a baseline decides what the poller enforces."""
    import inspect
    src = inspect.getsource(ca.accept_peer_baseline)
    assert 'require_admin_flag("admin_enforcement")' in src


# ── 3. the preview's population ──────────────────────────────────────────────

class _PeerPoller:
    def __init__(self, by_name):
        self.by_name = by_name

    async def _fetch_policy_compliance(self, peer):
        a = self.by_name[peer.name]
        if isinstance(a, Exception):
            raise a
        return a


@pytest.mark.asyncio
async def test_the_preview_walks_the_pollers_population(monkeypatch, as_sandbox_alpha):
    peers = [
        _peer(1, "sbxalphaop", td="sandbox-a.example", ptype="cloud_operator"),
        _peer(2, "Sandbox Beta", td="sandbox-b.example"),
        _peer(3, "sbxbetaop", td="sandbox-b.example", ptype="discovered"),
        _peer(4, "fresh", td="sandbox-b.example", ptype="discovered"),
        _peer(5, "streak", td="sandbox-b.example", ptype="discovered"),
        _peer(6, "graced", td="sandbox-b.example", ptype="discovered"),
        _peer(8, "Salut", status="INACTIVE", td="salut.example"),
        _peer(9, "Sandbox Alpha", ptype="discovered", td="sandbox-a.example"),
    ]
    graced = _baseline(6, "a" * 64)
    graced.quarantine_grace_expires = datetime.now(timezone.utc) + timedelta(hours=10)
    compliances = [_baseline(1, "a" * 64), _baseline(2, "a" * 64), _baseline(3, "a" * 64), _baseline(5, "a" * 64, failures=2),
                   graced, _baseline(8)]
    import httpx
    monkeypatch.setattr(ca, "get_compliance_poller", lambda: _PeerPoller({
        "sbxalphaop": ({"policy_hash": "b" * 64}, None),
        "Sandbox Beta": ({"policy_hash": "a" * 64}, None),
        "sbxbetaop": (None, "HTTP 401"),
        "streak": httpx.ConnectError("refused"),
        "graced": ({"policy_hash": "b" * 64}, None),
    }))
    out = await ca.preview_quarantine(db=_QueueDB(_Result(peers), _Result(compliances)))
    by = {r.peer_name: r for r in out.peers}
    assert set(by) == {"sbxalphaop", "Sandbox Beta", "sbxbetaop", "fresh", "streak", "graced"}, \
        "every ACTIVE peer the poller reads; never an inactive one, never this registry's echo"
    assert by["sbxalphaop"].would_action == "quarantine_high_48h" and by["sbxalphaop"].hash_match is False
    assert by["Sandbox Beta"].would_action == "none" and by["Sandbox Beta"].hash_match is True
    assert by["sbxbetaop"].would_action == "none" and by["sbxbetaop"].reachable is False and "1 of 3" in by["sbxbetaop"].detail
    assert by["fresh"].would_action == "skipped" and "first answer" in by["fresh"].detail
    assert by["streak"].would_action == "quarantine_high_48h" and "failure 3 in a row" in by["streak"].detail
    assert by["graced"].would_action == "none" and "grace period" in by["graced"].detail
    assert (out.total_peers, out.would_quarantine_count, out.would_noop_count, out.skipped_count) == (6, 2, 3, 1)


# ── 4. an unreadable store is not an empty ledger ────────────────────────────

class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


def _fake_client(answer_for):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            a = answer_for((params or {}).get("event_type"))
            if isinstance(a, Exception):
                raise a
            return a
    return _Client


@pytest.mark.asyncio
async def test_events_name_the_types_the_store_did_not_answer(monkeypatch):
    def answer(t):
        if t == "ComplianceDryRunDrift":
            return _Resp(200, [{"event_type": t, "timestamp": "2026-10-03T11:25:10Z"}])
        if t == "RegistryBlacklisted":
            return _Resp(503)
        return _Resp(200, [])
    monkeypatch.setattr(ca.httpx, "AsyncClient", _fake_client(answer))
    out = await ca.list_events(limit=50, event_types=None)
    assert out["total"] == 1 and out["unreadable"] == [{"event_type": "RegistryBlacklisted", "reason": "HTTP 503"}]
    assert "error" not in out, "one type unreadable is named, not a store outage"


@pytest.mark.asyncio
async def test_events_say_once_when_the_store_cannot_be_read_at_all(monkeypatch):
    import httpx
    monkeypatch.setattr(ca.httpx, "AsyncClient", _fake_client(lambda t: httpx.ConnectError("no route")))
    out = await ca.list_events(limit=50, event_types=None)
    assert out["total"] == 0 and len(out["unreadable"]) == 8
    assert out["error"] == "the event store could not be read (ConnectError: no route)"


@pytest.mark.asyncio
async def test_the_default_event_types_include_the_baseline_events(monkeypatch):
    asked = []

    def answer(t):
        asked.append(t)
        return _Resp(200, [])
    monkeypatch.setattr(ca.httpx, "AsyncClient", _fake_client(answer))
    await ca.list_events(limit=50, event_types=None)
    assert {"ComplianceBaselineRecorded", "ComplianceBaselineAccepted", "ComplianceDryRunDrift"} <= set(asked)


@pytest.mark.asyncio
async def test_drifts_report_a_refusal_rather_than_an_empty_list(monkeypatch):
    monkeypatch.setattr(ca.httpx, "AsyncClient", _fake_client(lambda t: _Resp(403)))
    out = await ca.list_drifts(limit=50, drift_type=None)
    assert out["drifts"] == [] and out["error"] == "the event store answered HTTP 403"


# ── 5. the poller's drift says what the peer reports about both documents ─────

@pytest.mark.asyncio
async def test_a_dry_run_drift_carries_both_versions_and_sources(monkeypatch):
    from agentvault_registry.background_tasks import compliance_poller as cp
    from agentvault_registry.core.base_network_params import DriftSeverity
    em = _Emitter()
    monkeypatch.setattr(cp, "get_event_emitter", lambda: em)

    class _Check:
        stored_hash, fetched_hash = "a" * 64, "b" * 64
    poller = cp.CompliancePoller() if hasattr(cp, "CompliancePoller") else cp.get_compliance_poller()
    await poller._emit_dry_run_drift(peer=_peer(2, "Sandbox Beta"), compliance=_baseline(2, version=0, source="factory_default"),
                                     check=_Check(), severity=DriftSeverity.HIGH, grace_hours=48, mode="dry_run",
                                     trigger="hash_mismatch",
                                     fetched={"policy_hash": "b" * 64, "policy_version": 0, "policy_source": "factory_default"})
    d = em.received[0]["data"]
    assert (d["stored_version"], d["fetched_version"], d["stored_source"], d["fetched_source"]) == (0, 0, "factory_default", "factory_default")


# ── 6. the detail and the drift list say what the console needs to judge a drift ──

@pytest.mark.asyncio
async def test_the_detail_reports_both_versions_and_skips_the_diff_for_an_accepted_baseline(monkeypatch):
    p = _peer(2, "Sandbox Beta", td="sandbox-b.example")
    c = _baseline(2, "a" * 64, version=0, source="factory_default")
    c.policy_json = {"baseline_source": "admin:accepted", "policy_hash": "a" * 64, "policy_version": 0,
                     "policy_source": "factory_default"}
    calls = []

    async def _fetch(url, timeout_seconds=10.0, full=False):
        calls.append(full)
        return "b" * 64, {"policy_hash": "b" * 64, "policy_version": 0, "policy_source": "factory_default",
                          "policy_json": {"x": 1}}, None

    async def _no_targets(_db):
        return []
    monkeypatch.setattr(ca, "list_diag_targets", _no_targets)
    monkeypatch.setattr(ca, "_fetch_live_policy", _fetch)

    class _DB:
        def __init__(self):
            self.n = 0

        async def execute(self, _stmt):
            self.n += 1
            return _Result([p]) if self.n == 1 else _Result(one=c)
    d = await ca.get_peer_detail_by_operator("sandbox-beta", db=_DB())
    assert calls == [True]
    assert (d.admitted_policy_version, d.admitted_policy_source) == (0, "factory_default")
    assert (d.live_policy_version, d.live_policy_source, d.hash_match) == (0, "factory_default", False)
    assert d.diff is None, "an accepted baseline is an observation record, never a document to diff"


@pytest.mark.asyncio
async def test_drifts_name_their_peer_and_whether_it_is_still_one(monkeypatch):
    rows = [{"event_type": "FederationStateDriftDetected", "data": {"drift_type": "peer_url_misconfigured", "peer_id": 18}},
            {"event_type": "FederationStateDriftDetected", "data": {"drift_type": "frame_bundle_stale", "peer_id": "2"}},
            {"event_type": "FederationStateDriftDetected", "data": {"drift_type": "frame_bundle_stale", "peer_id": 99}},
            {"event_type": "FederationStateDriftDetected", "data": {"drift_type": "operator_network_topology"}}]
    monkeypatch.setattr(ca.httpx, "AsyncClient", _fake_client(lambda t: _Resp(200, rows)))
    db = _QueueDB(_Result([_peer(18, "F6 Revoke", status="INACTIVE"), _peer(2, "Sandbox Beta")]))
    out = await ca.list_drifts(limit=50, drift_type=None, db=db)
    peers = [d.get("peer") for d in out["drifts"]]
    assert peers == [{"id": 18, "name": "F6 Revoke", "status": "INACTIVE"}, {"id": 2, "name": "Sandbox Beta", "status": "ACTIVE"},
                     {"id": 99, "name": None, "status": "DELETED"}, None]


@pytest.mark.asyncio
async def test_preview_rows_carry_the_trust_domain_the_console_groups_by(monkeypatch, as_sandbox_alpha):
    peers = [_peer(3, "sbxbetaop", ptype="discovered", card=_card("sbxbetaop", "sandbox-b.example", "cloud-operator", "SBXB"))]
    monkeypatch.setattr(ca, "get_compliance_poller", lambda: _PeerPoller({"sbxbetaop": ({"policy_hash": "a" * 64}, None)}))
    out = await ca.preview_quarantine(db=_QueueDB(_Result(peers), _Result([_baseline(3, "a" * 64)])))
    assert [r.trust_domain for r in out.peers] == ["sandbox-b.example"]


# ── 7. the trust-bundle matrix: the federation's frames, from this registry's own bundle ──

def _ca_pem(td):
    """A self-signed CA whose URI SAN names `td`, the way a SPIRE root does."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SPIFFE")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=7))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(f"spiffe://{td}")]), critical=False)
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_ca_sets_are_placed_by_the_trust_domain_each_ca_names():
    a1, a2, b1 = _ca_pem("sandbox-a.example"), _ca_pem("sandbox-a.example"), _ca_pem("sandbox-b.example")
    sets = ca._ca_sets_by_trust_domain(a1 + a2 + b1 + "garbage")
    assert {k: len(v) for k, v in sets.items()} == {"sandbox-a.example": 2, "sandbox-b.example": 1}


@pytest.mark.asyncio
async def test_the_matrix_columns_are_the_federations_frames_and_a_missing_ca_is_said(monkeypatch, tmp_path, as_sandbox_alpha):
    (tmp_path / "bundle.0.pem").write_text(_ca_pem("sandbox-a.example"))      # Sandbox Beta's CA is missing here
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(ca, "_gateways_unreadable_reason", lambda: "no socket in a test")
    peers = [_peer(2, "Sandbox Beta", td="sandbox-b.example", card=_card("Sandbox Beta", "sandbox-b.example", "sovereign-mainframe", "SBXB")),
             _peer(8, "Salut", status="INACTIVE", td="salut.example")]
    m = await ca.trust_bundle_matrix(db=_QueueDB(_Result(peers)))
    assert [(f.name, f.trust_domain, f.ca_count) for f in m.frames] == [
        ("Sandbox Alpha", "sandbox-a.example", 1), ("Sandbox Beta", "sandbox-b.example", 0)]
    assert m.frame_ca_error == "this registry's own trust bundle holds no CA of: sandbox-b.example"
    assert m.gateways_readable is False and m.gateways_unreadable_reason == "no socket in a test" and m.ops == []
    assert "agentvault.com" not in m.model_dump_json() and "frame-c" not in m.model_dump_json()


@pytest.mark.asyncio
async def test_the_matrix_reads_each_gateway_against_every_frame(monkeypatch, tmp_path, as_sandbox_alpha):
    a, b = _ca_pem("sandbox-a.example"), _ca_pem("sandbox-b.example")
    (tmp_path / "bundle.0.pem").write_text(a + b)
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    monkeypatch.setattr(ca, "_gateways_unreadable_reason", lambda: None)
    peers = [_peer(1, "sbxalphaop", td="sandbox-a.example", ptype="cloud_operator"),
             _peer(2, "Sandbox Beta", td="sandbox-b.example", card=_card("Sandbox Beta", "sandbox-b.example", "sovereign-mainframe", "SBXB"))]

    async def _targets(_db):
        return [{"operator_id": "op-sbxalphaop", "display_name": "sbxalphaop", "role": "operator",
                 "containers": {"nginx_federation": "cloud-op-op-sbxalphaop-nginx-federation"}},
                {"operator_id": "op-broken", "display_name": "broken", "role": "operator",
                 "containers": {"nginx_federation": "cloud-op-op-broken-nginx-federation"}}]

    class _Probe:
        async def exec_in(self, name, cmd, timeout=10):
            return (0, a) if "sbxalphaop" in name else (1, "No such file")
    monkeypatch.setattr(ca, "list_diag_targets", _targets)
    monkeypatch.setattr(ca, "get_probe", lambda: _Probe())
    m = await ca.trust_bundle_matrix(db=_QueueDB(_Result(peers)))
    by = {r.op: r for r in m.ops}
    assert by["sbxalphaop"].trusts == {"sandbox-a.example": True, "sandbox-b.example": False}
    assert by["sbxalphaop"].missing == ["sandbox-b.example"] and by["sbxalphaop"].complete is False
    assert by["sbxalphaop"].frame == "Sandbox Alpha"
    assert by["broken"].error.startswith("could not read /certs/bundle.0.pem (rc=1)")
    assert (m.total, m.complete, m.drift, m.errors, m.frame_ca_error) == (2, 0, 1, 1, None)
