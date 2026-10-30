"""The cross-TEG partner rule on real money (2026-10-17): a leg with a peer that is not a current partner of this TEG
moves nothing, and a partner's legs move what they always moved.

Integration test (real Postgres; the real cross-TEG router, coordinator, protocol and coordination store) against a
THROWAWAY database (DATABASE_URL), never a production schema. Redis is an in-memory stand-in and so is the far TEG of a
transfer this TEG starts. The caller is the identity this frame's terminator verified, under TEG_MTLS_REQUIRED=true (the
production posture), injected where the router reads it. Runner style (python tests/test_cross_teg_partner_legs.py) for
the CI job's "<passed>/<total> passed".

RED control: against dad136e9's TEG source (its router and partner cache) five of the seven scenarios fail (a
never-added, a removed or a sibling operator's commit credits the recipient; the transfer toward a TEG that is no
partner locks, commits and pays it and adds it as a partner; a transfer toward a partner rewrites the partner's stored
address with the payload's); the two controls (a partner operator, an operator TEG's parent frame) pass on both.
"""
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, "/app")

os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")
OWN = "eu.test"
os.environ["SPIRE_TRUST_DOMAIN"] = OWN
os.environ["TRUSTED_SPIFFE_DOMAINS"] = OWN
os.environ["TEG_MTLS_REQUIRED"] = "true"
os.environ["CROSS_TEG_PEER_INBOUND_LIMIT_MODE"] = "off"
for _name in ("CROSS_TEG_PARTNER_RULE_MODE", "CROSS_TEG_LOCAL_LEG_SOURCES", "REDIS_URL"):
    os.environ.pop(_name, None)

from fastapi import FastAPI                                                       # noqa: E402
from fastapi.testclient import TestClient                                         # noqa: E402
from sqlalchemy import create_engine                                              # noqa: E402
from sqlalchemy.orm import sessionmaker                                           # noqa: E402

from src.teg_core_service.database.models import (                                # noqa: E402
    Base, AgentTEGProfile, TEGTransaction, CrossTEGTransfer,
)
from src.teg_core_service.database import get_db                                  # noqa: E402
from src.teg_core_service.core.db_url import sync_engine_url                      # noqa: E402
import src.teg_core_service.redis_client as rc                                    # noqa: E402
import src.teg_core_service.core.cross_teg.partner_cache as pc                    # noqa: E402
import src.teg_core_service.api.cross_teg_router as r                             # noqa: E402
from src.teg_core_service.api import auth_enhanced as ae                          # noqa: E402
from src.teg_core_service.core.cross_teg import (                                 # noqa: E402
    CrossTEGTransferProtocol, DistributedTransactionCoordinator,
)

FRAME_TEG = f"spiffe://{OWN}/service/teg-layer"
FRAME_REGISTRY = f"spiffe://{OWN}/service/eu-registry"
AMSTERDAM = f"spiffe://{OWN}/operator/amsterdam/svid-writer"
LISBON = f"spiffe://{OWN}/operator/lisbon/svid-writer"
SENDER = "did:theprotocol:partner-legs-sender"
RECIPIENT = "did:theprotocol:partner-legs-recipient"
FEECOLL = "teg:system:fee_collector"
HASH = "teg:partners"

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
engine = create_engine(sync_engine_url(_raw))
SessionLocal = sessionmaker(bind=engine)


class FakeRedis:
    """The commands the partner store uses, on dicts (an empty hash is dropped, as Redis drops it)."""

    def __init__(self):
        self.h, self.s = {}, {}

    async def ping(self):
        return True

    async def hset(self, name, key=None, value=None, mapping=None):
        d = self.h.setdefault(name, {})
        items = dict(mapping or {})
        if key is not None:
            items[key] = value
        n = sum(1 for k in items if k not in d)
        d.update(items)
        return n

    async def hget(self, name, key):
        return self.h.get(name, {}).get(key)

    async def hgetall(self, name):
        return dict(self.h.get(name, {}))

    async def hdel(self, name, *keys):
        d = self.h.get(name, {})
        n = 0
        for k in keys:
            if k in d:
                del d[k]
                n += 1
        if name in self.h and not self.h[name]:
            del self.h[name]
        return n

    async def publish(self, channel, message):
        return 0

    def pipeline(self, transaction=True):
        return _Pipe(self)

    async def sismember(self, key, member):
        return member in self.s.get(key, set())


class _Pipe:
    def __init__(self, redis):
        self.redis, self.ops = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def hdel(self, *args):
        self.ops.append(("hdel", args, {}))
        return self

    def hset(self, *args, **kwargs):
        self.ops.append(("hset", args, kwargs))
        return self

    async def execute(self):
        return [await getattr(self.redis, name)(*args, **kwargs) for name, args, kwargs in self.ops]


class FarTEG:
    """The far TEG of a transfer this TEG starts: it prepares and commits whatever it is sent."""

    def __init__(self):
        self.calls = []

    async def prepare_transfer(self, transfer_id, request_data, auth_token):
        self.calls.append(("prepare", transfer_id))
        return {"status": "prepared", "transfer_id": transfer_id}

    async def commit_transfer(self, transfer_id, auth_token):
        self.calls.append(("commit", transfer_id))
        return {"status": "committed", "transfer_id": transfer_id}

    async def abort_transfer(self, transfer_id, reason, auth_token):
        self.calls.append(("abort", transfer_id))
        return {"status": "aborted", "transfer_id": transfer_id}


class Factory:
    def __init__(self):
        self.far = FarTEG()
        self.dials = []

    def get_client(self, teg_id, url):
        self.dials.append((teg_id, url))
        return self.far

    async def remove_client(self, teg_id):
        return True


REDIS = FakeRedis()


async def _get_redis():
    return REDIS


rc.get_redis = _get_redis
pc.get_redis = _get_redis

CALLER = {"id": None}
r._extract_spiffe_from_header = lambda req: CALLER["id"]

FACTORY = Factory()
PROTOCOL = CrossTEGTransferProtocol(teg_id=r.settings.teg_id, db_session_factory=get_db)
COORD = DistributedTransactionCoordinator(
    teg_id=r.settings.teg_id, protocol=PROTOCOL,
    teg_client_factory=lambda teg_id, url_hint=None: FACTORY.get_client(teg_id, r.resolve_partner_url(teg_id, url_hint=url_hint)),
)   # main.py's wiring
r.init_cross_teg_router(PROTOCOL, COORD, FACTORY)

APP = FastAPI()
APP.include_router(r.router)
APP.dependency_overrides[ae.verify_admin_key] = lambda: True
APP.dependency_overrides[r.get_current_agent] = lambda: SENDER


def reset(own_identity=FRAME_TEG):
    os.environ["TEG_OWN_SPIFFE_ID"] = own_identity
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        for aid, bal in ((SENDER, "100"), (RECIPIENT, "0"), (FEECOLL, "0")):
            db.add(AgentTEGProfile(agent_id=aid, token_balance=Decimal(bal), audited_balance=Decimal(bal),
                                   locked_balance=Decimal("0"), wrapped_balance=Decimal("0"), reputation_score=0,
                                   account_status="active"))
        db.commit()
    finally:
        db.close()
    REDIS.h.clear()
    r._runtime_partners[:] = []
    FACTORY.dials.clear()
    FACTORY.far.calls.clear()
    COORD.active_coordinations.clear()


def balance(agent):
    db = SessionLocal()
    try:
        p = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == agent).one()
        return p.token_balance, p.locked_balance
    finally:
        db.close()


def rows(transfer_id):
    db = SessionLocal()
    try:
        coordination = db.query(CrossTEGTransfer).filter(CrossTEGTransfer.transfer_id == transfer_id).all()
        return [(str(getattr(c.status, "value", c.status)), c.role) for c in coordination], \
            db.query(TEGTransaction).count()
    finally:
        db.close()


def add(client, teg_id, url):
    res = client.post("/api/v1/cross-teg/config/add-partner", json={"teg_id": teg_id, "url": url})
    assert res.status_code == 200, res.text


def prepare(client, tid, amount="10"):
    return client.post(f"/api/v1/cross-teg/prepare/{tid}", json={
        "source_teg_id": "teg-amsterdam", "source_registry_id": "registry-amsterdam", "source_agent_id": SENDER,
        "target_agent_id": RECIPIENT, "amount": amount, "currency": "ECU", "correlation_id": tid,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat()})


def commit(client, tid):
    return client.post(f"/api/v1/cross-teg/commit/{tid}")


def transfer(client, tid, target, url):
    now = datetime.now(timezone.utc)
    return client.post("/api/v1/cross-teg/transfer", json={
        "transfer_id": tid, "correlation_id": tid, "source_teg_id": r.settings.teg_id,
        "source_registry_id": "registry-eu", "source_agent_id": SENDER, "target_teg_id": target,
        "target_registry_id": "registry-x", "target_teg_url": url, "target_agent_id": "did:theprotocol:far",
        "amount": "10", "authorization_token": "t", "expires_at": (now + timedelta(seconds=120)).isoformat(),
        "idempotency_key": tid})


def refused(res):
    assert res.status_code == 403 and "cross_teg_partner_refused" in res.text, (res.status_code, res.text[:200])


# ------------------------------------------------------------------------------------------------ the scenarios
def test_a_partner_operator_credits_as_before():
    """Control: the registry added the operator (teg-layer-<name>); its prepare and commit credit the recipient."""
    reset()
    with TestClient(APP) as c:
        add(c, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
        CALLER["id"] = AMSTERDAM
        assert prepare(c, "pl-a").status_code == 200
        assert commit(c, "pl-a").status_code == 200
    assert balance(RECIPIENT) == (Decimal("9.95"), Decimal("0")), balance(RECIPIENT)
    assert balance(FEECOLL)[0] == Decimal("0.05")


def test_an_operator_that_is_no_partner_credits_nothing():
    reset()
    with TestClient(APP) as c:
        CALLER["id"] = AMSTERDAM
        refused(prepare(c, "pl-b"))
        refused(commit(c, "pl-b"))
    assert balance(RECIPIENT) == (Decimal("0"), Decimal("0")), "a never-added operator credited the recipient"
    assert rows("pl-b") == ([], 0), rows("pl-b")


def test_the_reactor_removal_stops_a_prepared_transfer():
    """Prepared while a partner; its registry's reactor then removes it as teg-amsterdam: the commit credits nothing."""
    reset()
    with TestClient(APP) as c:
        add(c, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
        CALLER["id"] = AMSTERDAM
        assert prepare(c, "pl-c").status_code == 200
        res = c.post("/api/v1/cross-teg/config/remove-partner", json={"teg_id": "teg-amsterdam"})
        assert res.status_code == 200 and res.json()["status"] == "removed", res.text
        refused(commit(c, "pl-c"))
    assert balance(RECIPIENT) == (Decimal("0"), Decimal("0")), "the removed operator's commit credited the recipient"
    assert rows("pl-c") == ([("prepared", "target")], 0), rows("pl-c")


def test_a_transfer_toward_no_partner_locks_nothing_and_adds_nothing():
    reset()
    with TestClient(APP) as c:
        CALLER["id"] = FRAME_REGISTRY
        res = transfer(c, "pl-d", "teg-layer-elsewhere", "https://elsewhere.test:8443")
        assert res.status_code == 400 and "cross_teg_partner_refused" in res.text, (res.status_code, res.text[:200])
    assert balance(SENDER) == (Decimal("100"), Decimal("0")), balance(SENDER)
    assert rows("pl-d") == ([], 0), rows("pl-d")
    assert FACTORY.far.calls == [] and FACTORY.dials == [], "the far TEG was dialed"
    assert r._runtime_partners == [] and HASH not in REDIS.h, "the payload's address added a partner"


def test_a_transfer_toward_a_partner_pays_as_before():
    """Control: the registry adds the target, then starts the transfer; the address it names is the dial's."""
    reset()
    with TestClient(APP) as c:
        add(c, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
        FACTORY.dials.clear()                   # add-partner pre-registers a client at the stored address
        CALLER["id"] = FRAME_REGISTRY
        res = transfer(c, "pl-e", "teg-layer-amsterdam", "https://amsterdam-now.op.test:8443")
        assert res.status_code == 200 and res.json()["success"], (res.status_code, res.text[:200])
    assert balance(SENDER) == (Decimal("90"), Decimal("0")), balance(SENDER)
    assert FACTORY.far.calls == [("prepare", "pl-e"), ("commit", "pl-e")]
    assert {u for _, u in FACTORY.dials} == {"https://amsterdam-now.op.test:8443"}, FACTORY.dials
    assert [(p["teg_id"], p["url"]) for p in r._runtime_partners] == [
        ("teg-layer-amsterdam", "https://amsterdam.op.test:8443")], "a dial changed the partner list"


def test_an_operator_tegs_parent_frame_credits_as_before():
    """Control: on an operator TEG the parent frame is no peer (it issued the operator's own identity)."""
    reset(own_identity=AMSTERDAM)
    with TestClient(APP) as c:
        CALLER["id"] = FRAME_TEG
        assert prepare(c, "pl-f").status_code == 200
        assert commit(c, "pl-f").status_code == 200
    assert balance(RECIPIENT)[0] == Decimal("9.95"), balance(RECIPIENT)


def test_a_sibling_operator_that_is_no_partner_credits_nothing():
    reset(own_identity=AMSTERDAM)
    with TestClient(APP) as c:
        CALLER["id"] = LISBON
        refused(prepare(c, "pl-g"))
        refused(commit(c, "pl-g"))
    assert balance(RECIPIENT) == (Decimal("0"), Decimal("0")), "a sibling operator credited the recipient"
    assert rows("pl-g") == ([], 0), rows("pl-g")


TESTS = [
    test_a_partner_operator_credits_as_before,
    test_an_operator_that_is_no_partner_credits_nothing,
    test_the_reactor_removal_stops_a_prepared_transfer,
    test_a_transfer_toward_no_partner_locks_nothing_and_adds_nothing,
    test_a_transfer_toward_a_partner_pays_as_before,
    test_an_operator_tegs_parent_frame_credits_as_before,
    test_a_sibling_operator_that_is_no_partner_credits_nothing,
]


def _alarm(signum, frame):
    raise TimeoutError("scenario exceeded 60 s (a hang is the failure)")


if __name__ == "__main__":
    failed = 0
    signal.signal(signal.SIGALRM, _alarm)
    for t in TESTS:
        signal.alarm(60)
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
        finally:
            signal.alarm(0)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
