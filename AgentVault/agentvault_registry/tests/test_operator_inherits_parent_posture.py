import pathlib
"""§BATCH5 — a provisioned operator inherits its parent frame's posture; canaries follow the parent; the console knob is written;
the provisioning seed comes from the network profile (both rails)."""
import inspect, io, pathlib
from agentvault_registry.services import cloud_provisioner as cp

import agentvault_registry as _pkg  # importable package, not a sibling src/ (CI mounts tests beside /app/src)
SRC = pathlib.Path(_pkg.__file__).resolve().parent


def test_inherit_writes_only_what_the_parent_carries(monkeypatch):
    for k in cp.PARENT_POSTURE_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("REPUTATION_BOND_MODE", "enforce"); monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "enforce"); monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", "false")
    buf = io.StringIO(); written = cp._inherit_parent_posture(buf)
    assert set(written) == {"REPUTATION_BOND_MODE", "ENFORCEMENT_PROPAGATION_MODE", "TOKEN_BRIDGE_ENABLED"}
    assert "REPUTATION_BOND_MODE=enforce\n" in buf.getvalue() and "TOKEN_BRIDGE_ENABLED=false\n" in buf.getvalue()
    assert "CANARY_ENABLED" not in buf.getvalue(), "the canary flags are written by their own block"


def test_canaries_follow_the_parent_with_the_historical_default(monkeypatch):
    monkeypatch.delenv("CANARY_ENABLED", raising=False)
    assert cp._parent_or("CANARY_ENABLED", "true") == "true", "registry-a's operators keep today's behaviour"
    monkeypatch.setenv("CANARY_ENABLED", "false")
    assert cp._parent_or("CANARY_ENABLED", "true") == "false", "a fresh frame with canaries off hands its operators the same"
    src = inspect.getsource(cp)
    assert 'f"{_ck}={_parent_or(_ck, \'true\')}' in src and 'f.write(f"CANARY_ENABLED=true\\n")' not in src


def _getenv_calls_for(source: str, key: str) -> int:
    import ast as _ast
    n = 0
    for node in _ast.walk(_ast.parse(source)):
        if isinstance(node, _ast.Call):
            f = node.func
            name = f.attr if isinstance(f, _ast.Attribute) else getattr(f, "id", "")
            if name == "getenv" and node.args and isinstance(node.args[0], _ast.Constant) and node.args[0].value == key:
                n += 1
    return n

def test_console_knob_and_profile_seed_on_both_rails():
    src = inspect.getsource(cp)
    # §HELLOFRAME lane 6 (2026-09-18): the console URL is derived from ONE rule (operator_public_urls) rather
    # than a literal naming the network's own suffix; the knob is still written on the provisioning rail
    assert "PUBLIC_UI_URL={_public['PUBLIC_UI_URL']}" in src and "operator_public_urls(safe=safe" in src
    for rel in ("routers/cloud_operators.py", "routers/operator_self_service.py"):
        t = (SRC / rel).read_text(encoding="utf-8")
        assert '_money_knob("OPERATOR_PROVISION_FUNDING_AVT", "100000")' in t, rel
        # ABSENCE is checked on the AST, never on the text: a comment naming the retired call
        # is documentation, not a call (the PART 1 "source-reading gate finds its own docs" class).
        assert _getenv_calls_for(t, "OPERATOR_PROVISION_FUNDING_AVT") == 0, rel


def test_batch9_authority_and_venue_posture_is_inherited(monkeypatch):
    """§BATCH9: the fresh operators were born without IRONKEY (AGENT_RBAC_MODE unset = off). The authority pair,
    spawn/anchor/inline-SVID, guild, contracts and the venue flags travel from the parent — and the RBAC pair
    travels TOGETHER (PART 14: never flip one alone)."""
    import io
    from agentvault_registry.services import cloud_provisioner as cp
    for k in ("AGENT_RBAC_MODE", "AGENT_DELEGATION_MODE", "AGENT_SPAWN_ENABLED", "SPAWN_WALLET_ANCHOR_MODE",
              "IRONHAND_INLINE_SVID_ENABLED", "GUILD_ENABLED", "CONTRACTS_V2_ENABLED", "EXCHANGE_ENABLED", "JURISDICTION_MODE"):
        assert k in cp.PARENT_POSTURE_KEYS, k
    assert cp.PARENT_POSTURE_KEYS.index("AGENT_DELEGATION_MODE") == cp.PARENT_POSTURE_KEYS.index("AGENT_RBAC_MODE") + 1
    for k in cp.PARENT_POSTURE_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce"); monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    monkeypatch.setenv("EXCHANGE_ENABLED", "true")
    buf = io.StringIO(); written = cp._inherit_parent_posture(buf)
    assert set(written) == {"AGENT_RBAC_MODE", "AGENT_DELEGATION_MODE", "EXCHANGE_ENABLED"}
    assert "AGENT_RBAC_MODE=enforce\nAGENT_DELEGATION_MODE=enforce\n" in buf.getvalue()


def test_the_capability_circuit_breaker_travels_with_the_ironkey_posture(monkeypatch):
    """§DOCSFIX CB-222 (2026-10-16): the IRONKEY posture travelled (the RBAC pair, inline SVIDs) without its circuit
    breaker, so an operator under a kit frame (breaker on) ran with it off unless someone set it by hand."""
    import io
    from agentvault_registry.services import cloud_provisioner as cp
    for k in cp.PARENT_POSTURE_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENT_RBAC_MODE", "enforce"); monkeypatch.setenv("AGENT_DELEGATION_MODE", "enforce")
    monkeypatch.setenv("CAPABILITY_CIRCUIT_BREAKER_ENABLED", "true")
    buf = io.StringIO(); written = cp._inherit_parent_posture(buf)
    assert "CAPABILITY_CIRCUIT_BREAKER_ENABLED" in written
    assert "CAPABILITY_CIRCUIT_BREAKER_ENABLED=true\n" in buf.getvalue()


def test_the_frames_governance_binds_its_new_operators(monkeypatch):
    """§DOCSFIX CB-236 (2026-10-16): services/env_catalog.py keeps the governance switches frame-scoped ("The frame's
    governance binds its operators") and refuses them as an applicant's choice, while provisioning never wrote them:
    a new operator under a member-mode frame voted by locked units, with no ballots, no commons and no presence
    check. They travel from the frame now, the commons budget cap with the commons."""
    import io
    from agentvault_registry.services import cloud_provisioner as cp
    frame = {"GOVERNANCE_WEIGHT_MODE": "member", "GOVERNANCE_PRESENCE_MODE": "conditional",
             "FEDERATION_BALLOT_MODE": "on", "COMMONS_ENABLED": "true", "COMMONS_MAX_BUDGET": "100"}
    for k in cp.PARENT_POSTURE_KEYS:
        monkeypatch.delenv(k, raising=False)
    for k, v in frame.items():
        monkeypatch.setenv(k, v)
    buf = io.StringIO(); written = cp._inherit_parent_posture(buf)
    assert set(written) == set(frame), written
    for k, v in frame.items():
        assert f"{k}={v}\n" in buf.getvalue(), k
