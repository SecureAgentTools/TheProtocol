"""
§TRUSTPOLICY (2026-09-11) — the peer trust number becomes a decision.

Every test pins something measured LIVE on EU's `peer_registries` on 2026-09-11:

    peer        type            interactions  disputes  discount
    amsterdam   cloud_operator       9            0      0.9091
    lisbon      cloud_operator       5            0      0.8571
    asia        frame               15            0      0.9412
    hochiminh   discovered           0            0      0.5000   <- the Beta(1,1) prior
    shenzhen    discovered           0            0      0.5000   <- the Beta(1,1) prior
    ASIA        frame (INACTIVE)     0            0      1.0000   <- the COLUMN default

Two of those populations are traps pointing in opposite directions, and both are
about EVIDENCE rather than the number: 0.5 means "nothing observed" and reads as
half-trust; 1.0 on a row nobody has transacted with means "nothing observed" and
reads as perfect. A threshold applied straight to the number restricts the peers
who have done nothing wrong and trusts the ghost.
"""
import pytest

from agentvault_registry.crud.crud_enforcement import DEFAULT_POLICY_JSON
from agentvault_registry.services import frame_policy as fp
from agentvault_registry.services import peer_trust_policy as ptp


class Peer:
    """The two attributes the evaluator reads, and nothing else."""
    def __init__(self, interactions, discount):
        self.total_interactions = interactions
        self.bayesian_discount = discount


def policy(**overrides):
    row = {"peer_trust": dict(overrides)} if overrides else {}
    return fp.ResolvedPolicy(doc=fp.resolve(row), version=1 if row else 0,
                             source="amended" if row else "factory_default",
                             _row_json=row or None)


# ---------------------------------------------------------------------------
# The shipped posture is inert
# ---------------------------------------------------------------------------

def test_default_mode_is_observe_not_enforce():
    """Money-adjacent, so fail-open until the frame opts in — exactly like
    ENFORCEMENT_SLASH_MODE. A roll must refuse nothing."""
    assert DEFAULT_POLICY_JSON["peer_trust"]["mode"] == "observe"


def test_in_observe_a_bad_peer_is_classified_but_nothing_is_enforced():
    v = ptp.evaluate(Peer(40, 0.42), policy())
    assert v.state == ptp.RESTRICTED      # the verdict is real
    assert v.is_actionable is True
    assert v.enforced is False            # and nothing is withheld
    assert "observing" in ptp.describe(v)


def test_mode_off_classifies_nothing():
    v = ptp.evaluate(Peer(40, 0.05), policy(mode="off"))
    assert v.state == ptp.OK and v.enforced is False


# ---------------------------------------------------------------------------
# Evidence before the number — the load-bearing rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,interactions,discount", [
    ("hochiminh", 0, 0.5000),
    ("shenzhen", 0, 0.5000),
    ("lisbon", 5, 0.8571),
    ("amsterdam", 9, 0.9091),
])
def test_live_peers_below_the_evidence_floor_are_unmeasured(name, interactions, discount):
    """0.5000 IS `restrict_below`. Without the evidence gate, the two peers
    nobody has ever transacted with would be the first this frame restricted."""
    v = ptp.evaluate(Peer(interactions, discount), policy(mode="enforce"))
    assert v.state == ptp.UNMEASURED, name
    assert v.is_actionable is False and v.enforced is False
    assert "min_interactions" in (v.threshold_key or "")


def test_the_ghost_at_full_trust_with_no_evidence_is_also_unmeasured():
    """The INACTIVE `ASIA` row carries the COLUMN DEFAULT 1.0, which is a claim
    and not a prior. It must not read as the most trusted peer on the frame."""
    v = ptp.evaluate(Peer(0, 1.0), policy(mode="enforce"))
    assert v.state == ptp.UNMEASURED
    assert "Unmeasured" in ptp.describe(v)


def test_a_measured_peer_above_every_threshold_is_ok():
    """asia: 15 interactions at 0.9412 — the control for the tests above. If
    everything came back UNMEASURED the evidence gate would be a mute button."""
    v = ptp.evaluate(Peer(15, 0.9412), policy(mode="enforce"))
    assert v.state == ptp.OK and v.is_actionable is False
    assert "Trusted" in ptp.describe(v)


# ---------------------------------------------------------------------------
# The ladder, and the control on each rung
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("discount,expected", [
    (0.95, ptp.OK),
    (0.69, ptp.WARN),
    (0.49, ptp.RESTRICTED),
    (0.29, ptp.SUSPENDED),
])
def test_the_ladder(discount, expected):
    assert ptp.evaluate(Peer(40, discount), policy(mode="enforce")).state == expected


def test_a_peer_above_the_line_is_not_refused():
    """THE CONTROL. A gate that refuses everything is not a gate."""
    below = ptp.evaluate(Peer(40, 0.49), policy(mode="enforce"))
    above = ptp.evaluate(Peer(40, 0.51), policy(mode="enforce"))
    assert below.enforced is True
    assert above.enforced is False


def test_the_refusal_names_the_policy_and_the_number():
    """An operator must be able to see WHICH rule and WHICH value did this
    without reading the source."""
    v = ptp.evaluate(Peer(40, 0.42), policy(mode="enforce"))
    assert "peer_trust.restrict_below" in v.reason
    assert "0.42" in v.reason and "40" in v.reason
    assert v.threshold_key == "peer_trust.restrict_below" and v.threshold == 0.50


# ---------------------------------------------------------------------------
# Recovery, without an admin
# ---------------------------------------------------------------------------

def test_recovery_restores_the_capability_with_no_admin_action():
    v = ptp.evaluate(Peer(41, 0.60), policy(mode="enforce"), previous_state=ptp.RESTRICTED)
    assert v.state in (ptp.OK, ptp.WARN)
    assert v.enforced is False


def test_hysteresis_holds_a_peer_hovering_on_the_line():
    """0.52 is above restrict_below (0.50), but a peer already restricted must
    clear it by recover_margin or the capability flaps on and off every pass."""
    held = ptp.evaluate(Peer(41, 0.52), policy(mode="enforce"), previous_state=ptp.RESTRICTED)
    fresh = ptp.evaluate(Peer(41, 0.52), policy(mode="enforce"), previous_state=None)
    assert held.state == ptp.RESTRICTED
    assert fresh.state == ptp.WARN          # the control: hysteresis, not a lower threshold
    assert "recover_margin" in held.reason


def test_hysteresis_releases_once_the_margin_is_cleared():
    v = ptp.evaluate(Peer(41, 0.56), policy(mode="enforce"), previous_state=ptp.RESTRICTED)
    assert v.state != ptp.RESTRICTED


# ---------------------------------------------------------------------------
# The thresholds are the frame's, and validated
# ---------------------------------------------------------------------------

def test_thresholds_are_frame_policy_and_a_frame_can_change_them():
    strict = ptp.evaluate(Peer(40, 0.65), policy(mode="enforce", restrict_below=0.70))
    lax = ptp.evaluate(Peer(40, 0.65), policy(mode="enforce", restrict_below=0.40))
    assert strict.state == ptp.RESTRICTED
    assert lax.state == ptp.WARN


def test_an_out_of_range_threshold_is_refused_by_the_policy_validator():
    """The §FRAMEPOLICY validator is what stops a frame writing a threshold the
    network does not permit; peer_trust is bounded like every other rule."""
    assert fp.validate_document({"peer_trust": {"min_interactions": 99999}})
    assert fp.validate_document({"peer_trust": {"restrict_below": 2.0}})
    assert fp.validate_document({"peer_trust": {"restrict_below": 0.55}}) == []


def test_peer_trust_is_published_on_the_frame_policy_document():
    assert "peer_trust" in DEFAULT_POLICY_JSON
    for key in ("mode", "min_interactions", "warn_below", "restrict_below",
                "suspend_below", "recover_margin"):
        assert key in DEFAULT_POLICY_JSON["peer_trust"]


# ---------------------------------------------------------------------------
# Say what the number means
# ---------------------------------------------------------------------------

def test_describe_never_renders_a_bare_prior_as_distrust():
    """0.500 with no evidence must not read as 'half trusted'."""
    text = ptp.describe(ptp.evaluate(Peer(0, 0.5), policy()))
    assert "Unmeasured" in text
    assert "50%" not in text


def test_describe_carries_the_evidence_count():
    assert "15 interaction(s)" in ptp.describe(ptp.evaluate(Peer(15, 0.94), policy()))


def test_verdict_dict_carries_everything_a_reader_needs():
    d = ptp.evaluate(Peer(40, 0.42), policy(mode="enforce")).to_dict()
    for key in ("state", "reason", "discount", "interactions", "threshold_key",
                "threshold", "mode", "enforced"):
        assert key in d, key
