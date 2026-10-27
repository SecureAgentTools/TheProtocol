"""§MCPTEST30 (V0550): a tool its target has switched off is held to the refusal its switch documents.

A registry can switch surfaces off: §BAFIN's STAKING_ENABLED, STAKING_REWARDS_ENABLED and AGORA_DISTRIBUTIONS_ENABLED
(EU and ASIA run rewards and distributions off) and §MEMBERSHIP's GOVERNANCE_WEIGHT_MODE=member (the sandbox's next
roll, with STAKING_ENABLED=false). /api/v1/public/registry-config says which. Until V0550 the tester asked every target
the same question, so a switched-off stake read as a broken tool where a contract held it to success, and as a pass
that measured nothing where a lifecycle asked "any". A run now reads its target's config once (`use_target`), and a
switched-off tool is held to its switch: a refusal with the documented status whose body names the switch's code word.
A 2xx is a finding (the switch did not hold), and so is any other refusal (the row would measure something else).

The map is checked against the code by tests/test_mcp_switches.py: every tool whose route carries a switch dependency
(read by the request survey, class SWITCHED) is in it, nothing else is, and each inline switch is still in its handler.
A target that reports no switch (an image before §BAFIN) switches nothing: the run reads exactly as before.

The state is a ContextVar: each flow runs in its own request task, so the frame's run and an operator's run never read
each other's switches.
"""
from __future__ import annotations

import contextvars
import json
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class Switch:
    key: str              # the registry-config key that reports the switch
    off_when: Any         # the value of that key that switches the tool off
    words: Tuple[str, ...]  # the refusal's code word (one of these begins the detail or names the error)
    status: int           # the status the switch refuses with
    where: str            # the dependency that applies it, or "inline: <module.function>"

    def label(self) -> str:
        v = self.off_when
        return f"{self.key}={str(v).lower() if isinstance(v, bool) else v}"


STAKING_OFF = Switch("staking_enabled", False, ("staking_disabled",), 403, "require_staking_enabled")
# rewards are off wherever staking is: the gate then names staking itself (core/staking_gate.require_staking_rewards_enabled)
REWARDS_OFF = Switch("staking_rewards_enabled", False, ("staking_rewards_disabled", "staking_disabled"), 403,
                     "require_staking_rewards_enabled")
AGORA_DISTRIBUTIONS_OFF = Switch("agora_distributions_enabled", False, ("agora_distributions_disabled",), 403,
                                 "inline: exchange_service.declare_dividend")
# §MCPTEST30 (V0555): with FEDERATION_BALLOT_MODE=on (§MEMBERSHIP D2, the sandbox from V0555's roll) the same handler
# refuses EVERY agent's federation vote 409 registry_ballots, before the member check: registries cast ballots there.
# registry-config does not report the ballot mode, so the member switch takes either word (agentvault2-33, 2026-10-03)
MEMBER_FEDERATION_VOTE = Switch("governance_weight_mode", "member", ("federation_ballot_pending", "registry_ballots"), 409,
                                "inline: governance.federation_vote")
# §MEMBERSHIP phase B (V0551): every commons route refuses where COMMONS_ENABLED is off (the read routes in the router,
# every write in its service function: services/commons.require_enabled); registry-config reports commons_enabled
COMMONS_OFF = Switch("commons_enabled", False, ("commons_disabled",), 403, "inline: commons.require_enabled")
# D8 (core/legacy_surfaces.py): a retired legacy surface is not mounted, so its routes answer FastAPI's plain 404 "Not
# Found"; registry-config reports token_bridge_enabled. The fresh frame's template retires the bridge, and the first
# nightly pair on the current image (nt261008, 2026-10-08) read the three bridge rows' 404s as broken contracts.
BRIDGE_OFF = Switch("token_bridge_enabled", False, ("Not Found",), 404,
                    "unmounted: main.create_app mounts routers/token_bridge.py only where TOKEN_BRIDGE_ENABLED is on")

SWITCHED_TOOLS: Dict[str, Switch] = {
    "theprotocol_lockUnits": STAKING_OFF,
    "theprotocol_tegLockDirect": STAKING_OFF,
    "theprotocol_claimLockPayouts": REWARDS_OFF,
    "theprotocol_estimateMyLockPayouts": REWARDS_OFF,
    "theprotocol_updatePayoutRelock": REWARDS_OFF,
    "theprotocol_triggerLockPayoutRun": REWARDS_OFF,
    "theprotocol_claimTegPayouts": REWARDS_OFF,
    "theprotocol_declareAgoraDistribution": AGORA_DISTRIBUTIONS_OFF,
    "theprotocol_federationVoteProposal": MEMBER_FEDERATION_VOTE,
    **{f"theprotocol_{n}": COMMONS_OFF for n in (
        "getCommonsSeasons", "getCommonsSeason", "getMyCommonsSeason", "submitCommonsWork", "castCommonsBallot",
        "adminCommonsOpenSeason", "adminCommonsCloseSeason", "adminCommonsStrikeSubmission", "adminCommonsPaySeason",
        "adminCommonsWriteOffAward", "adminCommonsCancelSeason")},
    **{f"theprotocol_{n}": BRIDGE_OFF for n in (
        "bridgeTransfer", "bridgeIssueWrapped", "bridgeRedeem", "bridgeUnlock", "getBridgeStatus")},
}

# the route dependencies the request survey reports as SWITCHED, with the config key each one follows
DEPENDENCY_KEYS: Dict[str, str] = {"require_staking_enabled": "staking_enabled",
                                   "require_staking_rewards_enabled": "staking_rewards_enabled"}

KEYS: Tuple[str, ...] = ("staking_enabled", "staking_rewards_enabled", "agora_distributions_enabled",
                         "governance_weight_mode", "governance_presence_mode", "commons_enabled",
                         "token_bridge_enabled")

_TARGET: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("mcp_tester_target_switches",
                                                                                     default=None)


def read_switches(config: Any) -> Dict[str, Any]:
    """The switch keys a registry-config answer carries; the keys it does not carry are left out (never guessed)."""
    if not isinstance(config, dict):
        return {}
    return {k: config[k] for k in KEYS if k in config}


def use_target(config: Any) -> Dict[str, Any]:
    """Hold this run to its target's switches; returns what was read (the run records it in flow_values)."""
    switches = read_switches(config)
    _TARGET.set(switches)
    return switches


def current() -> Dict[str, Any]:
    return dict(_TARGET.get() or {})


def switched_off(tool: str) -> Optional[Switch]:
    """The switch that has turned this tool off on the run's target, or None (no switch, or not off, or not reported)."""
    sw = SWITCHED_TOOLS.get(tool)
    target = _TARGET.get()
    if sw is None or not target or sw.key not in target:
        return None
    return sw if target[sw.key] == sw.off_when else None


def answer_text(inner: Any, extra: str = "") -> str:
    if isinstance(inner, dict):
        t = inner.get("_text")
        text = t if isinstance(t, str) else json.dumps(inner, default=str)[:2000]
    else:
        text = str(inner or "")
    return f"{text} {extra}".strip()


def judge(tool: str, sw: Switch, code: int, text: str) -> Tuple[bool, Optional[str]]:
    """(healthy, fail_reason) for an answer from a tool its target switched off."""
    short = tool.replace("theprotocol_", "")
    if 200 <= code < 300:
        return False, (f"BUG-FIND: {short} answered HTTP {code} though this target reports {sw.label()}: the switch "
                       f"did not hold ({sw.where})")
    named = any(w in (text or "") for w in sw.words)
    if named and code == sw.status:
        return True, None
    if named:
        return False, (f"{short} is switched off here ({sw.label()}) and named it, but answered HTTP {code}; "
                       f"{sw.where} refuses with {sw.status}")
    return False, (f"{short} is switched off here ({sw.label()}): expected its refusal ({sw.status} {sw.words[0]}), "
                   f"got HTTP {code}: {(text or '')[:160]}")


def refusal_contract(base: Any, sw: Switch) -> Any:
    """The tool's contract as its switch holds it: the documented refusal, nothing else asserted (no shape, no event,
    no side effect: a refusal moves nothing). A contract that says do not call keeps saying it."""
    if getattr(base, "skip_reason", None):
        return base
    note = (f"§MCPTEST30 (V0550): switched off on this target ({sw.label()}, {sw.where}); held to its refusal. "
            + (base.notes or ""))
    return replace(base, expect_status="error_4xx", expect_error_message_contains=list(sw.words),
                   expect_keys=[], expect_types={}, expect_error_keys=[], side_effect_assert=None, expect_events=[],
                   expect_idempotent=False, expect_consistency_within=None, consistency_check=None,
                   success_path_unmeasured=None, notes=note.strip())
