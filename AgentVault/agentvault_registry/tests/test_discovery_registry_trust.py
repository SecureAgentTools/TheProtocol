"""§DISCOTRUST — the host registry's trust verdict reaches a discovery caller, and only a known one.

Two properties, and the second one is the one that needs a test:

1. `RegistryHealthProfile` DECLARES `trust`. A pydantic response_model drops undeclared fields
   silently, which is exactly how seven policy fields reached nobody from the governance tally
   earlier in this program. A field that is assigned but not declared is a field that does not
   exist on the wire, and nothing else in the stack complains.

2. The verdict is ABSENT for an anonymous caller. It is this frame's own opinion of a peer,
   formed from settlements this frame witnessed; serving it to the whole internet would make
   this registry a credit bureau on its peers, which is the thing the peer-trust design
   deliberately refuses. A member asking "should I deal with this provider" is asking this
   frame for its opinion, and that is what the field is for.

The control matters here: a test that only asserts presence-when-authenticated passes just as
loudly against a build that serves the verdict to everybody.
"""
from agentvault_registry.routers.registry_health import RegistryHealthProfile


def test_profile_declares_trust_or_it_never_reaches_the_wire():
    assert "trust" in RegistryHealthProfile.model_fields, (
        "RegistryHealthProfile must DECLARE trust; response_model drops undeclared fields silently"
    )
    f = RegistryHealthProfile.model_fields["trust"]
    assert f.default is None, "trust must default to None — absent is not 'trusted'"


def _profile(**kw):
    base = dict(
        registry_id=1, registry_name="eu", registry_url="https://eu:8443", registry_did=None,
        federation_status="unknown", compliance_score=0.0, policy_drift_events=0,
        quarantine_events=[], quarantine_reason=None, quarantine_since=None,
        admitted_at=None, last_polled_at=None,
    )
    base.update(kw)
    return RegistryHealthProfile(**base)


def test_trust_is_none_unless_set():
    """The anonymous shape. The handler only assigns when a viewer resolved."""
    p = _profile()
    assert p.trust is None
    assert p.model_dump().get("trust") is None


def test_trust_round_trips_when_set():
    """The authenticated shape: whatever the service said survives serialisation intact."""
    verdict = {"state": "unmeasured", "label": "Unmeasured — 5 settled interaction(s), not enough to judge",
               "interactions": 5, "enforced": False}
    p = _profile(trust=verdict)
    assert p.model_dump()["trust"] == verdict


def test_handler_gates_the_attachment_on_a_viewer():
    """Pin the GUARD, not just the shape.

    Read the handler's source and require that the trust attachment sits under a viewer check.
    A shape test cannot see an `if` that was deleted, and deleting it is precisely the change
    that would turn this frame into a public scoreboard on its peers.
    """
    import inspect
    from agentvault_registry.routers import registry_health as rh
    src = inspect.getsource(rh.list_federated_registries)
    assert "viewer" in src, "the handler must take an optional viewer"
    i_guard = src.find("if viewer is not None")
    i_attach = src.find("profile.trust")
    assert i_guard != -1, "the trust attachment must be guarded on an authenticated viewer"
    assert i_attach > i_guard, "profile.trust must be assigned INSIDE the viewer guard"


def test_one_trust_implementation_not_two():
    """The topology router must not hold a second copy of the verdict logic.

    §TRUSTPOLICY's own finding was a third trust implementation with cut-offs belonging to
    nobody's policy. The router is allowed to have a thin delegate and nothing more.
    """
    import inspect
    from agentvault_registry.routers import federation_topology as ft
    src = inspect.getsource(ft._peer_trust_block)
    assert "ptp.trust_block" in src, "_peer_trust_block must delegate to the service"
    for reimplemented in ("warn_below", "restrict_below", "suspend_below", "min_interactions"):
        assert reimplemented not in src, f"{reimplemented} threshold re-implemented in the router"
