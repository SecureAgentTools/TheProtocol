"""§BONDFILL (2026-09-11) — the bond's maturity crosses the frame boundary, and the half that
moves with the CLOCK deliberately does not.

Every test here is paired with a control that must fail on the pre-fix code, because a test that
cannot fail measures nothing. The two that matter most are:

  * `test_snapshot_omits_the_clock_derived_fields` — the design decision. Age and percent are
    functions of *now*, so a value written into an exported card is wrong the next morning and
    NO incremental gate can notice: cursor, watermark, digest and the reconcile walk all ask
    about stored rows, and a row that only aged has not changed. The reader recomputes them
    from `locked_at`, which is signed and already travels.

  * `test_age_is_recomputed_not_read_back` — proves that is actually what happens, by resolving
    two snapshots that differ ONLY in `locked_at` and asserting the ages differ. A resolver that
    read a stored age would pass every other test in this file.
"""
from datetime import datetime, timedelta, timezone

from agentvault_registry.services import reputation_bond as rb

# §BONDFILL-3 — the trust gate is relative: evidence (independent raters) AND standing (a percentile
# of the frame's ranked agents), the standing half waived below a population that can be ranked.
TH = {"min_transactions": 10, "min_age_days": 30, "min_trust_percentile": 50,
      "min_rated_peers": 3, "min_ranked_population": 10, "releases_percent": 60}


def _p(tx=4, age=3, et=0.0002, th=None, raters=1, pct=82.4, pop=17):
    return rb.progress_dict(transactions=tx, age_days=age, eigentrust=et, thresholds=th or TH,
                            rated_peers=raters, trust_percentile=pct, trust_population=pop)


# ── the long pole is named by the rule, not guessed by each surface ──────────

def test_blocking_names_the_furthest_behind_gate_first():
    # 4/10 settlements (0.40), 3/30 days (0.10), trust: 1 of 3 independent raters (0.33) at the
    # 82nd percentile (standing met). Age is furthest behind, then trust, then settlements.
    p = _p()
    assert p["blocking"] == ["age", "trust", "transactions"]
    assert p["percent"] == 28


def test_blocking_is_empty_once_every_gate_is_met():
    p = _p(tx=10, age=30, raters=3, pct=50.0)
    assert p["matured"] is True
    assert p["blocking"] == []


def test_a_met_gate_never_appears_in_blocking():
    # Settlements done, age and trust still short.
    p = _p(tx=99, age=3, raters=0)
    assert "transactions" not in p["blocking"]
    assert set(p["blocking"]) == {"age", "trust"}


def test_a_zero_threshold_is_a_satisfied_condition_not_a_division_by_zero():
    p = _p(tx=0, age=0, raters=0, pct=0.0,
           th={"min_transactions": 0, "min_age_days": 0, "min_trust_percentile": 0,
               "min_rated_peers": 0, "min_ranked_population": 10})
    assert p["matured"] is True and p["blocking"] == [] and p["percent"] == 100


# ── what the exported card carries, and what it deliberately does not ───────

def test_snapshot_omits_the_clock_derived_fields():
    m = rb.maturity_params(_p())
    assert m is not None
    assert "age_days" not in m, "age moves with the clock; a stored copy rots and no gate sees it"
    assert "percent" not in m, "percent is a function of age; same reason"
    # What it MUST carry: the two counters a reader cannot derive, and the origin's thresholds.
    assert m["transactions"] == 4
    assert m["eigentrust"] == 0.0002
    # The GATE thresholds travel. `releases_percent` deliberately does not: it governs the
    # origin's unlock rail, and a mirror has no unlock to offer.
    assert m["thresholds"] == {k: TH[k] for k in ("min_transactions", "min_age_days",
                                                  "min_trust_percentile", "min_rated_peers",
                                                  "min_ranked_population")}
    assert "releases_percent" not in m["thresholds"]
    assert m["as_of"], "a claim about a moment must say which moment"


def test_no_progress_means_no_snapshot_rather_than_an_empty_one():
    assert rb.maturity_params(None) is None


def test_the_exported_extension_carries_the_snapshot():
    state = {"bond": {"status": "locked", "amount": "250", "currency": "ECU",
                      "locked_at": "2026-09-08T00:00:00+00:00", "progress": _p()}}
    card = rb.inject_extension({"name": "Shadowban Sheldon"}, state)
    ext = [e for e in card["extensions"] if e["uri"] == rb.BOND_EXTENSION_URI]
    assert len(ext) == 1
    assert ext[0]["params"]["maturity"]["transactions"] == 4


def test_an_unmeasured_bond_exports_no_maturity_key_at_all():
    """Absent is not zero: a key present with a null value reads as 'measured, and it is
    nothing', which is a different claim from 'this origin published nothing'.

    Asserted against its own positive control in the SAME test, or it would pass trivially on
    a build that never writes the key at all (it did, and that is the defect this closes)."""
    base = {"status": "locked", "amount": "250", "currency": "ECU",
            "locked_at": "2026-09-08T00:00:00+00:00"}
    measured = rb.inject_extension({"name": "x"}, {"bond": dict(base, progress=_p())})
    unmeasured = rb.inject_extension({"name": "x"}, {"bond": dict(base, progress=None)})
    assert "maturity" in measured["extensions"][0]["params"]
    assert "maturity" not in unmeasured["extensions"][0]["params"]


# ── the reader's half ───────────────────────────────────────────────────────

def _mirror(locked_days_ago=3, tx=4, et=0.0002, raters=1, pct=82.4, pop=17):
    locked = datetime.now(timezone.utc) - timedelta(days=locked_days_ago, hours=1)
    state = {"bond": {"status": "locked", "amount": "250", "currency": "ECU",
                      "locked_at": locked.isoformat(),
                      "progress": rb.progress_dict(transactions=tx, age_days=locked_days_ago,
                                                   eigentrust=et, thresholds=TH, rated_peers=raters,
                                                   trust_percentile=pct, trust_population=pop)}}
    card = rb.inject_extension({}, state)
    return rb.extension_from_card(card)


def test_a_mirror_resolves_the_same_shape_the_home_frame_produces():
    resolved = rb.progress_from_card(_mirror())
    assert resolved is not None
    local = _p()
    for k in ("transactions", "transactions_required", "age_days", "age_days_required",
              "rated_peers", "rated_peers_required", "trust_percentile", "trust_percentile_required",
              "trust_percentile_state", "trust_population", "eigentrust",
              "met", "matured", "percent", "blocking"):
        assert resolved[k] == local[k], f"{k} differs between home and mirror"
    assert resolved["source"] == "card", "a claim this frame did not compute must say whose it is"
    assert resolved["as_of"], "and when it was true"


def test_age_is_recomputed_not_read_back():
    """THE CONTROL FOR THE WHOLE DESIGN. Two snapshots differing only in `locked_at`; a resolver
    that read a stored age would return the same number twice."""
    young = rb.progress_from_card(_mirror(locked_days_ago=3))
    old = rb.progress_from_card(_mirror(locked_days_ago=40))
    assert young["age_days"] == 3
    assert old["age_days"] == 40
    assert young["met"]["age"] is False and old["met"]["age"] is True


def test_an_origin_that_publishes_no_snapshot_resolves_to_none_not_to_zero():
    params = {"status": "locked", "amount": "250", "locked_at": "2026-09-08T00:00:00+00:00"}
    assert rb.progress_from_card(params) is None
    assert rb.progress_from_card(None) is None
    assert rb.progress_from_card({"maturity": "not-a-dict"}) is None


def test_a_card_with_no_locked_at_reports_zero_age_rather_than_raising():
    params = {"status": "locked", "maturity": {"version": 2, "transactions": 4, "eigentrust": 0.5,
                                               "rated_peers": 1, "trust_percentile": 60.0,
                                               "trust_population": 17, "thresholds": TH}}
    r = rb.progress_from_card(params)
    assert r is not None and r["age_days"] == 0 and r["met"]["age"] is False


def test_junk_in_the_snapshot_degrades_to_zero_rather_than_raising():
    params = {"locked_at": "not-a-date",
              "maturity": {"transactions": "seven", "eigentrust": None, "thresholds": {}}}
    r = rb.progress_from_card(params)
    assert r is not None and r["transactions"] == 0 and r["eigentrust"] == 0.0


# ── the additive-ingest clause (the gate a clock-only reader cannot pass) ────

def test_ingest_sees_a_card_that_newly_gained_a_maturity_block():
    from agentvault_registry.crud.crud_peer_registry import _has_bond_maturity
    state = {"bond": {"status": "locked", "amount": "250", "currency": "ECU",
                      "locked_at": "2026-09-08T00:00:00+00:00", "progress": _p()}}
    enriched = rb.inject_extension({"name": "x"}, state)
    bare = rb.inject_extension({"name": "x"}, {"bond": dict(state["bond"], progress=None)})
    assert _has_bond_maturity(enriched) is True
    # THE CONTROL: the bond extension alone is NOT enough. Every bonded card has carried the
    # URI since §REPBOND, so a predicate keyed on the URI would fire for every card forever
    # and force a full re-ingest of the fleet on every cycle.
    assert _has_bond_maturity(bare) is False
    assert _has_bond_maturity({"name": "no extensions here"}) is False
    assert _has_bond_maturity(None) is False


# ── the name a card publishes for the registry that signed it ───────────────

def test_the_registry_names_itself_from_the_variable_that_is_actually_set(monkeypatch):
    """§BONDFILL — `registry_display_name` read ONLY `REGISTRY_FEDERATION_NAME`, which is unset on
    every frame in the fleet, so every bonded card EU and ASIA ever exported carried
    `"registry": "registry"` — a last-resort placeholder published as if it were a name. Measured
    live on EU before the fix. Nothing rendered the field until the maturity bar had to say whose
    claim it was showing, which is why a value wrong for weeks looked fine.

    The frame's real name sits in `settings.REGISTRY_NAME` (measured live: "EU" / "ASIA", agreeing
    with the canonical DB-backed `_get_display_name`). ⚠ `monkeypatch.delenv` cannot unset it: the
    pydantic Settings singleton read the environment at import, so this test drives the env vars
    the function itself reads and asserts the ORDER, which is the contract that matters.
    """
    monkeypatch.setenv("REGISTRY_NAME", "EU")
    monkeypatch.delenv("REGISTRY_FEDERATION_NAME", raising=False)
    assert rb.registry_display_name() == "EU"

    # An explicitly-set federation name still wins, so a node that set one is byte-unchanged.
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "EU-Federation")
    assert rb.registry_display_name() == "EU-Federation"

    # THE CONTROL that makes the above mean something: the pre-fix function consulted exactly one
    # name, so with that one absent it fell to the placeholder. Assert the frame's own name is
    # genuinely reachable now — a generic category noun must never be published as an identity.
    monkeypatch.delenv("REGISTRY_FEDERATION_NAME", raising=False)
    monkeypatch.setenv("REGISTRY_NAME", "ASIA")
    got = rb.registry_display_name()
    assert got == "ASIA" and got != "registry"
