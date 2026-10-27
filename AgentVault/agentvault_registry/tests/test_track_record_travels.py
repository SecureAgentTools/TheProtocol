"""§TRAVELREC — the work record crosses a frame boundary on the card that already crosses it.

THE BUG THIS PINS. `inject_track_record_extension` existed and was called in exactly one place:
the agent's own well-known card. The FEDERATION EXPORT injected the reputation bond and the
enforcement state and not this, so a peer mirrored a bonded, certified, enforced card carrying no
evidence of the work that earned any of it. Measured on the live pair before the fix:

    EU   (home)   track_record: {jobs: 250, stars: 4.58, on_time 240/250}
    ASIA (mirror) track_record: None

Same class as §FANOUTFIX: a capability built correctly and wired at one of its call sites.

WHAT TRAVELS IS A CLAIM PLUS A WAY TO CHECK IT. The origin states the compact summary on the card
it signs and states where to verify it. A peer renders the origin's claim, attributed, and can
dial `verify_at` if it cares. A pointer alone would not do: a discovery page renders thousands of
cards and cannot fetch an attestation for each one.
"""
from agentvault_registry.services.track_record import (
    TRACK_RECORD_EXTENSION_URI,
    compact_from_card,
    inject_track_record_extension,
)

COMPACT = {"jobs": 250, "stars": 4.58, "five_star": 156, "on_time_met": 240,
           "on_time_of": 250, "traveled": 0, "cross_registry": 0, "disputes": 0,
           "open_disputes": 0, "lost_disputes": 0, "last_verified_at": "2026-09-09T23:44:04Z"}
DID = "did:theprotocol:eu.theprotocol.cloud:76a8ed9b"


def _ext(card):
    return [e for e in card["capabilities"]["extensions"]
            if e.get("uri") == TRACK_RECORD_EXTENSION_URI][0]


def test_export_carries_the_summary_and_where_to_verify_it():
    card = inject_track_record_extension({}, DID, compact=COMPACT)
    params = _ext(card)["params"]
    assert params["compact"]["jobs"] == 250
    assert params["compact"]["stars"] == 4.58
    assert params["verify_at"], "a claim with no way to check it is just a claim"
    assert "/track-record" in params["verify_at"]


def test_a_peer_reads_it_back_and_knows_whose_claim_it_is():
    card = inject_track_record_extension({}, DID, compact=COMPACT)
    got = compact_from_card(card)
    assert got is not None
    assert got["jobs"] == 250 and got["stars"] == 4.58
    assert got["attested"] is True, "a peer must not present an origin's claim as its own finding"
    assert got["verify_at"] == _ext(card)["params"]["verify_at"]


def test_the_regression_itself_a_card_without_the_extension_reads_none():
    """THE CONTROL. This is the shape every mirrored card had before the fix, and the reason the
    peer's page was blank. If this ever returns a record, the reader is inventing one."""
    assert compact_from_card({"capabilities": {"extensions": []}}) is None
    assert compact_from_card({}) is None
    assert compact_from_card(None) is None


def test_pointer_only_is_not_a_record():
    """The well-known-card shape: the extension is present but carries no summary. A peer must
    read that as 'no record known here', not as a zero."""
    card = inject_track_record_extension({}, DID)          # no compact
    assert "compact" not in _ext(card)["params"]
    assert compact_from_card(card) is None


def test_an_agent_with_no_history_is_absent_not_zero():
    """A zero written by us is indistinguishable from a zero the ledger holds, so never write one."""
    assert compact_from_card(inject_track_record_extension({}, DID, compact={"jobs": 0})) is None


def test_injection_is_idempotent_by_uri():
    card = inject_track_record_extension({}, DID, compact=COMPACT)
    card = inject_track_record_extension(card, DID, compact=COMPACT)
    hits = [e for e in card["capabilities"]["extensions"]
            if e.get("uri") == TRACK_RECORD_EXTENSION_URI]
    assert len(hits) == 1


def test_the_export_site_actually_calls_it():
    """Pin the CALL SITE, because the bug was never in the function.

    The function was correct and complete for a year. What was missing was one line at the place
    where cards leave this registry. A unit test of the injector would have passed throughout.
    """
    import inspect
    from agentvault_registry.routers import federation_sync
    src = inspect.getsource(federation_sync)
    assert "inject_track_record_extension" in src, (
        "the federation export must inject the record, or it does not travel"
    )
    i_bond = src.find("_rb.inject_extension")
    i_rec = src.find("inject_track_record_extension")
    assert i_bond != -1 and i_rec != -1


# ---------------------------------------------------------------------------------------------
# The second half, which the first fix did not have and which made it inert on a live pair.
# ---------------------------------------------------------------------------------------------

def test_a_newly_attached_summary_is_treated_as_additive_at_ingest():
    """A DERIVED field cannot ride a clock, so the ingest must let it in without one.

    Measured on the live pair after the export fix shipped: EU's exporter produced the summary
    correctly and ASIA's mirror still read None, through a forced pull AND a forced full
    reconcile. Nothing about Sheldon's card had changed, so `updated_at` had not moved, and the
    ingest applies a peer's card only when its envelope is NEWER. The reconcile does not help:
    it re-READS from epoch and then skips every card for being the same age.

    §DIRFEED states this from the reader's side — an incremental index is blind to a field the
    read gained. This is the same law at the write side, and the flare clause above it is the
    same accommodation made once before.
    """
    from agentvault_registry.crud.crud_peer_registry import _has_track_record_ext
    incoming = inject_track_record_extension({}, DID, compact=COMPACT)
    assert _has_track_record_ext(incoming) is True
    assert _has_track_record_ext({}) is False
    # pointer-only is NOT new information: the agent's own well-known card carries that shape
    assert _has_track_record_ext(inject_track_record_extension({}, DID)) is False


def test_the_ingest_actually_consults_it():
    """Pin the CALL SITE again. A predicate nothing asks is the bug this program keeps finding.

    §ECHO (2026-09-28): the ingest's "new field" tests live in ONE function, `new_fields_offered`, which the ingest
    both admits by and merges by (merge_new_fields). The pin follows that chain: the ingest asks it, and it answers
    'track_record' for a card that newly carries the summary and not for the pointer-only shape."""
    import inspect
    from agentvault_registry.crud import crud_peer_registry as c
    src = inspect.getsource(c.upsert_agent_cards_from_peer)
    assert "new_fields_offered(existing_cd, incoming_card_data)" in src
    assert "has_new_fields = bool(_new_fields)" in src
    assert "track_record" in c.new_fields_offered({}, inject_track_record_extension({}, DID, compact=COMPACT))
    assert "track_record" not in c.new_fields_offered({}, inject_track_record_extension({}, DID))


def test_the_discover_fallback_references_no_helper_defined_below_it():
    """The third bug in this chain, and the one that answered 200 while doing nothing.

    The fallback called `_jsonb(...)`, defined further down the same function, so every call
    raised UnboundLocalError — caught by the enrichment's own try/except and logged as a warning.
    Discovery kept working, the record kept not appearing, nothing failed loudly.

    ⚠ THE FIRST VERSION OF THIS TEST MEASURED THE WRONG THING: it compared the POSITION of the
    fallback against the position of `def _jsonb`, which stays "wrong" forever even after the
    fallback stops calling it. Position is not the invariant. REFERENCE is: the fallback must not
    name a helper that is defined after it. §DISCECHO — a gate that reads source cannot see an
    ordering, so pin the thing that actually breaks.
    """
    import inspect, re
    from agentvault_registry.routers import agent_cards
    src = inspect.getsource(agent_cards)
    m_def = re.search(r"\n\s*def _jsonb\b", src)
    m_use = re.search(r"compact_from_card\(", src)
    assert m_use, "the discover fallback must exist"
    if not m_def:
        return
    # the fallback block: from the line that binds _cd to the compact_from_card call
    blk_start = src.rfind("\n", 0, max(0, src.rfind("_cd =", 0, m_use.start())))
    block = src[blk_start:m_use.end() + 120]
    assert "_jsonb(" not in block, (
        "the track-record fallback calls _jsonb, which is defined below it — "
        "UnboundLocalError at runtime, swallowed by the enrichment handler"
    )


def test_every_settle_site_moves_the_card_clock():
    """The forward half. Without this a peer keeps yesterday's summary forever.

    Six places in the guild router settle a work order. Each changes the record, and a record
    that changes without moving the card's clock is invisible to a cursor AND to a digest, which
    is the pair of blindnesses that made this bug survive two fixes. Counting the sites is the
    test: adding a seventh settle path without a touch should fail here, loudly, rather than
    quietly stop propagating for that one path.
    """
    import inspect, re
    from agentvault_registry.routers import guild
    src = inspect.getsource(guild)
    settles = len(re.findall(r"UPDATE guild_work_orders SET status='settled'", src))
    touches = len(re.findall(r"_tr_touch\(db", src))
    assert settles > 0, "no settle sites found — the anchor moved"
    assert touches >= settles, (
        f"{settles} settle sites but only {touches} card touches: a settled job on an untouched "
        f"path never reaches the peers mirroring that agent"
    )


def test_the_export_shape_is_versioned_and_served():
    """§DIRFEED's writer half: a digest over STORED cards cannot see a change to what we DERIVE.

    Without this, the day a registry starts attaching a new field every peer's digest still
    matches and every peer defers the walk, so the new field reaches nobody. Measured: that is
    exactly what happened, and neither a forced pull nor a forced full reconcile broke it.
    """
    import inspect
    from agentvault_registry.routers import federation_sync as fsr
    assert getattr(fsr, "CARD_EXPORT_VERSION", None), "the export shape must be named"
    src = inspect.getsource(fsr.get_sync_digest)
    assert "export_version" in src, "the digest must publish the export shape"

    from agentvault_registry.background_tasks import federation_sync as fsw
    wsrc = inspect.getsource(fsw)
    assert "_last_export_version" in wsrc and "export shape changed" in wsrc, (
        "the puller must walk once when a peer's export shape changes, even on an equal digest"
    )

    # ⚠ AND IT MUST BE CHECKED AT THE **FIRST** GATE, NOT ONLY THE DIGEST.
    # Measured: the watermark fast-path returns "watermark" before _digest_probe is ever called,
    # so a version check that lives only in the digest sits behind a door nobody opens. The first
    # attempt at this fix did exactly that and changed nothing on a live pair.
    wsrc_ep = inspect.getsource(fsr.get_sync_watermark)
    assert "export_version" in wsrc_ep, (
        "the watermark must publish the export shape — it is the first gate a peer hits"
    )
    assert "FED-WATERMARK" in wsrc, (
        "the watermark fast-path must refuse to skip on a changed export shape"
    )
    # ⚠ AND IT MUST FORCE A FULL RE-READ. Bypassing the watermark alone buys an INCREMENTAL page,
    # which asks for cards newer than the cursor and gets none: nothing about those cards changed,
    # only what the peer says about them. Measured — the walk happened and returned zero rows.
    i_wm = wsrc.find("FED-WATERMARK")
    tail = wsrc[i_wm:i_wm + 1400]
    assert "_RECONCILE_CURSOR_PREFIX" in tail and "_SYNC_EPOCH" in tail, (
        "a changed export shape must seed a walk from EPOCH, not merely skip the watermark"
    )
