"""§ECHO (2026-09-28): a frame took its OWN operator's stale copy of a card back over the fresh one from the card's home.

Measured on the sandbox pair with scripts/mcpsweep/enfprop_watch.py (both databases, every 3 s): the home reinstated a
suspended agent at 11:04:49.947, sbx-beta's mirror read the lift at 11:05:09.459, and at 11:05:21.334 sbx-beta's sync
with sbxbetaop (its own operator, which had pulled the SUSPENDED copy from sbx-beta at 11:04:56.257) wrote it back. The
relay's copy was older by the clock; it got in through `has_new_fields` (it carried a `location` the home's copy does
not), replaced the whole card, and the re-stamp then out-dated the home's own clock, so the home could never correct it.
Two federation-suite rows went red (the suspension's lift and the relist), and the state stayed wrong.

Two halves, both held here:
  1. THE DIRECT COPY WINS: a registry ignores a RELAYED copy of a card whose origin it pulls from directly (the
     registry-card fan-out has had this rule since §FANOUTFIX; agent cards had none). A relay stays the source for an
     origin we do not pull from, or cannot reach right now.
  2. A copy admitted ONLY for a new field brings that field and nothing else: the enforcement extension, the
     listing, the name and the active flag stay ours.
"""
from __future__ import annotations

import asyncio
import copy
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

ENF = "https://theprotocol.cloud/extensions/v1/enforcement"
DID = "did:theprotocol:sandbox-a.theprotocol.cloud:915dd121-04ef-4c15-a6fa-227869d91e94"


def _fm(origin="Sandbox Alpha"):
    return {"origin_registry_name": origin, "source_registry": "spiffe://sandbox-a.theprotocol.cloud/service/registry",
            "first_synced_from": "spiffe://sandbox-a.theprotocol.cloud/service/registry"}


def _card(*, suspended=False, location=False, origin="Sandbox Alpha", extra_ext=None):
    cd = {"name": "fedsuite-mech-enf-079e8ac4", "description": "probe", "url": "https://agent.example.test/a2a",
          "version": "1.0", "capabilities": {}, "skills": [], "federation_metadata": _fm(origin)}
    exts = list(extra_ext or [])
    if suspended:
        exts.append({"uri": ENF, "required": False, "description": "Enforcement state stamped by the agent's home registry",
                     "params": {"version": 1, "status": "suspended", "since": "2026-09-28", "registry": "Sandbox Alpha"}})
    if exts:
        cd["extensions"] = exts
    if location:
        cd["location"] = {"name": "Sandbox Alpha", "lat": 50.1, "lng": 8.7}
    return cd


def _ext_status(cd):
    for e in (cd or {}).get("extensions") or []:
        if isinstance(e, dict) and e.get("uri") == ENF:
            return (e.get("params") or {}).get("status")
    return None


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def fetchall(self):
        return []


class _Session:
    """Just enough session for the existing-card branch of upsert_agent_cards_from_peer."""

    def __init__(self, existing):
        self.existing = existing
        self.commits = 0

    async def execute(self, stmt, params=None):
        return _Result(self.existing)

    async def commit(self):
        self.commits += 1

    async def get(self, model, key):
        return None


def _existing(cd, *, written_at, is_active=True, name="fedsuite-mech-enf-079e8ac4"):
    return SimpleNamespace(card_data=copy.deepcopy(cd), name=name, description="probe", is_active=is_active,
                           updated_at=written_at, developer_id=None, agent_did=DID)


def _incoming(cd, *, updated_at, is_active=True, name="fedsuite-mech-enf-079e8ac4"):
    return {"id": str(uuid.uuid4()), "name": name, "description": "probe", "is_active": is_active,
            "updated_at": updated_at.isoformat(), "card_data": copy.deepcopy(cd)}


@pytest.fixture(autouse=True)
def _plain_ingest(monkeypatch):
    # the listing column and the fail-closed schema gate are decided above the branch under test
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", "off")
    monkeypatch.delenv("FEDERATION_INGEST_FAIL_CLOSED", raising=False)


def _upsert(existing, incoming, **kw):
    from agentvault_registry.crud import crud_peer_registry as crud
    db = _Session(existing)
    res = asyncio.run(crud.upsert_agent_cards_from_peer(
        db=db, peer_svid="spiffe://sandbox-b.theprotocol.cloud/operator/sbxbetaop/registry",
        agent_card=incoming, peer_trust_domain="sandbox-b.theprotocol.cloud", **kw))
    existing.commits = db.commits
    return res, existing


# ── half 2: a copy admitted only for a new field brings that field and nothing else ─────────────────────────────

W = datetime(2026, 9, 28, 11, 5, 9, 459000)          # sbx-beta wrote the lift (naive UTC, as the column holds it)
RELAY_CLOCK = datetime(2026, 9, 28, 11, 4, 56, 257000)  # the operator's copy, pulled while the agent was suspended


def test_the_measured_echo_keeps_the_lift():
    # exactly the measured copy: older by the clock, admitted only for its `location`. The change detection ignores
    # location by design (_norm_card: "genuine did/location changes are rare and ride the periodic full-reconcile"),
    # so once the stale state is refused there is nothing left to write: a no-op, and the lift stays.
    existing = _existing(_card(suspended=False, location=False), written_at=W)
    res, row = _upsert(existing, _incoming(_card(suspended=True, location=True), updated_at=RELAY_CLOCK))
    assert _ext_status(row.card_data) is None, "the stale relay put the home's lifted suspension back"
    assert res == "unchanged" and row.commits == 0


FLARE = {"tier": "founder", "variant": "classic"}


def test_a_new_field_still_arrives_without_the_older_state_around_it():
    existing = _existing(_card(suspended=False), written_at=W)
    stale = _card(suspended=True)
    stale["flare"] = FLARE
    res, row = _upsert(existing, _incoming(stale, updated_at=RELAY_CLOCK))
    assert res == "updated" and row.card_data.get("flare") == FLARE, "the new field is what let the copy in"
    assert _ext_status(row.card_data) is None, "…and only the new field: the stale suspension stays out"


def test_a_stale_copy_admitted_for_a_new_field_does_not_revive_a_deactivated_mirror():
    existing = _existing(_card(), written_at=W, is_active=False)
    stale = _card()
    stale["flare"] = FLARE
    _res, row = _upsert(existing, _incoming(stale, updated_at=RELAY_CLOCK, is_active=True))
    assert row.is_active is False and row.card_data.get("flare") == FLARE


def test_a_stale_copy_admitted_for_a_new_field_does_not_rename_the_mirror():
    existing = _existing(_card(), written_at=W, name="the home's current name")
    _res, row = _upsert(existing, _incoming(_card(location=True), updated_at=RELAY_CLOCK, name="an older name"))
    assert row.name == "the home's current name"


def test_control_a_newer_copy_still_replaces_the_card():
    existing = _existing(_card(suspended=False), written_at=W)
    res, row = _upsert(existing, _incoming(_card(suspended=True), updated_at=W + timedelta(seconds=30)))
    assert res == "updated" and _ext_status(row.card_data) == "suspended"


def test_control_an_older_copy_without_a_new_field_is_still_skipped():
    existing = _existing(_card(suspended=False), written_at=W)
    res, row = _upsert(existing, _incoming(_card(suspended=True), updated_at=RELAY_CLOCK))
    assert res == "skipped" and _ext_status(row.card_data) is None


# ── the origin's own copy is the truth, whatever the clocks say (a stuck mirror heals) ──────────────────────────

STUCK_AT = datetime(2026, 9, 28, 11, 5, 21, 334000)    # the echo's local re-stamp on sbx-beta
HOME_CLOCK = datetime(2026, 9, 28, 11, 4, 49, 947000)  # the home's card after the reinstatement (older than the stamp)


def test_the_origins_own_copy_replaces_a_stuck_mirror_whatever_the_clocks_say():
    existing = _existing(_card(suspended=True, location=True), written_at=STUCK_AT)
    res, row = _upsert(existing, _incoming(_card(suspended=False), updated_at=HOME_CLOCK), from_origin=True)
    assert res == "updated" and _ext_status(row.card_data) is None, "the home's lift must heal the stuck mirror"


def test_control_the_same_old_copy_from_a_relay_is_still_refused_by_the_clock():
    existing = _existing(_card(suspended=True, location=True), written_at=STUCK_AT)
    res, row = _upsert(existing, _incoming(_card(suspended=False), updated_at=HOME_CLOCK), from_origin=False)
    assert res == "skipped" and _ext_status(row.card_data) == "suspended"


def test_an_identical_copy_from_the_origin_is_still_a_no_op():
    cd = _card(suspended=False)
    existing = _existing(cd, written_at=STUCK_AT)
    res, row = _upsert(existing, _incoming(cd, updated_at=HOME_CLOCK), from_origin=True)
    assert res == "unchanged" and row.commits == 0, "a quiet mesh must stay quiet: no write, no re-stamp"


BOND = "https://theprotocol.cloud/extensions/v1/reputation-bond"


def _bonded(as_of, transactions=12, trust_population=30):
    cd = _card()
    cd["extensions"] = [{"uri": BOND, "required": False, "params": {
        "version": 1, "status": "locked", "amount": "250", "currency": "SBXA", "locked_at": "2026-09-28T12:29:25+00:00",
        "maturity": {"version": 2, "as_of": as_of, "transactions": transactions, "eigentrust": 0.01,
                     "rated_peers": 1, "trust_percentile": 50, "trust_population": trust_population, "thresholds": {},
                     "matured": False}}}]
    return cd


def test_the_bond_snapshots_export_clock_is_not_a_change():
    # MEASURED on V0483 (sbx-beta, 12:30-12:31Z): two stored copies of one bonded card 30 s apart differed ONLY in
    # maturity.as_of (stamped datetime.now() at every EXPORT) and the sync's own timestamp, so under the origin rule
    # every direct sync rewrote every bonded card in its page. §SYNCLOOP's rule: a derived clock is not content.
    existing = _existing(_bonded("2026-09-28T12:30:39.498115+00:00"), written_at=STUCK_AT)
    res, row = _upsert(existing, _incoming(_bonded("2026-09-28T12:31:09.450867+00:00"), updated_at=HOME_CLOCK),
                       from_origin=True)
    assert res == "unchanged" and row.commits == 0


def test_the_home_frames_population_count_is_not_a_change():
    # §POPCOUNT, MEASURED on V0484 (sbx-beta, 14:11Z): the daily digest walk rewrote ~4,445 bonded mirrors in one minute.
    # A burst-written mirror stored trust_population 1418 and the home exported 1427 eighteen minutes later: the HOME
    # FRAME's count of ranked agents, stamped on every bonded card, moves with every agent the frame ranks.
    existing = _existing(_bonded("2026-09-28T14:11:12+00:00", trust_population=1418), written_at=STUCK_AT)
    res, row = _upsert(existing, _incoming(_bonded("2026-09-28T14:29:08+00:00", trust_population=1427),
                                           updated_at=HOME_CLOCK), from_origin=True)
    assert res == "unchanged" and row.commits == 0


def test_control_a_real_change_inside_the_snapshot_still_writes():
    existing = _existing(_bonded("2026-09-28T12:30:39+00:00", transactions=12), written_at=STUCK_AT)
    res, row = _upsert(existing, _incoming(_bonded("2026-09-28T12:31:09+00:00", transactions=13), updated_at=HOME_CLOCK),
                       from_origin=True)
    assert res == "updated" and row.commits == 1


# ── half 1: the direct copy wins ─────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 28, 11, 6, 0, tzinfo=timezone.utc)


def _peer(name, *, peer_type="frame", td="sandbox-a.theprotocol.cloud", synced_ago=30, failures=0, status="ACTIVE"):
    return SimpleNamespace(name=name, peer_type=peer_type, trust_domain=td, status=status,
                           last_synced_at=None if synced_ago is None else NOW - timedelta(seconds=synced_ago),
                           consecutive_sync_failures=failures, base_url=f"https://{name}.example.test")


# sbx-beta's rows as measured 2026-09-28: the other frame, its own operator, and the other frame's operator
SBX_BETA_PEERS = [
    _peer("Sandbox Alpha"),
    _peer("sbxbetaop", peer_type="cloud_operator", td="sandbox-b.theprotocol.cloud"),
    _peer("sbxalphaop", peer_type="discovered", td="sandbox-a.theprotocol.cloud"),
]


def test_the_direct_sources_are_the_peers_we_pull_from_and_reached_recently():
    from agentvault_registry.background_tasks.federation_sync import direct_source_names
    assert direct_source_names(SBX_BETA_PEERS, now=NOW) == {"sandbox alpha", "sbxbetaop"}


@pytest.mark.parametrize("peer", [
    _peer("Sandbox Alpha", synced_ago=None),       # never synced
    _peer("Sandbox Alpha", synced_ago=3600),       # not reached for an hour: relays are the source again
    _peer("Sandbox Alpha", failures=2),            # failing now
    _peer("Sandbox Alpha", status="INACTIVE"),
])
def test_a_source_we_cannot_rely_on_right_now_is_not_direct(peer):
    from agentvault_registry.background_tasks.federation_sync import direct_source_names
    assert "sandbox alpha" not in direct_source_names([peer, SBX_BETA_PEERS[1]], now=NOW)


def test_the_other_frames_operator_is_never_a_direct_source():
    # §BATCH8 item 4: the cycle never dials it (its cards arrive through its frame), so a fresh row is not enough
    from agentvault_registry.background_tasks.federation_sync import direct_source_names
    assert "sbxalphaop" not in direct_source_names(SBX_BETA_PEERS, now=NOW)


@pytest.mark.parametrize("origin,presenter,expected", [
    ("Sandbox Alpha", "sbxbetaop", "Sandbox Alpha"),   # the measured echo: our operator relays the other frame's card
    ("SANDBOX ALPHA", "sbxbetaop", "SANDBOX ALPHA"),   # names are compared without case ("ASIA" beside "asia")
    ("Sandbox Alpha", "Sandbox Alpha", None),          # the direct copy itself
    ("sbxalphaop", "Sandbox Alpha", None),             # an origin we do not pull from: the relay is its source
    (None, "sbxbetaop", None),                         # no origin named: behave as before
])
def test_which_copies_are_relays_of_a_direct_origin(origin, presenter, expected):
    from agentvault_registry.background_tasks.federation_sync import relayed_copy_of_direct_origin
    cd = _card(origin=origin) if origin else {k: v for k, v in _card().items() if k != "federation_metadata"}
    assert relayed_copy_of_direct_origin({"card_data": cd}, presenter, {"sandbox alpha", "sbxbetaop"}) == expected


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _BatchSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def begin_nested(self):
        return _Nested()

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def ingest(monkeypatch):
    """The real batch and push paths over sbx-beta's measured peer rows; the upsert replaced by a recorder of
    (origin, from_origin) for every copy that reached it."""
    from agentvault_registry.background_tasks import federation_sync as fs
    from agentvault_registry.services import frame_policy, peer_trust_policy

    seen = []

    async def _record(db, peer_svid, agent_card, peer_trust_domain=None, from_origin=False):
        seen.append((agent_card["card_data"]["federation_metadata"].get("origin_registry_name"), from_origin))
        return "updated"

    async def _peers(db, skip=0, limit=1000):
        return SBX_BETA_PEERS

    async def _no_policy(db):
        return {}

    monkeypatch.setattr(fs, "AsyncSessionLocal", lambda: _BatchSession())
    monkeypatch.setattr(fs.crud_peer_registry, "upsert_agent_cards_from_peer", _record)
    monkeypatch.setattr(fs.crud_peer_registry, "list_active_peer_registries_all", _peers)
    monkeypatch.setattr(frame_policy, "load", _no_policy)
    monkeypatch.setattr(peer_trust_policy, "evaluate", lambda peer, pol: SimpleNamespace(is_actionable=False))
    monkeypatch.setattr(fs, "_utcnow", lambda: NOW, raising=False)
    return fs, seen


def _batch(*origins):
    return [{"id": str(uuid.uuid4()), "card_data": _card(origin=o)} for o in origins]


def test_a_batch_from_our_operator_passes_its_own_cards_and_drops_the_other_frames(ingest):
    fs, seen = ingest
    worker = fs.FederationSyncWorker()
    assert asyncio.run(worker._process_peer_cards(SBX_BETA_PEERS[1], _batch("Sandbox Alpha", "sbxbetaop", "sbxalphaop"))) is True
    # the batch is sorted by card id before the ingest, so compare as a multiset
    assert sorted(seen) == [("sbxalphaop", False), ("sbxbetaop", True)], \
        f"the relayed copy of a direct origin reached the ingest, or the origin's own copy was not marked: {seen}"


def test_control_a_batch_from_the_origin_itself_passes_everything(ingest):
    fs, seen = ingest
    worker = fs.FederationSyncWorker()
    assert asyncio.run(worker._process_peer_cards(SBX_BETA_PEERS[0], _batch("Sandbox Alpha", "sbxalphaop"))) is True
    assert sorted(seen) == [("Sandbox Alpha", True), ("sbxalphaop", False)]


class _PushDb:
    async def execute(self, stmt, params=None):
        return _Result(None)     # the legacy name lookup finds no peer row

    async def commit(self):
        pass


def _push_request(spiffe_id, *origins):
    from agentvault_registry.routers.federation_sync import FederationSyncRequest
    now = datetime(2026, 9, 28, 11, 6, 0)
    cards = [{"id": str(uuid.uuid4()), "developer_id": 1, "developer_name": "d", "developer_verified": True,
              "card_data": _card(origin=o), "name": "n", "description": "d", "is_active": True,
              "created_at": now, "updated_at": now, "source_registry": spiffe_id} for o in origins]
    return FederationSyncRequest(source_registry=spiffe_id, agent_cards=cards, sync_timestamp=now)


def test_a_push_from_our_operator_is_held_to_the_same_rule(ingest):
    # 05's review: POST /federation/sync-request calls the upsert directly, so it needs the rule of its own
    from agentvault_registry.routers.federation_sync import receive_sync_request
    fs, seen = ingest
    op = "spiffe://sandbox-b.theprotocol.cloud/operator/sbxbetaop/registry"   # resolves to the sbxbetaop row
    asyncio.run(receive_sync_request(_push_request(op, "Sandbox Alpha", "sbxbetaop", "sbxalphaop"), _PushDb(), op))
    assert sorted(seen) == [("sbxalphaop", False), ("sbxbetaop", True)], seen


def test_a_push_from_a_presenter_we_cannot_name_ingests_no_copy_of_a_direct_origin(ingest):
    # a frame's post-F5 identity (/service/registry) names no peer row: every copy of a direct origin is a relay
    from agentvault_registry.routers.federation_sync import receive_sync_request
    fs, seen = ingest
    frame = "spiffe://sandbox-a.theprotocol.cloud/service/registry"
    asyncio.run(receive_sync_request(_push_request(frame, "Sandbox Alpha", "sbxbetaop", "sbxalphaop"), _PushDb(), frame))
    assert seen == [("sbxalphaop", False)], seen


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    # asyncio.run() leaves the thread with no current loop; put one back for the next file
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
