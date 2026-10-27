"""`_build_tier` must key on the DECLARATION, not on a roster of known names.

§TIERFLAG (2026-09-04). The tier gate used to require membership in a hardcoded
six-name allowlist IN ADDITION to `IS_CENTRAL_REGISTRY=true`, so a sovereign
frame the list had never heard of was silently demoted. Measured on two fresh
sandbox frames: both declared the flag, both had own trust domain / EventStore /
economy / bilateral peer, and both published `tier: sandbox` — because their
REGISTRY_NAME is the DISPLAY name "Sandbox Alpha", which the `"sandbox" in name`
fallback caught. Five federation tests read that tier and failed. The tier was
wrong, not the tests.

Same class as `KNOWN_TASKS` in §VITALS and the frame map in the §MONEY-NS split
script: a hand-maintained roster is confidently wrong the first time reality
adds a member. The regression test below is the "Sandbox Alpha" case, because
that is the exact string that made a correct declaration lose to a substring.
"""
import importlib

import pytest


def _tier(monkeypatch, *, registry_name: str, central: str | None):
    """Re-evaluate _build_tier() under a given name + flag."""
    from agentvault_registry.services import registry_card_builder as rcb
    monkeypatch.setattr(rcb.settings, "REGISTRY_NAME", registry_name, raising=False)
    if central is None:
        monkeypatch.delenv("IS_CENTRAL_REGISTRY", raising=False)
    else:
        monkeypatch.setenv("IS_CENTRAL_REGISTRY", central)
    monkeypatch.delenv("STANDALONE_MODE", raising=False)
    return rcb._build_tier()


@pytest.mark.parametrize("name", [
    "Sandbox Alpha",      # ← the regression: display name containing "sandbox"
    "Sandbox Beta",
    "sbx-alpha",
    "registry-a",
    "frame-b",
    "frame-c",
    "a-frame-nobody-has-named-yet",
])
def test_declared_central_registry_is_a_sovereign_mainframe(monkeypatch, name):
    """IS_CENTRAL_REGISTRY=true IS the declaration — no allowlist may override it."""
    assert _tier(monkeypatch, registry_name=name, central="true") == "sovereign-mainframe"


@pytest.mark.parametrize("name,expected", [
    ("registry-test", "sandbox"),
    ("registry-test-b", "sandbox"),
    ("some-test-stack", "sandbox"),
    ("sandbox-fixture", "sandbox"),
    ("op-london", "cloud-operator"),
    ("cloud-op-op-berlin", "cloud-operator"),
    ("frame-d", "regional-mainframe"),
])
def test_undeclared_nodes_keep_their_substring_fallbacks(monkeypatch, name, expected):
    """Without the flag, the legacy name heuristics still decide — unchanged."""
    assert _tier(monkeypatch, registry_name=name, central=None) == expected


def test_no_operator_can_be_promoted_by_a_name(monkeypatch):
    """The control: a cloud-op name with the flag ABSENT must never be sovereign.

    This is what makes the test above meaningful — the live census showed the
    flag unset on all 13 cloud-ops, so keying on it cannot promote an operator.
    If someone later sets it on an op, that is a deliberate act, and this test
    documents that the NAME alone never does it.
    """
    assert _tier(monkeypatch, registry_name="cloud-op-op-london", central="false") == "cloud-operator"
    assert _tier(monkeypatch, registry_name="cloud-op-op-london", central=None) == "cloud-operator"


@pytest.mark.parametrize("name", [
    # ⚠ These are REGISTRY_NAME values (the container-style name), NOT the
    # published `identity.registry_name`. On a cloud-op the two differ:
    # REGISTRY_NAME is `cloud-op-qatest16` and the card publishes `qatest16`
    # from REGISTRY_FEDERATION_NAME (see `_build_identity_block`). `_build_tier`
    # reads the former. My first draft of this test passed the published name
    # and failed — the parameter was wrong, not the function.
    "cloud-op-qatest16",        # ← the live regression: a real Frame-A operator
    "cloud-op-sandboxalpha",
    "cloud-op-sandboxdelta",
    "op-test-one",
])
def test_an_operator_is_an_operator_whatever_its_name_contains(monkeypatch, name):
    """Being an operator is STRUCTURAL; a substring must not outrank it.

    Measured live 2026-09-04: `qatest16`, a Frame-A cloud operator, published
    `tier: sandbox` in its SIGNED registry card because the `"test" in name`
    fallback was evaluated BEFORE the operator check. `op-berlin` and
    `sbxalphaop` — structurally identical nodes — said `cloud-operator`. The
    only difference was four letters in a free-text name.
    """
    assert _tier(monkeypatch, registry_name=name, central=None) == "cloud-operator"
