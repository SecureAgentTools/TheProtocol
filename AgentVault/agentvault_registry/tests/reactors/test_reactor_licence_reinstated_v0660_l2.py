"""V0660 (l2): the licence-reinstated reactor takes the partner address from the peer ROW, and acts on our own
events only.

MEASURED ON daa8f8995 (the V0660 cut), which is why this exists:
  * `FederationLicenseReinstated` is on the replicator's broadcast allowlist
    (event-store `services/cross_frame_replicator.CROSS_FRAME_BROADCAST_TYPES`), so every event a peer emits of this
    type reaches this frame — on the WS bridge, and through `reactor_base._poll_once`, which fetches the reactor's own
    event type from `/api/v1/events/foreign` as well as `/events/export` every 30 s by default;
  * the reactor read `url` and `teg_id` straight out of that payload and passed them to
    `reactor_helpers.add_partner_on_teg`, which writes them into this frame's TEG partner config as that partner's
    dial address. So a federated peer could name both the partner and the address this frame's TEG dials for it;
  * and the `url` key was read from a payload NEITHER of our own emitters sets (the licence route and the
    operator-application route; both were read), so the only thing it ever wrote was the helper's invented
    `https://<teg_id>.placeholder:8443`.

THE RULE HERE, the one its sibling `reactor_frame_federation_established` already follows: the payload names the
licence and nothing else. This database says which operator that licence belongs to, and the peer ROW says the
address — `register_peer_partner_on_teg`, the helper the reactivation, the quarantine lift and the provisioning use.
A peer frame's reinstatement is not acted on at all: re-adding a partner is a grant of trust this frame makes for
itself.

RED on daa8f8995: the reactor calls add_partner_on_teg with the payload's url, so the foreign test writes a partner,
the address test writes the payload's address, and the no-row test writes the placeholder.
"""
from __future__ import annotations

import ast
import pathlib
import types
from typing import Any, Dict, List, Optional

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_federation_license_reinstated as r_lic
from agentvault_registry.background_tasks import reactor_helpers

SRC = pathlib.Path(r_lic.__file__).resolve()

ROW_ADDRESS = "https://op-lab.op.theprotocol.cloud:27543"
PAYLOAD_ADDRESS = "http://169.254.169.254/latest/meta-data"      # what a peer would like us to dial
LICENCE_ID = "6f2a1d84-0000-4000-8000-00000000l2ab".replace("l2", "12")


@pytest.fixture(autouse=True)
def reset_leader_keys():
    reactor_base._registered_leader_keys.clear()
    r_lic._instance = None
    yield
    reactor_base._registered_leader_keys.clear()
    r_lic._instance = None


class _DB:
    """A session holding one licence row; records what was read."""

    def __init__(self, licences: Optional[Dict[str, Any]] = None):
        self.licences = licences or {}
        self.reads: List[tuple] = []

    async def get(self, model, key):
        self.reads.append((model.__name__, key))
        return self.licences.get(str(key))


class _Session:
    def __init__(self, db):
        self.db = db
        self.opened = 0

    def __call__(self):
        self.opened += 1
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def world(monkeypatch):
    """Licence <LICENCE_ID> belongs to operator 'op-lab', whose ACTIVE peer row carries ROW_ADDRESS.

    The helper chain is REAL from the reactor down to the TEG call: the peer resolver and the add-partner POST are
    the only doubles, so the address that reaches add-partner is the one the code actually chose.
    """
    from agentvault_registry import database

    partners: List[Dict[str, Any]] = []
    resolved: Dict[str, Any] = {"value": (ROW_ADDRESS, "cache-key")}

    async def fake_resolve(peer_name, db):
        return resolved["value"]

    async def fake_post_teg_admin(*, path, body, source_label, op_name):
        partners.append({"path": path, **body})
        return {"status": "added", "total_partners": 2}

    db = _DB(licences={LICENCE_ID: types.SimpleNamespace(id=LICENCE_ID, operator_name="op-lab",
                                                         operator_did="did:theprotocol:op-lab")})
    session = _Session(db)
    monkeypatch.setattr(database, "AsyncSessionLocal", session)
    monkeypatch.setattr(reactor_helpers, "_post_teg_admin", fake_post_teg_admin)
    from agentvault_registry.routers import teg_integration
    monkeypatch.setattr(teg_integration, "_resolve_peer_target_for_cross_teg_fund", fake_resolve)
    return types.SimpleNamespace(partners=partners, db=db, session=session, resolved=resolved)


def _event(**over):
    """The payload our own emitters send (routers/federation_licenses.py, routers/operator_applications.py),
    plus the `url` a peer would add — no emitter of ours ever sets it."""
    base = {"license_id": LICENCE_ID, "operator_did": "did:theprotocol:op-lab", "operator_name": "op-lab",
            "teg_id": "teg-op-lab", "actor_developer_id": 2, "actor_email": "admin@example.test"}
    base.update(over)
    return base


# ── 1. a peer's reinstatement is not ours to act on ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_foreign_event_with_an_address_writes_no_partner(world):
    """The one that makes it a fix: the event arrives through the allowlist, carries an address, and is ignored."""
    await r_lic.FederationLicenseReinstatedReactor().handle_event(
        _event(_foreign_frame_id="asia", url=PAYLOAD_ADDRESS, teg_id="teg-of-the-peer"))
    assert world.partners == [], "a peer frame's reinstatement re-added a TEG partner"
    assert world.session.opened == 0, "a peer's event must not even open a session"


# ── 2. our own event writes the ROW's address, never the payload's ──────────────────────────────────

@pytest.mark.asyncio
async def test_our_own_event_writes_the_rows_address(world):
    await r_lic.FederationLicenseReinstatedReactor().handle_event(_event(url=PAYLOAD_ADDRESS))
    assert len(world.partners) == 1, f"the partner was not registered: {world.partners}"
    wrote = world.partners[0]
    assert wrote["url"] == ROW_ADDRESS, f"the address written is not the row's: {wrote['url']}"
    assert PAYLOAD_ADDRESS not in str(wrote), "the payload's address reached the TEG"
    assert wrote["teg_id"] == "teg-op-lab", wrote


@pytest.mark.asyncio
async def test_the_operator_is_the_licence_rows_own(world):
    """The payload names the licence; this database says whose it is. A payload naming another operator changes
    nothing about which partner is trusted."""
    await r_lic.FederationLicenseReinstatedReactor().handle_event(
        _event(operator_name="someone-else", teg_id="teg-someone-else"))
    assert len(world.partners) == 1 and world.partners[0]["teg_id"] == "teg-op-lab", world.partners


# ── 3. no row, no write ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_peer_row_writes_nothing(world):
    world.resolved["value"] = None            # no ACTIVE peer row with an address for this operator
    await r_lic.FederationLicenseReinstatedReactor().handle_event(_event(url=PAYLOAD_ADDRESS))
    assert world.partners == [], "a partner was registered with no peer row to name its address"


@pytest.mark.asyncio
async def test_a_licence_this_database_does_not_hold_writes_nothing(world):
    """A cloud operator reads its parent frame's store, where the parent's own event is not marked foreign."""
    await r_lic.FederationLicenseReinstatedReactor().handle_event(_event(license_id="a-licence-of-the-parent"))
    assert world.partners == [], "another registry's licence event registered a partner here"


@pytest.mark.asyncio
async def test_a_payload_with_no_licence_writes_nothing(world):
    await r_lic.FederationLicenseReinstatedReactor().handle_event(_event(license_id=None))
    assert world.partners == [] and world.session.opened == 0


# ── 4. the controls: the helper and the sibling path are unchanged ──────────────────────────────────

@pytest.mark.asyncio
async def test_the_sibling_helper_still_writes_the_rows_address(world):
    """The control: `register_peer_partner_on_teg` is what the reactivation, the quarantine lift and the
    provisioning call. (l2) changes the reactor, not the helper, and this fails if the helper moved."""
    out = await reactor_helpers.register_peer_partner_on_teg(world.db, "op-lab", source_label="control")
    assert out == {"status": "added", "total_partners": 2}
    assert world.partners[-1]["url"] == ROW_ADDRESS
    assert world.partners[-1]["teg_id"] == "teg-op-lab"


def test_the_reactor_reads_no_address_from_the_payload():
    """The dead read is GONE rather than inert: `url` was never set by either of our own emitters, so the only
    address it ever carried was one a peer put there.

    ⚠ read as a SYNTAX TREE, not as text. The first version of this test grepped the source and failed on the
    module's own docstring, which names `add_partner_on_teg` to say what the reactor no longer does — a gate that
    finds its own documentation first, and the reason the rule is to run the real test rather than a grep window.
    """
    tree = ast.parse(SRC.read_text())
    called = {ast.unparse(n.func).split(".")[-1] for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "add_partner_on_teg" not in called, \
        "the reactor still calls add_partner_on_teg; the row-reading helper is the one path"
    assert "register_peer_partner_on_teg" in called, "the reactor no longer registers the peer at all"

    read_keys = {n.args[0].value for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(".get")
                 and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}
    assert "url" not in read_keys, "the reactor still reads an address out of the payload"
    assert "_foreign_frame_id" in read_keys, "the reactor does not ask whether the event is a peer's"
    assert "license_id" in read_keys, "the reactor no longer reads the one thing the payload may decide"
