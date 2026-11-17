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
    # V0666: a refusal that comes FIRST on a target that is also something else (a registry that does not govern code answers the governing
    # refusal before it looks at this switch): (status, words) pairs that are as healthy as the switch's own
    also: Tuple[Tuple[int, Tuple[str, ...]], ...] = ()

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
# V0664 (session-tester, session-lead seq 4287): the migration template library refuses every route 503 where
# WORKFLOW_TEMPLATES_ENABLED is off (routers/workflow_templates._require_enabled, called by each of its 13 routes);
# registry-config reports workflow_templates_enabled. Production's posture ran it off until V0664's card, and the pair
# proof on nt261115x1 read that 503 as 2 failed contracts and 4 false BUG-FINDs
WORKFLOW_TEMPLATES_OFF = Switch("workflow_templates_enabled", False, ("Workflow templates are switched off",), 503,
                                "inline: workflow_templates._require_enabled")
# V0666 the games switch (core/games.py, arena/mount.py): where GAMES_ENABLED is off the registry mounts no game route and
# neither lists nor dispatches a game tool (mcp/tool_switches.NEEDS_GAMES), so there is no refusal to hold a game tool to:
# its row is NOT MEASURED on that target (never passed, never failed). registry-config reports games_enabled.
GAMES_OFF = Switch("games_enabled", False, ("games are off on this registry",), 0, "inline: arena/mount.mount_games")
UNMEASURED_WHEN_OFF: Dict[str, Switch] = {f"theprotocol_{n}": GAMES_OFF for n in (
    "listArenaMatches", "getArenaMatch", "getArenaMatchBets", "getArenaMatchMap", "getArenaLeaderboard",
    "getArenaAgentStats", "createArenaMatch")}

# V0666 D1: an organization's code distributions (release lines, not AGORA payouts): off, every route answers 404
# (routers/code_distributions._switch, a router dependency; routers/code_changes._line_switch on the line's three
# routes and on a propose that names a line). No §BAFIN dependency carries it, so the survey does not see it: the
# routes' 404 is pinned by tests/test_code_distributions_v0666.py
CODE_DISTRIBUTIONS_OFF = Switch("code_distributions_enabled", False, ("Not Found",), 404,
                                "inline: code_distributions._switch, code_changes._line_switch")
# ... except PROPOSE: CodeChangeFlow.propose asks the governing gate (services/code_authority) BEFORE the lines switch, so on a registry that does not govern code (the
# pair's posture: distributions off, code governed on EU) it answers 403 "Code changes are governed on <name>; open them there" first (session-release's pair proof nt261116x6).
# Every other step asks the switch first (the vote, the veto, the go, the routes), and keeps the one sentence
CODE_DISTRIBUTIONS_OFF_PROPOSE = replace(CODE_DISTRIBUTIONS_OFF, also=((403, ("Code changes are governed on",)),))
# V0651 (p): the token bridge is retired: its five tools left the catalogs and every /api/v1/bridge/*
# route answers 410 whatever TOKEN_BRIDGE_ENABLED says, so the switch row that read its 404 went with it

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
    **{f"theprotocol_{n}": WORKFLOW_TEMPLATES_OFF for n in (
        "listWorkflowTemplates", "getWorkflowTemplate", "getWorkflowTemplateVersion", "listMyWorkflowTemplates",
        "createWorkflowTemplate", "publishWorkflowTemplateVersion", "forkWorkflowTemplate", "purchaseWorkflowTemplate",
        "instantiateWorkflowTemplate")},
    **{f"theprotocol_{n}": CODE_DISTRIBUTIONS_OFF for n in (
        "getCodeDistribution", "listOrganizationCodeDistributions", "voteCodeDistributionChange")},
    "theprotocol_proposeCodeDistributionChange": CODE_DISTRIBUTIONS_OFF_PROPOSE,
}

# the route dependencies the request survey reports as SWITCHED, with the config key each one follows
DEPENDENCY_KEYS: Dict[str, str] = {"require_staking_enabled": "staking_enabled",
                                   "require_staking_rewards_enabled": "staking_rewards_enabled"}

KEYS: Tuple[str, ...] = ("staking_enabled", "staking_rewards_enabled", "agora_distributions_enabled",
                         "governance_weight_mode", "governance_presence_mode", "commons_enabled",
                         "token_bridge_enabled", "workflow_templates_enabled", "games_enabled",
                         "code_distributions_enabled")

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


def unmeasured_off(tool: str) -> Optional[str]:
    """V0666: why a tool is NOT MEASURED on the run's target (a game tool where games_enabled is false), or None. A target
    that does not report the key (an image before V0666) has its games on: None."""
    sw = UNMEASURED_WHEN_OFF.get(tool)
    target = _TARGET.get()
    if sw is None or not target or target.get(sw.key) != sw.off_when:
        return None
    return f"NOT MEASURED: the games are off on this target ({sw.label()}): no game route, no game tool"


def probe_skip(tool: str) -> Optional[str]:
    """V0664: why a probe (hygiene, range) does not ask a switched-off tool, or None. On a target that switched the
    tool off, every hostile value meets the switch's refusal first, so the probe would measure the switch and report
    it as the route's own answer (the nt261115x1 pair proof: 4 false BUG-FINDs). The switch itself is measured by the
    tool's own row. V0666: a game tool where the target's games are off is NOT MEASURED the same way (the switch refuses
    it by name, -32601, so every hostile value would measure the switch: V0666's pair proof, two false BUG-FINDs)."""
    off = unmeasured_off(tool)
    if off:
        return off
    sw = switched_off(tool)
    if sw is None:
        return None
    return (f"NOT MEASURED: switched off on this target ({sw.label()}): every value would meet the switch's refusal "
            f"({sw.status}), not the route; the tool's own row measures the switch")


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
    if any(code == st and any(w in (text or "") for w in ws) for st, ws in sw.also):
        return True, None                              # the refusal that comes first on this target (see Switch.also)
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
    # V0664: a switch that refuses with a 5xx (the template library's 503) is held to that, not to a 4xx
    return replace(base, expect_status="error_5xx" if sw.status >= 500 else "error_4xx",
                   expect_error_message_contains=list(sw.words) + [w for _st, ws in sw.also for w in ws],
                   expect_keys=[], expect_types={}, expect_error_keys=[], side_effect_assert=None, expect_events=[],
                   expect_idempotent=False, expect_consistency_within=None, consistency_check=None,
                   success_path_unmeasured=None, notes=note.strip())
