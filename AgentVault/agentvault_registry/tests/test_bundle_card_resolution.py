"""A bundle recorded a STRANGER's agent name, and captured no card at all.

MEASURED on production 2026-11-07, from a Forge lineage seeded on EU and ASIA. `_fetch_agent_full` resolved an
agent's card by loading EVERY card of the developer (no `agent_did` filter, though the column exists) and matching
`card_data['did'] == agent_did` or `humanReadableId == agent_did`. A freshly-minted card carries NEITHER: there is no
`did` key in it at all, and `humanReadableId` is a slug ("api-theprotocol-cloud"). So the match failed and two
things happened at once:

  * `name` fell back to `card_row[0][0]` — the developer's FIRST card, under a query with no ORDER BY. The bundle for
    my agent "Forge Starter Seed" was recorded as "AGORA Deposit Gateway" on EU and "Canary eu 1 receiver" on ASIA.
  * `card_data` stayed None, so the bundle captured no card. The fork's restored copy was then written a 4-key card
    (did, flare, humanReadableId, name) — which a fail-closed peer QUARANTINES, exactly the stub shape §VENUEGW
    documented for the gateway in August. That is what set the FederationCardIngestRefused alert off on both frames.

WHY IT SURVIVED: a RESTORED card does carry `card_data['did']`, with `humanReadableId == did`, so it matches. The
only agents that bundled correctly were ones that came from a previous restore.

The fix resolves by the `agent_did` COLUMN and never substitutes a different agent's row: a missing card yields
(None, None) and the payload's own "Unnamed Agent" default, which is honest, instead of a stranger's name that reads
as fact wherever the bundle is opened.
"""
from __future__ import annotations

import inspect

from agentvault_registry.services.bundles import service as svc

DID = "did:theprotocol:eu.theprotocol.cloud:027d6da2-62c4-45bb-a4ea-4fdf9c27097b"
OTHER = "did:theprotocol:eu.theprotocol.cloud:8ea7b941-77b4-46e5-841b-a49761fb294e"

# rows are (name, description, card_data), as the query selects them
FRESH_MINT = ("Forge Starter Seed", "a seed", {"humanReadableId": "api-theprotocol-cloud", "name": "Forge Starter Seed"})
STRANGER = ("AGORA Deposit Gateway", "the gateway", {"did": OTHER, "humanReadableId": OTHER})
RESTORED = ("Forge Starter Seed", "a copy", {"did": DID, "humanReadableId": DID})


def test_a_fresh_mints_own_row_is_used_even_though_its_card_data_has_no_did():
    """The row IS this agent's (the query filtered on agent_did); its card_data simply carries no 'did' key."""
    name, cd = svc._pick_agent_card([FRESH_MINT], DID)
    assert name == "Forge Starter Seed"
    assert cd == FRESH_MINT[2], "the card was dropped: the restore then writes a 4-key stub a peer quarantines"


def test_a_strangers_row_is_never_substituted():
    """RED before the fix: name fell through to card_row[0][0] and the bundle wore this name."""
    name, cd = svc._pick_agent_card([STRANGER], DID)
    assert name is None and cd is None


def test_no_card_at_all_is_none_not_a_guess():
    assert svc._pick_agent_card([], DID) == (None, None)


def test_the_content_match_still_works_for_a_restored_card():
    name, cd = svc._pick_agent_card([RESTORED], DID)
    assert name == "Forge Starter Seed" and cd["did"] == DID


def test_the_agents_own_row_wins_over_any_other():
    """Order must not decide the answer — the lottery is the defect."""
    for rows in ([STRANGER, FRESH_MINT], [FRESH_MINT, STRANGER]):
        name, cd = svc._pick_agent_card(rows, DID)
        assert name == "Forge Starter Seed", f"order decided the name: {rows!r}"


def test_the_query_filters_by_the_agent_did_column():
    """Structural: the fallback could only ever fire because the query fetched other agents' rows.

    COMMENTS ARE STRIPPED FIRST. The first version of this test failed on the fix's own explanatory comment, which
    names the old `card_row[0][0]` call to say why it is gone — a source-reading gate finding its documentation and
    calling it the defect. The prose stays; the assertion reads code."""
    lines = [l for l in inspect.getsource(svc._fetch_agent_full).splitlines()
             if not l.lstrip().startswith("#")]
    src = "\n".join(lines)
    assert "FROM agent_cards" in src
    where = src[src.index("FROM agent_cards"):]
    assert "agent_did = :did" in where, "the query still loads every card of the developer"
    assert "card_row[0][0]" not in src, "the first-row fallback is still there"


# ── the other half: what leaves this registry ─────────────────────────────────────────────────────────────────────
# session-lead's review of the first attempt, measured in the V0657 image: supplying the five fields the peer's
# refusal NAMED still produced a card the peer refuses, for "must declare at least one endpoint via url (v0.3) or
# supportedInterfaces[] (v1.0)". His explanation is the lesson: pydantic runs the model-level endpoint rule only
# AFTER the field errors are gone, so five missing fields HID the sixth rule. I had read an error list as the whole
# contract, when a validator reports one layer at a time.
#
# So these cases validate with the REAL model the peer runs. A copied list of field names measures itself.
from agentvault import AgentCard as PeerModel   # noqa: E402 — the same model crud_peer_registry validates with

from agentvault_registry.routers.federation_sync import _export_refusal  # noqa: E402


def _accepted(cd) -> bool:
    try:
        PeerModel.model_validate(cd)
        return True
    except Exception:
        return False


# THE FIXTURE IS THE PRODUCT'S OWN, not mine. I tried three times to hand-build a card that passes and was told
# three different things: humanReadableId is required; "must declare at least one endpoint"; "must declare auth via
# authSchemes". Each round was one layer deeper, because pydantic reports field errors first and the model-level
# rules only once those clear. So the fixture is the registry's own stub builder, which is ALSO worth asserting:
# the cards this registry mints must be cards its peers accept.
def _good():
    from agentvault_registry.routers.onboarding import _build_stub_card_data
    return _build_stub_card_data("https://example.test", "Pending", "n")


def test_the_registrys_own_stub_card_is_one_its_peers_accept():
    """The control: without it, every refusal below could be the model refusing everything. It also pins something
    worth pinning — a card this registry mints at onboarding passes the peer's own model (12 keys, measured)."""
    assert _accepted(_good())


def test_a_restore_with_no_captured_card_is_still_refused_and_that_is_why_the_exporter_gates():
    """The honest statement of what _restored_card_data alone achieves. It fills the five fields, which is strictly
    better than the 3-key card, and it CANNOT supply an endpoint: a restored copy has no host, and inventing an
    address is a fact nobody can retract. So the copy is simply not exportable until its agent is deployed and the
    pull-sync gives it a real one."""
    cd = svc._restored_card_data(None, DID, "Forge Starter Seed")
    assert not _accepted(cd)
    assert _export_refusal(cd) is not None, "the exporter must not hand this to a peer"
    # it fails TWO model-level rules, not one: no endpoint and no auth declaration. Neither can be supplied without
    # inventing a fact about an agent nobody has deployed, which is why the honest answer is the export gate and the
    # pull-sync, not a richer default here.


def test_a_restore_that_captured_an_endpoint_is_accepted():
    """The case that matters once the capture is fixed: a bundle made after half one carries the real card."""
    cd = svc._restored_card_data(_good(), DID, "Forge Starter Seed")
    assert _accepted(cd), "a captured card with an endpoint must survive the restore"
    assert cd["did"] == DID and cd["name"] == "Forge Starter Seed"
    assert _export_refusal(cd) is None


def test_the_old_three_key_restore_is_refused_too():
    """The control: the shape before any of this. It must still be refused."""
    assert _export_refusal({"did": DID, "humanReadableId": DID, "name": "x"}) == "protocolVersion"


def test_the_exporter_names_the_first_failing_field_as_the_reason():
    assert _export_refusal(svc._restored_card_data(None, DID, "n")) == "(card)"   # a model-level rule, not a field
    assert _export_refusal({"name": "x"}) == "protocolVersion"
    assert _export_refusal("not a dict") == "card_data"


def test_the_exporter_passes_a_card_the_peer_accepts():
    assert _export_refusal(_good()) is None


def test_a_darksync_tombstone_body_is_refused_by_the_model_but_the_importer_never_asks():
    """NO FINDING — I checked before filing one, on session-lead's instruction, and the importer already handles it.

    A tombstone body is {extensions, did, federation_metadata} by design and the MODEL refuses it on protocolVersion,
    which is what this asserts. But §LISTPROP's handling sits ABOVE the fail-closed gate in the importer precisely
    so the model is never asked: "A TOMBSTONE IS NOT A CARD AND MUST NOT BE VALIDATED AS ONE", with the same
    incident recorded (measured 2026-09-09: EU exported tombstones to ASIA and ASIA quarantined every one). D6-816
    does the same for an erasure tombstone.

    My own error is worth keeping next to the assertion: I validated the body against the model in ISOLATION and
    concluded that peers quarantine tombstones. That comment names the trap from the other side — "only the live
    proof could see it: the unit tests do not run this gate" — and a unit test does not run the exemption either.
    The export gate stays scoped to the FULL-card path, which is still right: a tombstone is not a card."""
    from agentvault_registry.services.listing_propagation import export_state, tombstone_card_data
    body = tombstone_card_data(DID, export_state({}, None, relayed=False), None)
    assert _export_refusal(body) is not None


# ── the regression session-lead caught in the export gate ──────────────────────────────────────────────────────────
# §QUARANTINEDENY (2026-09-29) exists because of a measured incident: EU suspended "Test Agent v3", whose card (made
# 2026-09-12, no protocolVersion) fails today's schema, so ASIA quarantined every update and kept serving the old copy
# ACTIVE AND UNENFORCED FOR TWELVE DAYS. The peer's fix was to refuse the untrusted CONTENT while still applying the
# home's deny-only facts. My export gate would have re-created the bug one layer earlier: with the envelope never
# leaving, there is nothing for the peer to take the denial from.
#
# So a card that is inactive or under enforcement is exported even when it fails the model. The quarantine on the far
# side still refuses its content; what it must not lose is the denial.
from agentvault_registry.routers.federation_sync import export_skip_reason  # noqa: E402

SUSPENDED_EXT = {"uri": "https://theprotocol.cloud/extensions/v1/enforcement", "params": {"status": "suspended"}}


def test_a_failing_card_is_skipped_when_it_carries_no_denial():
    bad = {"did": DID, "humanReadableId": DID, "name": "x"}
    assert export_skip_reason(True, bad) is not None


def test_a_failing_card_that_its_home_DEACTIVATED_is_still_exported():
    bad = {"did": DID, "humanReadableId": DID, "name": "x"}
    assert export_skip_reason(False, bad) is None, "the peer would never learn the card was withdrawn"


def test_a_failing_card_under_ENFORCEMENT_is_still_exported():
    bad = {"did": DID, "humanReadableId": DID, "name": "x", "extensions": [SUSPENDED_EXT]}
    assert export_skip_reason(True, bad) is None, "a suspended agent would stay active on every peer"


def test_a_passing_card_is_always_exported():
    assert export_skip_reason(True, _good()) is None
    assert export_skip_reason(False, _good()) is None


def test_an_active_unenforced_failing_card_is_the_only_thing_withheld():
    """The gate's whole remaining job, stated as one case."""
    bad = {"did": DID, "humanReadableId": DID, "name": "x",
           "extensions": [{"uri": "https://theprotocol.cloud/extensions/v1/enforcement",
                           "params": {"status": "active"}}]}
    assert export_skip_reason(True, bad) is not None
