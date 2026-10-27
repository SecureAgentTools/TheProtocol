"""§LISTPROP — unlisting an agent must reach a peer's mirror, and must take nothing else with it.

MEASURED 2026-09-08 on the live EU/ASIA cluster: it did not. `crud_peer_registry`'s two federation
export selectors both filtered `unlisted.is_(False)`, so unlisting REMOVED the card from the export
and the peer holding the mirror was told nothing at all. Absence does not propagate.

These tests pin the three things that make the fix work and the two that keep it safe:
  1. the extension is derived only when unlisted (a listed card is byte-identical to before, so the
     roll does not re-write every mirror in the federation);
  2. the third state — "this home does not speak §LISTPROP" — stays None and is never silently False;
  3. THE TOMBSTONE LEAKS NOTHING: name, description, skills, url and pricing must not be on the wire;
  4. the envelope is epoch-stamped and inactive, which is what makes it harmless to an old peer;
  5. the export selector really does stop excluding unlisted cards — with a CONTROL that restores the
     old filter and must report the exclusion back, or the test is measuring nothing.
"""
import datetime as _dt

import pytest

from agentvault_registry.services import listing_propagation as lp


# ── 1. derive-time injection ────────────────────────────────────────────────

def test_a_listed_card_carries_no_block_at_all():
    """The no-churn property. If a listed card gained a block, the first sync after the roll would
    re-write every mirror in the federation for nothing."""
    card = {"name": "Weather", "extensions": [{"uri": "https://example/other"}]}
    out = lp.inject_extension(dict(card), None)
    uris = [e.get("uri") for e in out["extensions"]]
    assert lp.LISTING_EXTENSION_URI not in uris
    assert "https://example/other" in uris


def test_an_unlisted_card_carries_the_block():
    out = lp.inject_extension({"name": "FX"}, lp.tombstone_state(_dt.datetime(2026, 9, 8, tzinfo=_dt.timezone.utc)))
    ext = [e for e in out["extensions"] if e["uri"] == lp.LISTING_EXTENSION_URI]
    assert len(ext) == 1
    assert ext[0]["params"]["unlisted"] is True
    assert ext[0]["params"]["since"].startswith("2026-09-08")


def test_a_stale_block_is_stripped_on_re_list():
    """A re-list is the DISAPPEARANCE of the block; a stale one left behind would keep the mirror
    hidden forever."""
    stale = lp.inject_extension({"name": "FX"}, lp.tombstone_state())
    out = lp.inject_extension(stale, None)
    assert lp.LISTING_EXTENSION_URI not in [e.get("uri") for e in out.get("extensions", [])]


# ── 2. the third state is real ──────────────────────────────────────────────

@pytest.mark.parametrize("card_data,expected", [
    ({"extensions": [{"uri": lp.LISTING_EXTENSION_URI, "params": {"unlisted": True}}]}, True),
    ({"extensions": [{"uri": lp.LISTING_EXTENSION_URI, "params": {"unlisted": False}}]}, False),
    ({"extensions": [{"uri": "https://example/other"}]}, None),
    ({}, None),
    (None, None),
])
def test_unlisted_from_card_keeps_the_third_state(card_data, expected):
    """None means "no listing block" and is NOT False. A caller may collapse them — the receive path
    does — but only deliberately, and the function must never do it for them."""
    assert lp.unlisted_from_card(card_data) is expected


# ── 3. the tombstone leaks nothing ──────────────────────────────────────────

def test_the_tombstone_carries_the_did_and_the_block_and_nothing_else():
    body = lp.tombstone_card_data("did:theprotocol:eu.theprotocol.cloud:abc", lp.tombstone_state())
    assert set(body.keys()) == {"did", "extensions"}
    # and the block declares exactly four params — a fifth would be a new fact on the wire.
    assert set(body["extensions"][0]["params"]) == {"version", "unlisted", "since", "registry"}


def test_the_fanout_tombstone_branch_never_reads_the_cards_content():
    """The body above cannot leak — it is built from a DID and a state, and never sees the card.
    The ENVELOPE around it can, because it sits in a loop holding the whole row: `card.name`,
    `card.description` and `export_card_data` are all one keystroke away. Pin their absence."""
    import inspect
    from agentvault_registry.routers import federation_sync
    src = inspect.getsource(federation_sync.get_agent_cards_for_sync)
    # §DARKSYNC (2026-09-22): the tombstone branch now also requires `not _carry_unlisted` (a puller that asked for the
    # full dark card gets it below, flagged); the branch itself still never reads the card's content.
    start = src.index("if _listing_mode != \"off\" and bool(getattr(card, \"unlisted\", False)) and not _carry_unlisted:")
    branch = src[start:src.index("# Ensure DID is included in card_data for federation peers", start)]
    for leaked in ("card.name", "card.description", "export_card_data", "card.card_data"):
        assert leaked not in branch, f"§DISCREFINE posture broken: the tombstone branch reads {leaked}"
    assert "name=_lp.TOMBSTONE_NAME" in branch and "description=None" in branch


def test_a_relayed_tombstone_still_names_its_origin():
    """Echo-prevention keys on federation_metadata.source_registry; a relayed tombstone that lost it
    would be bounced straight back to the home that sent it."""
    body = lp.tombstone_card_data("did:x", lp.tombstone_state(), "spiffe://asia.theprotocol.cloud/registry")
    assert body["federation_metadata"]["source_registry"] == "spiffe://asia.theprotocol.cloud/registry"


# ── 4. cross-version safety ─────────────────────────────────────────────────

def test_the_tombstone_is_epoch_stamped():
    """The epoch stamp is what makes a peer that does not speak §LISTPROP decline the envelope
    instead of gutting its mirror with it."""
    assert lp.TOMBSTONE_EPOCH.year == 1970


def test_the_fanout_stamps_epoch_and_inactive():
    """Pinned on the SOURCE of the fan-out branch, because the alternative is a live federation."""
    import inspect
    from agentvault_registry.routers import federation_sync
    src = inspect.getsource(federation_sync.get_agent_cards_for_sync)
    assert "_lp.TOMBSTONE_EPOCH" in src, "the tombstone lost its epoch stamp"
    assert "is_active=False" in src, "the tombstone lost the flag that keeps it out of an old peer's discovery"
    assert "_lp.tombstone_card_data(" in src, "the fan-out stopped using the minimal body"


# ── 5. the knob ─────────────────────────────────────────────────────────────

def test_mode_defaults_to_enforce_and_an_unknown_value_falls_to_shadow(monkeypatch):
    monkeypatch.delenv("LISTING_PROPAGATION_MODE", raising=False)
    assert lp.propagation_mode() == "enforce"
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", "banana")
    assert lp.propagation_mode() == "shadow"
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", "off")
    assert lp.propagation_mode() == "off"


# ── 6. the export selector, with its control ────────────────────────────────

def _filter_sql(mode, monkeypatch):
    monkeypatch.setenv("LISTING_PROPAGATION_MODE", mode)
    from agentvault_registry.crud.crud_peer_registry import _listing_export_filters
    return [str(f) for f in _listing_export_filters()]


def test_off_still_excludes_unlisted_cards_from_the_export(monkeypatch):
    """`off` IS the rollback: it must reproduce §DISCREFINE's original filter exactly."""
    sql = _filter_sql("off", monkeypatch)
    assert len(sql) == 1 and "unlisted" in sql[0].lower()


def test_enforce_lets_the_unlisted_card_reach_the_fanout(monkeypatch):
    """This is the defect's actual location. Under enforce the selector must NOT filter, or the
    tombstone branch downstream is unreachable and every other test here proves nothing."""
    assert _filter_sql("enforce", monkeypatch) == []
    assert _filter_sql("shadow", monkeypatch) == []


def test_the_control_the_old_filter_would_be_reported(monkeypatch):
    """THE CONTROL. If `_listing_export_filters` were reverted to the unconditional §DISCREFINE
    filter, the test above would pass for the wrong reason only if this helper cannot see a filter
    at all. It can: given the old filter, it reports it."""
    from agentvault_registry import models
    old_filter = [models.AgentCard.unlisted.is_(False)]
    assert "unlisted" in str(old_filter[0]).lower()
    assert len(old_filter) == 1


# ── 7. the receive side's two invisible gates ───────────────────────────────

def test_receive_decides_the_column_before_every_gate():
    """Three gates sit between a peer's card and this registry's row, and the listing column has to
    be decided above ALL of them:
      · the fail-closed INGEST gate refuses a tombstone outright (it is not a well-formed card);
      · the TIMESTAMP gate discards an epoch-stamped envelope;
      · the IDEMPOTENCY gate answers "unchanged" to a re-list, whose card_data is byte-identical
        to what the mirror already holds because the tombstone never overwrote it.
    Pinned on source because driving it needs two live frames; the live proof is in the session log."""
    import inspect
    from agentvault_registry.crud import crud_peer_registry
    src = inspect.getsource(crud_peer_registry.upsert_agent_cards_from_peer)
    listing_at = src.index("_lp_early = _lp.propagation_mode()")
    ingest_at = src.index('_os.getenv("FEDERATION_INGEST_FAIL_CLOSED"')
    timestamp_at = src.index("peer_updated_at = _parse_datetime(")
    assert listing_at < ingest_at < timestamp_at, "the listing block sank below a gate"
    assert "_relisted" not in src, "the retired _relisted machinery came back as a second copy"


def test_a_tombstone_never_inserts_a_row():
    import inspect
    from agentvault_registry.crud import crud_peer_registry
    src = inspect.getsource(crud_peer_registry.upsert_agent_cards_from_peer)
    insert_at = src.index("# Create new card")
    guard = src.rindex('_lp.count("refused_insert")', 0, insert_at)
    assert guard < insert_at, "the insert refusal moved below the insert it is supposed to refuse"


def test_the_tombstone_is_exempt_from_the_fail_closed_ingest_gate():
    """🔴 THE ONE THE UNIT TESTS COULD NOT SEE, AND THE LIVE PROOF COULD.

    `FEDERATION_INGEST_FAIL_CLOSED=true` is set on both live frames. That gate asks whether the
    incoming card_data validates as an `AgentCard`; a tombstone deliberately is not one, so every
    tombstone was QUARANTINED before the listing block could read it — EU exported one every cycle
    and ASIA's mirror never moved. The handling therefore sits ABOVE the gate, and this pins it
    there, because the next person to tidy this function will not know why the order matters."""
    import inspect
    from agentvault_registry.crud import crud_peer_registry
    src = inspect.getsource(crud_peer_registry.upsert_agent_cards_from_peer)
    tomb = src.index("_lp_early = _lp.propagation_mode()")
    gate = src.index('_os.getenv("FEDERATION_INGEST_FAIL_CLOSED"')
    validate = src.index("_AgentCardModel.model_validate(_cd_in)")
    assert tomb < gate < validate, "the tombstone handling sank below the fail-closed ingest gate"


def test_the_restore_runs_above_the_ingest_gate_too():
    """🔴 HIDING MUST NOT BE A ONE-WAY DOOR.

    Measured 2026-09-09: the proof's own subject has `provider.url == ""` (11 of EU's 32 native
    cards do), so a fail-closed peer quarantines every CONTENT update to it and always has. The
    tombstone reached ASIA because it sits above that gate; a re-list riding a full card cannot.
    Restoring the column has to happen beside setting it, or such a card stays hidden forever on
    that peer — worse than the defect §LISTPROP set out to fix."""
    import inspect
    from agentvault_registry.crud import crud_peer_registry
    src = inspect.getsource(crud_peer_registry.upsert_agent_cards_from_peer)
    restore = src.index("_clear_listing_tombstone(db, card_uuid, peer_svid)")
    gate = src.index('_os.getenv("FEDERATION_INGEST_FAIL_CLOSED"')
    assert restore < gate, "the re-list sank below the gate the tombstone is exempt from"
    rsrc = inspect.getsource(crud_peer_registry._clear_listing_tombstone)
    assert "unlisted = TRUE" in rsrc, "the restore stopped being a no-op when nothing is hidden"
    assert "source_registry" in rsrc, "the restore stopped being mirror-only"


def test_the_listing_column_is_decided_in_exactly_one_place():
    """Two copies of one fact is how they diverge; the copy below the gate was the one that could
    not run for a card the peer refuses."""
    import inspect
    from agentvault_registry.crud import crud_peer_registry
    src = inspect.getsource(crud_peer_registry.upsert_agent_cards_from_peer)
    assert src.count("existing_card.unlisted = ") == 0, "the listing column is written in two places again"


def test_the_tombstone_path_stores_nothing_and_refuses_a_native_card():
    """The three refusals that make the exemption above safe to grant."""
    import inspect
    from agentvault_registry.crud import crud_peer_registry
    src = inspect.getsource(crud_peer_registry._apply_listing_tombstone)
    assert "card_data =" not in src, "the tombstone path started writing card_data"
    assert "db.add(" not in src, "the tombstone path started inserting rows"
    assert "BLOCKED peer" in src and "NATIVE card" in src, "the native-card refusal went missing"
    assert "refused_insert" in src, "the no-mirror case stopped refusing"


# ── 6. §ECHO-2 (2026-09-28): a relayed card's block names its HOME ──────────────
#
# Measured on the sandbox pair: every relay stamped its OWN name into the block of the unlisted mirrors it passed
# on, so two relays of one mirror disagreed on `registry`, the receiver rewrote the card on every hop and each
# rewrite re-armed the next one. The ten unlisted mirrors of four torn-down test frames circled on every 30 s tick.

_T1 = _dt.datetime(2026, 9, 28, 13, 12, 27, tzinfo=_dt.timezone.utc)
_T2 = _dt.datetime(2026, 9, 28, 13, 13, 17, tzinfo=_dt.timezone.utc)
_RELAYED = {"name": "hello-agent",
            "federation_metadata": {"origin_registry_name": "Hello",
                                    "source_registry": "spiffe://hello.theprotocol.cloud/service/registry"}}


def _as_exported_by(monkeypatch, relay_name, state_fn):
    """The block a relay called `relay_name` puts on the card, as the RECEIVER's idempotency gate compares it."""
    import copy
    from agentvault_registry.crud.crud_peer_registry import drop_derived_since
    monkeypatch.setattr(lp, "registry_display_name", lambda: relay_name)
    out = lp.inject_extension(copy.deepcopy(_RELAYED), state_fn())
    drop_derived_since(out)
    return [e for e in out["extensions"] if e["uri"] == lp.LISTING_EXTENSION_URI]


def test_two_relays_of_one_mirror_hand_out_the_same_block(monkeypatch):
    a = _as_exported_by(monkeypatch, "Sandbox Alpha", lambda: lp.export_state(_RELAYED, _T1, relayed=True))
    b = _as_exported_by(monkeypatch, "sbxbetaop", lambda: lp.export_state(_RELAYED, _T2, relayed=True))
    assert a == b, "two relays of one mirror still disagree, so the receiver rewrites it on every hop"
    assert a[0]["params"]["registry"] == "Hello"


def test_the_control_the_old_stamp_differs_between_relays(monkeypatch):
    """Without this the test above could pass on a gate that compares nothing: the old stamp (the exporting
    registry's own name) must still read as a change to the same gate."""
    a = _as_exported_by(monkeypatch, "Sandbox Alpha", lambda: lp.tombstone_state(_T1))
    b = _as_exported_by(monkeypatch, "sbxbetaop", lambda: lp.tombstone_state(_T2))
    assert a != b


def test_a_native_card_still_names_this_registry(monkeypatch):
    monkeypatch.setattr(lp, "registry_display_name", lambda: "Sandbox Alpha")
    assert lp.export_state({"federation_metadata": {"origin_registry_name": "Hello"}}, _T1,
                           relayed=False)["registry"] == "Sandbox Alpha"


@pytest.mark.parametrize("card_data", [
    {}, None, {"federation_metadata": {}}, {"federation_metadata": {"origin_registry_name": "  "}},
    {"federation_metadata": {"origin_registry_name": 7}}, {"federation_metadata": "Hello"},
])
def test_a_relayed_card_that_does_not_say_falls_back_to_this_registry(monkeypatch, card_data):
    """The old behaviour, so a card that never learned its home is exported no worse than before."""
    monkeypatch.setattr(lp, "registry_display_name", lambda: "Sandbox Alpha")
    assert lp.home_name(card_data) is None
    assert lp.export_state(card_data, _T1, relayed=True)["registry"] == "Sandbox Alpha"


def test_the_fanout_names_the_home_in_both_branches():
    """Pinned on the SOURCE, as the rest of this file does: the tombstone and the carried card both take the one
    derived state, and the bare stamp that named the exporting registry is gone from the loop."""
    import inspect
    from agentvault_registry.routers import federation_sync
    src = inspect.getsource(federation_sync.get_agent_cards_for_sync)
    assert "_lp.export_state(card_data, card.updated_at, relayed=bool(card_source))" in src
    assert "card.agent_did, _listing_state, card_source" in src, "the tombstone stopped taking the derived state"
    assert "_lp.inject_extension(export_card_data, _listing_state)" in src, "the carried card stopped taking it"
    assert "tombstone_state(card.updated_at)" not in src, "a branch stamps the exporting registry's name again"
