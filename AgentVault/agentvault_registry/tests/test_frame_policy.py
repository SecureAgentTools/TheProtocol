"""
§FRAMEPOLICY (2026-09-11) — the frame's policy document binds, and says so.

Every test here pins a defect that was measured LIVE on 2026-09-11, on EU and
ASIA (both V0324) and on registry-a:

  * the signed card published sha256("{}") as its policy hash while
    /federation/policy-compliance published sha256(DEFAULT_POLICY_JSON) — one
    frame, two hashes, and the card's described a document nobody was running
  * the card published the MINIMUM of each bounded range as "the operator's
    chosen value": EU told every peer it required a 5% quorum while the code
    used 10% and registry-a's own document had said 20% since April
  * a partial row lost every section written after it
  * our own factory default FAILED our own admission validator
  * an unknown key was accepted, stored, versioned and then read by nobody

The load-bearing control is BYTE-INERTNESS: a frame with no policy row must
behave exactly as it did before this shipped.
"""
import copy

import pytest

from agentvault_registry.crud.crud_enforcement import DEFAULT_POLICY_JSON
from agentvault_registry.services import frame_policy as fp
from agentvault_registry.services.federation_policy_validator import FederationPolicyValidator


# ---------------------------------------------------------------------------
# The document validates against itself and against the network
# ---------------------------------------------------------------------------

def test_factory_default_is_a_valid_document():
    """The validator's own control: if the shipped default does not pass, the
    validator is measuring something other than this system."""
    assert fp.validate_document(DEFAULT_POLICY_JSON) == []


def test_factory_default_passes_the_admission_validator():
    """Measured before the fix: 2 HIGH violations (velocity_scaling_factor 0.1
    against a locked 1.0, and a `destination` the locked set requires and the
    document never carried). A frame submitting its REAL running policy at
    admission would have been refused for running the shipped default."""
    result = FederationPolicyValidator().validate(DEFAULT_POLICY_JSON)
    assert result.valid, [v.to_dict() for v in result.violations]


def test_unknown_key_is_refused():
    problems = fp.validate_document({"governance": {"standrd_quorum_percent": 20}})
    assert any("unknown policy key" in p for p in problems), problems


def test_out_of_range_value_is_refused():
    # governance.standard_quorum_percent is BOUNDED [5, 40]
    problems = fp.validate_document({"governance": {"standard_quorum_percent": 99}})
    assert any("outside its allowed range" in p for p in problems), problems


def test_a_valid_edit_passes():
    """The control for the two refusals above — a gate that refuses everything
    is not a gate."""
    assert fp.validate_document({"governance": {"standard_quorum_percent": 25}}) == []


def test_operator_defined_escalation_levels_are_not_unknown_keys():
    """A frame may add a 5th dispute level; that is data, not a typo."""
    doc = {"dispute_escalation": {"levels": {"5": {"slash_percent": 75,
                                                   "action_types": ["revoke"]}}}}
    assert [p for p in fp.validate_document(doc) if "unknown policy key" in p] == []


# ---------------------------------------------------------------------------
# Resolution — byte-inert when absent, complete when partial
# ---------------------------------------------------------------------------

def test_absent_row_resolves_to_the_factory_default_byte_for_byte():
    """THE load-bearing rule. A frame with no policy row must not move."""
    assert fp.resolve(None) == DEFAULT_POLICY_JSON


def test_partial_row_keeps_sections_written_after_it():
    """registry-a's active row is from 2026-04-09 and predates §REPBOND by five
    months, so it carries no slash_waterfall and no staking_reputation. Read
    raw, those sections simply vanish — which is why enforcement_engine.py
    carries a SECOND inline copy of the waterfall default to survive it."""
    partial = {"governance": {"standard_quorum_percent": 20}}
    resolved = fp.resolve(partial)
    assert "slash_waterfall" in resolved
    assert "staking_reputation" in resolved
    assert resolved["governance"]["standard_quorum_percent"] == 20
    # and the sections it did not mention are the documented defaults
    assert resolved["dispute_escalation"] == DEFAULT_POLICY_JSON["dispute_escalation"]


def test_explain_separates_set_here_from_shipped_default():
    """'unset' and 'set to the default value' are different facts; a readout
    that cannot tell them apart is the §29e class."""
    row = {"governance": {"standard_quorum_percent": 25}}
    pol = fp.ResolvedPolicy(doc=fp.resolve(row), version=1, source="amended", _row_json=row)
    set_here = pol.explain("governance.standard_quorum_percent")
    defaulted = pol.explain("governance.standard_pass_percent")
    assert set_here["source"] == "policy" and set_here["value"] == 25
    assert defaulted["source"] == "default"
    assert defaulted["value"] == DEFAULT_POLICY_JSON["governance"]["standard_pass_percent"]


# ---------------------------------------------------------------------------
# One rule, one key
# ---------------------------------------------------------------------------

def test_deprecated_alias_keeps_the_frames_own_value():
    """The document shipped TWO names for the policy-change thresholds. A frame
    that set only the old one meant that value.

    ⚠ This is a merge concern and not a getter concern: after the merge the
    canonical key is never absent (the default fills it), so a getter fallback
    can never fire. Measured as exactly that contradiction — the readout said
    'you set this' while returning the shipped default."""
    row = {"governance": {"policy_proposal_quorum_percent": 42}}
    pol = fp.ResolvedPolicy(doc=fp.resolve(row), version=1, source="amended", _row_json=row)
    explained = pol.explain("governance.policy_change_quorum_percent")
    assert explained["value"] == 42
    assert explained["source"] == "policy"
    assert explained["via_deprecated_key"] == "governance.policy_proposal_quorum_percent"


def test_canonical_key_wins_when_both_are_present():
    row = {"governance": {"policy_proposal_quorum_percent": 42,
                          "policy_change_quorum_percent": 25}}
    assert fp.resolve(row)["governance"]["policy_change_quorum_percent"] == 25


def test_the_duplicate_key_is_gone_from_the_shipped_default():
    assert "policy_proposal_quorum_percent" not in DEFAULT_POLICY_JSON["governance"]
    assert "policy_proposal_pass_percent" not in DEFAULT_POLICY_JSON["governance"]


# ---------------------------------------------------------------------------
# The defaults are the LIVE numbers, not the numbers the document wished for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,live_value", [
    ("governance.standard_quorum_percent", 10.0),      # routers/governance.py
    ("governance.standard_pass_percent", 50.0),        # routers/governance.py
    ("governance.policy_change_quorum_percent", 20.0),  # routers/governance.py
    ("governance.policy_change_pass_percent", 66.0),    # routers/governance.py
    ("governance.max_lock_days", 365),                  # vetoken_calculator
    ("governance.flexible_stake_ve_multiplier_max", 0.01),  # vetoken_calculator
])
def test_default_equals_the_number_the_code_already_used(path, live_value):
    """If a default does not match the running system it is not a default, it is
    a silent behaviour change waiting for the roll that finally reads it. The
    document used to say 20.0 and 33.0 here while the code did 10.0 and 20.0."""
    pol = fp.ResolvedPolicy(doc=fp.resolve(None), version=0, source="factory_default")
    assert float(pol.get(path)) == float(live_value)


def test_vetoken_weights_are_unchanged_for_an_unamended_frame():
    """The §GOVDEMO weights (20 / 10 / 7.40 / 6.16 / 1.64) must survive the move
    from module constants to policy, or every past tally becomes unreproducible."""
    import datetime
    from decimal import Decimal
    from agentvault_registry.services.vetoken_calculator import (
        VeTokenCalculator, vetoken_calculator,
    )
    pol = fp.ResolvedPolicy(doc=fp.resolve(None), version=0, source="factory_default")
    calc = VeTokenCalculator.from_policy(pol)
    now = datetime.datetime.now(datetime.timezone.utc)
    for amount, days in ((400, 365), (400, 30), (100, 365), (225, 180), (625, 90), (500, 0)):
        assert calc.calculate_position_power(Decimal(amount), days, now, now) == \
               vetoken_calculator.calculate_position_power(Decimal(amount), days, now, now)


def test_an_amended_frame_actually_changes_the_weight():
    """The control for the test above: if the policy cannot move the number,
    nothing was wired."""
    import datetime
    from decimal import Decimal
    from agentvault_registry.services.vetoken_calculator import VeTokenCalculator
    row = {"governance": {"flexible_stake_ve_multiplier_max": 0.5}}
    pol = fp.ResolvedPolicy(doc=fp.resolve(row), version=1, source="amended", _row_json=row)
    now = datetime.datetime.now(datetime.timezone.utc)
    amended = VeTokenCalculator.from_policy(pol).calculate_position_power(
        Decimal(400), 0, now, now)
    factory = VeTokenCalculator().calculate_position_power(Decimal(400), 0, now, now)
    assert amended > factory


# ---------------------------------------------------------------------------
# One hash, published in one shape
# ---------------------------------------------------------------------------

def test_hash_is_over_the_resolved_document_not_the_raw_row():
    """The card hashed the RAW row (i.e. `{}` on a frame that never amended)
    while the compliance endpoints hashed the resolved default. Both peers
    published sha256("{}"), so a peer-to-peer comparison compared nothing with
    nothing and matched every time."""
    import hashlib, json
    empty_hash = hashlib.sha256(b"{}").hexdigest()
    assert fp.policy_hash(fp.resolve(None)) != empty_hash
    canonical = json.dumps(DEFAULT_POLICY_JSON, sort_keys=True, separators=(",", ":"))
    assert fp.policy_hash(fp.resolve(None)) == hashlib.sha256(canonical.encode()).hexdigest()


def test_a_policy_change_moves_the_hash():
    """The control: a hash that cannot move cannot detect drift."""
    row = {"governance": {"standard_quorum_percent": 25}}
    assert fp.policy_hash(fp.resolve(row)) != fp.policy_hash(fp.resolve(None))


def test_card_block_publishes_real_values_with_provenance():
    """The card used to publish bounds['min'] as the operator's chosen value:
    EU's signed card said quorum 5 / pass 40 while the code used 10 / 50."""
    from agentvault_registry.services.registry_card_builder import _build_policy_block
    from agentvault_registry.core.base_network_params import BOUNDED_PARAMS
    pol = fp.ResolvedPolicy(doc=fp.resolve(None), version=0, source="factory_default")
    block = _build_policy_block(pol)

    declared = block["declared_params"]
    q = declared["governance.standard_quorum_percent"]
    assert q["value"] == pol.get("governance.standard_quorum_percent")
    assert q["source"] in ("policy", "default")
    # and specifically NOT the minimum of the range, which is what it published before
    assert q["value"] != BOUNDED_PARAMS["governance.standard_quorum_percent"]["min"]
    assert block["policy_source"] == "factory_default"


def test_card_block_tracks_an_amended_policy():
    from agentvault_registry.services.registry_card_builder import _build_policy_block
    row = {"governance": {"standard_quorum_percent": 25}}
    pol = fp.ResolvedPolicy(doc=fp.resolve(row), version=3, source="amended", _row_json=row)
    block = _build_policy_block(pol)
    assert block["declared_params"]["governance.standard_quorum_percent"] == {
        "value": 25, "source": "policy",
        "allowed": {"min": 5, "max": 40},
    }
    assert block["policy_source"] == "amended" and block["policy_version"] == 3


# ---------------------------------------------------------------------------
# The wire — a field the response_model does not declare reaches nobody
# ---------------------------------------------------------------------------

def test_tally_response_declares_the_policy_fields():
    """⚠ Caught before shipping: crud_governance.tally_votes gained the policy
    fields, and FastAPI's response_model would have dropped every one of them
    SILENTLY while still answering 200. The Senate Floor's "which policy decided
    this" line would have been dead code, and a policy_change that PASSED
    without applying would have stayed exactly as invisible as before.

    Pin the WIRE, not the payload builder."""
    from agentvault_registry.routers.governance import TallyResponse
    declared = set(TallyResponse.model_fields)
    for field in ("policy_version", "policy_source", "quorum_percent", "pass_percent",
                  "policy_applied", "policy_new_version", "policy_apply_error"):
        assert field in declared, f"TallyResponse would silently drop {field!r}"


def test_tally_response_keeps_a_none_policy_applied_distinct_from_false():
    """None = not a policy_change proposal · False = it was, and the policy did
    not move. Collapsing those two is the §29e class on a governance rail."""
    from agentvault_registry.routers.governance import TallyResponse
    base = dict(proposal_id=1, votes_for=1, votes_against=0, total_votes=1, status="PASSED")
    assert TallyResponse(**base).policy_applied is None
    assert TallyResponse(**base, policy_applied=False).policy_applied is False


def test_tally_handler_passes_the_whole_payload_not_a_hand_listed_subset():
    """⚠ THE TEST ABOVE WAS NOT ENOUGH, and the live proof is what found it.

    `test_tally_response_declares_the_policy_fields` pins the response MODEL.
    The handler built its response field by field, so all seven policy fields
    existed in the payload AND in the model and still reached nobody: the live
    tally of proposal #2 on EU applied its policy and reported
    `policy_applied=None`. A field-by-field response mapper is a silent-drop
    machine (PART 1), and a test that checks the model is blind to it in exactly
    the same way the model is.

    So pin the CONSTRUCTOR: the handler must splat the payload, which makes a
    new field reach the wire by construction with TallyResponse as the contract
    for what is allowed through.
    """
    import ast
    import inspect
    from agentvault_registry.routers import governance as gov

    tree = ast.parse(inspect.getsource(gov.tally_proposal_votes))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "TallyResponse"]
    assert calls, "the tally handler no longer builds a TallyResponse"
    for call in calls:
        starred = [k for k in call.keywords if k.arg is None]
        assert starred, (
            "the tally handler hand-lists its response fields again — a field added "
            "to the payload will be dropped silently while the endpoint answers 200"
        )


def test_tally_payload_and_response_model_cannot_drift():
    """Every key the payload carries must be a field the model declares, or it is
    dropped in silence; every field the model declares must be a key the payload
    can carry, or it is None forever."""
    from agentvault_registry.routers.governance import TallyResponse
    payload_keys = {
        "proposal_id", "votes_for", "votes_against", "total_votes", "quorum_met",
        "pass_rate", "status", "policy_applied", "policy_new_version",
        "policy_apply_error", "policy_version", "policy_source",
        "quorum_percent", "pass_percent",
        "already_tallied",   # §MEMBERSHIP (2026-10-02): False on a real tally, True on a closed proposal's stored result
        # §MEMBERSHIP (mig 0185): the tally-time record, on both payloads (crud_governance.tally_record)
        "tally_weight_mode", "tally_network_power", "tally_quorum_required", "tally_quorum_met", "tallied_at",
    }
    declared = set(TallyResponse.model_fields)
    assert payload_keys - declared == set(), f"payload carries fields the model drops: {payload_keys - declared}"
    assert declared - payload_keys == set(), f"model declares fields the payload never sets: {declared - payload_keys}"


def test_a_policy_change_stores_the_decision_not_a_full_snapshot():
    """Measured on EU right after the first real policy_change: a proposal that
    changed ONE value persisted the ENTIRE default document, so every other
    field read back as "this frame set it" when nobody had chosen it — and the
    frame silently stopped inheriting later changes to any shipped default.

    The row holds decisions; resolve() merges them onto the defaults at read
    time. Provenance is only honest if those two stay separate.
    """
    import copy
    from agentvault_registry.crud.crud_governance import _deep_merge

    # what the apply path now does: merge the diff onto the stored row, not the defaults
    stored = {}
    merged = _deep_merge(copy.deepcopy(stored), {"governance": {"standard_quorum_percent": 15.0}})
    assert merged == {"governance": {"standard_quorum_percent": 15.0}}, merged

    pol = fp.ResolvedPolicy(doc=fp.resolve(merged), version=1, source="amended", _row_json=merged)
    chosen = pol.explain("governance.standard_quorum_percent")
    untouched = pol.explain("governance.standard_pass_percent")
    assert chosen["source"] == "policy" and chosen["value"] == 15.0
    assert untouched["source"] == "default", (
        "a field nobody voted on must still read as the shipped default, or the "
        "frame has silently pinned every default it never chose"
    )
    # and a second change accumulates rather than replacing
    merged2 = _deep_merge(copy.deepcopy(merged), {"governance": {"standard_pass_percent": 55.0}})
    assert merged2["governance"] == {"standard_quorum_percent": 15.0, "standard_pass_percent": 55.0}
