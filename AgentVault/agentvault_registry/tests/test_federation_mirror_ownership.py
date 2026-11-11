"""A mirrored card could land on a LOCAL account, which then owned it.

session-lead measured this on production (counts only): EU held 47 mirrors on 8 real accounts and 5 on shadows;
ASIA 66 on 7 real accounts and 35 on shadows. EU developer 9 — an outside account — held hochiminh's canary sender
and receiver mirrors.

THE INSERT PATH asked for a local Developer whose id EQUALS the remote developer_id, and built the per-peer shadow
(`fed:<peer>:dev-<n>`, is_federation_shadow) only when that id happened to be free. The comment directly beneath it
reads "SECURITY: Never force the remote developer_id (causes collisions). Never reuse a local developer by name
(would grant cross-registry ownership)" — and the lookup three lines above did exactly the first thing, which grants
exactly the second. Remote and local developer ids are independent sequences, so a collision is ordinary, not rare.

THE WRITES then check nothing but `developer_id`: PATCH /{card_id}/listing, PUT /{card_id} and DELETE /{card_id}.
So the local account whose id collided could edit, unlist or delete another registry's agent card.

ONE PREDICATE, because there were already three. `home_extensions.is_native` read only `source_registry`, while
agent_cards.py asked `not (fm.get("source_registry") or fm.get("first_synced_from"))` inline, twice. A rule with
three copies and two meanings is the drift; the narrow copy is the one that was wrong.
"""
from __future__ import annotations

import inspect

import pytest

from agentvault_registry.crud import crud_peer_registry as cpr
from agentvault_registry.routers import agent_cards as ac
from agentvault_registry.services import home_extensions as he

MIRROR_SR = {"name": "x", "federation_metadata": {"source_registry": "spiffe://asia.theprotocol.cloud/registry/asia"}}
MIRROR_FS = {"name": "x", "federation_metadata": {"first_synced_from": "spiffe://asia.theprotocol.cloud/registry/asia"}}
NATIVE = {"name": "x", "federation_metadata": {"protocol_version": "1.0"}}
NATIVE_BARE = {"name": "x"}


# ── one predicate, both keys ───────────────────────────────────────────────────────────────────────────────────────
def test_a_card_naming_only_first_synced_from_is_not_native():
    """RED before: is_native read only source_registry, so this mirror passed every check that used it."""
    assert he.is_native(MIRROR_FS) is False


def test_a_card_naming_source_registry_is_not_native():
    assert he.is_native(MIRROR_SR) is False


def test_a_native_card_stays_native():
    assert he.is_native(NATIVE) is True
    assert he.is_native(NATIVE_BARE) is True


def test_a_non_dict_is_not_native():
    assert he.is_native(None) is False and he.is_native("x") is False


def test_agent_cards_asks_the_shared_predicate_rather_than_its_own_copy():
    """The two inline copies in agent_cards.py are what let the narrow one survive unnoticed.

    Scoped to the two functions that HELD them, not the module: mirror_write_refusal reads the same two keys to NAME
    the home registry in its refusal, which is a different question, and a module-wide string count flagged my own
    fix. A gate that cannot tell a copy of the rule from a use of the data is the §29e shape in a grep's clothing."""
    for fn_name in ("_build_currency_resolver", "list_agent_cards"):
        fn = getattr(ac, fn_name, None)
        if fn is None:
            continue
        src = inspect.getsource(fn)
        assert 'fm.get("source_registry") or fm.get("first_synced_from")' not in src, \
            f"{fn_name} still carries its own copy of the native rule"
    # and the shared one IS imported here
    assert "_he_is_native" in inspect.getsource(ac)


# ── the mirror refusal ─────────────────────────────────────────────────────────────────────────────────────────────
def test_the_refusal_names_a_mirror_and_passes_a_native():
    assert ac.mirror_write_refusal(MIRROR_SR) is not None
    assert ac.mirror_write_refusal(MIRROR_FS) is not None
    assert ac.mirror_write_refusal(NATIVE) is None
    assert ac.mirror_write_refusal(NATIVE_BARE) is None


def test_the_refusal_says_whose_card_it_is():
    """A refusal a human can act on: it names the registry the card came from."""
    reason = ac.mirror_write_refusal(MIRROR_SR)
    assert "asia" in reason.lower()


def test_each_owner_scoped_write_asks_for_the_refusal():
    """Structural, because a route needs a database. The three writes checked developer_id and nothing else."""
    for fn_name in ("set_agent_card_listing", "update_agent_card", "delete_agent_card"):
        fn = getattr(ac, fn_name)
        src = inspect.getsource(fn)
        assert "mirror_write_refusal" in src, f"{fn_name} still writes a mirror on an id match alone"


# ── the insert path ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_insert_never_looks_a_developer_up_by_the_remote_id():
    """The whole defect in one assertion. Comments are stripped: the fix's own comment names the old lookup."""
    # the insert lives in upsert_agent_cards_from_peer — read from the module, because my first version of this test
    # named a function that does not exist and failed for that reason instead of the one it was written for
    src = inspect.getsource(cpr.upsert_agent_cards_from_peer)
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "models.Developer.id == developer_id" not in code, "the remote id can still claim a local account"
    assert "is_federation_shadow=True" in code, "the per-peer shadow is gone"


# ── a third site, found by the grep lead asked for ─────────────────────────────────────────────────────────────────
def test_the_agent_log_owner_check_requires_a_native_card():
    """`_developer_owns_agent` granted log read/delete/write to whoever held A CARD with that agent_did — and a
    mirror carries a server-set agent_did. Its own docstring records closing this shape for card CONTENT
    (§MCPTEST30); it came back through a column the server does set. Structural, because the check is two queries."""
    from agentvault_registry.routers import agent_logs
    src = inspect.getsource(agent_logs._developer_owns_agent)
    assert "is_native" in src, "a mirror on a local account still passes the card leg"
    assert "card_data" in src, "it still selects only the id, so it cannot tell a mirror from a native card"


# ── session-lead's review: the refusal must not state a fact it cannot read ────────────────────────────────────────
# It told None, a string, an int and [] that they were "a federated mirror held from another registry". The write is
# refused either way — that part was right, a card whose ownership cannot be established is not one to write — but
# the SENTENCE was a claim about data the code could not read, which is the §29e shape: a verdict papering over which
# of two states it is in.
@pytest.mark.parametrize("unreadable", [None, "a string", 42, [], ()])
def test_an_unreadable_card_is_refused_but_not_called_a_mirror(unreadable):
    reason = ac.mirror_write_refusal(unreadable)
    assert reason is not None, "ownership cannot be established, so the write is still refused"
    assert "mirror" not in reason.lower(), f"it claims to know what it could not read: {reason!r}"
    assert "cannot be read" in reason.lower()


def test_a_real_mirror_still_gets_the_mirror_sentence_naming_its_home():
    reason = ac.mirror_write_refusal(MIRROR_SR)
    assert "mirror" in reason.lower() and "asia" in reason.lower()
