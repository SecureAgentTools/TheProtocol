"""The configuration catalog: what a registry can choose to run, in the words the application forms show (§FESUITE
V0595, his word 2026-10-11: "we need env setup in the application forms. but we need to map all the flags ... the env
flips that are frame exclusive should be still displayed for operators but greyed out and not chooseable").

ONE source for the frame request's switch board (the Frame Commander), the operator application's configuration step
and the provisioner that writes an operator's env. Before this the Frame Commander's 23 switches lived only in the
console (services/api/frameRequests.ts) and no server code turned a chosen key into an env flag: the choices were
collected and nothing applied them, and an operator application had no configuration at all.

Each entry is a friendly key (the Frame Commander's keys kept), the env flag its options write, and its SCOPE:
  - "frame": frame-exclusive. Shown to an operator greyed, with the frame's own value, and never accepted from an
    operator application (money and regulated policy, the authority posture, the frame's operations);
  - "operator": what an operator runs. An operator starts from its frame's value (the inheritance
    cloud_provisioner.PARENT_POSTURE_KEYS already does) and may choose another option.
The full map of every environment name the registry reads (954 on 2026-10-11) is sessionlogs2026/FLAGMAP_2026-10-11.md;
this file holds the switches a person chooses, not the internals.

`writes` names, per option, the env lines it means; the FIRST name is the entry's primary flag, the one this
registry's current option is read from. A value the catalog does not write is reported as "unknown", never guessed,
and an unset flag is the option `unset_means` names (the code's own default).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

TRUE, FALSE = "true", "false"


@dataclass(frozen=True)
class Entry:
    key: str
    group: str
    label: str
    hint: str
    options: Tuple[str, ...]
    default: str
    scope: str                                   # "frame" | "operator"
    writes: Dict[str, Dict[str, str]]            # option -> {ENV: value}; the first ENV of any option is the primary
    unset_means: str                             # the option an unset primary flag is (the code's default)
    reason: str = ""                             # why an operator cannot choose it (frame scope), shown greyed
    pair: Optional[str] = None                   # an entry that always takes the same option (PART 14)

    @property
    def primary(self) -> str:
        return next(iter(self.writes[self.options[0]]))


def _yes_no(env: str, extra_yes: Optional[Dict[str, str]] = None, extra_no: Optional[Dict[str, str]] = None):
    return {"yes": {env: TRUE, **(extra_yes or {})}, "no": {env: FALSE, **(extra_no or {})}}


def _modes(env: str, modes: Tuple[str, ...]) -> Dict[str, Dict[str, str]]:
    return {m: {env: m} for m in modes}


_ZKP = ("ZKP_PHASE_1_ENABLED", "ZKP_PHASE_2_ENABLED", "ZKP_PHASE_3_ENABLED", "ZKP_PHASE_4_ENABLED", "ZKP_PHASE_5_ENABLED")
_FRAME_MONEY = "Money policy is the frame's: its operators follow it."
_FRAME_AUTHORITY = "The frame's authority posture binds its operators."
_FRAME_OPS = "Run by the frame for the whole network."

CATALOG: Tuple[Entry, ...] = (
    # ── economy ────────────────────────────────────────────────────────────────────────────────────────────────────────
    Entry("agora_exchange", "economy", "AGORA market",
          "Organisations list points and trade them on a real order book, with launches and distributions.",
          ("yes", "no"), "yes", "operator",
          _yes_no("EXCHANGE_ENABLED", {"EXCHANGE_MARKET_CARD_ENABLED": TRUE, "STOCK_CARD_SYNC_ENABLED": TRUE}), "no"),
    Entry("passport_trading", "economy", "Passport trading",
          "Your members buy on other frames' markets, paid through the currency exchange.",
          ("yes", "no"), "yes", "operator", _yes_no("EXCHANGE_PASSPORT_ENABLED"), "no"),
    Entry("currency_exchange", "economy", "Currency exchange",
          "Swap your unit against other frames’ units. Needs federation.",
          ("yes", "no"), "yes", "frame",
          _yes_no("FX_ENABLED", {"FX_ROUTE_ENABLED": TRUE, "FX_RESERVE_KEEPER_ENABLED": TRUE, "FX_ROUTER_KEEPER_ENABLED": TRUE}),
          "no", reason="The currency pool and its reserves are the frame's."),
    Entry("guild", "economy", "Guild",
          "Work exchange: agents post paid jobs, others bid, money escrowed until the work is verified.",
          ("yes", "no"), "yes", "operator", _yes_no("GUILD_ENABLED"), "no"),
    Entry("contracts", "economy", "Contracts",
          "Milestone contracts with escrowed release.",
          ("yes", "no"), "yes", "operator", _yes_no("CONTRACTS_V2_ENABLED"), "no"),
    Entry("contract_templates", "economy", "Contract templates",
          "A library of reusable contract templates, published by those granted the authority to.",
          ("yes", "no"), "yes", "operator", _yes_no("CONTRACT_TEMPLATES_ENABLED"), "no"),
    Entry("cross_frame_contracts", "economy", "Cross-frame contracts",
          "One contract, two parties on different registries. Needs federation. Shadow records and refuses nothing.",
          ("off", "shadow", "enforce"), "enforce", "operator", _modes("CONTRACTS_XFRAME_MODE", ("off", "shadow", "enforce")), "off"),
    Entry("cosmetics_shop", "economy", "Cosmetics shop",
          "Agent badges and effects bought with your own currency.",
          ("yes", "no"), "yes", "operator", _yes_no("FLARE_LOCAL_PURCHASE_ENABLED"), "no"),
    Entry("fiat_onramp", "economy", "Fiat onramp",
          "Card payments into your currency. Needs your own payment processor account.",
          ("yes", "no"), "no", "frame", _yes_no("FIAT_ONRAMP_ENABLED"), "no",
          reason="A regulated lane: only a frame runs it."),
    Entry("staking", "economy", "Locking units",
          "Members lock points for votes and standing.",
          ("yes", "no"), "no", "frame", _yes_no("STAKING_ENABLED"), "yes", reason=_FRAME_MONEY),
    Entry("staking_rewards", "economy", "Payouts on locked units",
          "A discretionary payout on locked units. Never on where locking is off.",
          ("yes", "no"), "no", "frame", _yes_no("STAKING_REWARDS_ENABLED"), "yes", reason=_FRAME_MONEY),
    Entry("agora_distributions", "economy", "AGORA distributions",
          "Listed organisations pay distributions to their point holders.",
          ("yes", "no"), "no", "frame", _yes_no("AGORA_DISTRIBUTIONS_ENABLED"), "yes", reason=_FRAME_MONEY),
    Entry("genesis_grant", "economy", "Starting grant",
          "A new member's first agent receives a starting grant from the treasury.",
          ("yes", "no"), "yes", "frame", _yes_no("GENESIS_GRANT_ENABLED"), "yes", reason=_FRAME_MONEY),
    Entry("reputation_bond", "economy", "Provider bond",
          "Providing services takes a bond held in escrow. Shadow records and refuses nothing.",
          ("off", "shadow", "enforce"), "enforce", "frame", _modes("REPUTATION_BOND_MODE", ("off", "shadow", "enforce")), "off",
          reason=_FRAME_MONEY),
    # ── agents ─────────────────────────────────────────────────────────────────────────────────────────────────────────
    Entry("agent_permissions", "agents", "Agent permissions",
          "Per-agent roles and spend caps. Shadow decides and logs but denies nothing. Shadow first is the sane order.",
          ("off", "shadow", "enforce"), "shadow", "frame", _modes("AGENT_RBAC_MODE", ("off", "shadow", "enforce")), "off",
          reason=_FRAME_AUTHORITY, pair="delegation"),
    Entry("delegation", "agents", "Delegation",
          "An agent acts for another under narrower limits. Moves together with agent permissions, never on its own.",
          ("off", "shadow", "enforce"), "shadow", "frame", _modes("AGENT_DELEGATION_MODE", ("off", "shadow", "enforce")), "off",
          reason=_FRAME_AUTHORITY, pair="agent_permissions"),
    Entry("xreg_delegation", "agents", "Cross-registry delegation",
          "An agent on someone else’s registry acts under your limits, spending its own wallet.",
          ("yes", "no"), "yes", "operator", _yes_no("AGENT_XREG_DELEGATION_ENABLED"), "no"),
    Entry("agent_mtls", "agents", "Agent mTLS",
          "Short-lived X.509 identities so your agents talk over mutual TLS, including agents on your own hardware.",
          ("yes", "no"), "yes", "operator", _yes_no("IRONHAND_INLINE_SVID_ENABLED"), "no"),
    Entry("liability_card", "agents", "Liability card",
          "A named human underwrites one agent for a declared scope, confirmed from their phone. Shadow records and refuses nothing.",
          ("off", "shadow", "enforce"), "off", "operator", _modes("LIABILITY_MODE", ("off", "shadow", "enforce")), "off"),
    Entry("sub_agent_wallets", "agents", "Sub-agent wallets",
          "A spawned child agent spends its parent’s purse instead of holding its own.",
          ("yes", "no"), "yes", "operator",
          _yes_no("AGENT_SPAWN_ENABLED", {"SPAWN_WALLET_ANCHOR_MODE": "on"}, {"SPAWN_WALLET_ANCHOR_MODE": "off"}), "no"),
    Entry("agent_forge", "agents", "Agent forge",
          "Agents fork and improve other agents, adopted by quorum, with royalties to the ancestor.",
          ("yes", "no"), "no", "operator", _yes_no("FORGE_ENABLED", {"EVALS_ENABLED": TRUE}), "no"),
    Entry("zk_proofs", "agents", "Zero-knowledge proofs",
          "Prove a price, a metered usage, a fee batch or a moderation log meets this registry's policy without revealing the figures behind it.",
          ("yes", "no"), "no", "operator",
          {"yes": {z: TRUE for z in _ZKP}, "no": {z: FALSE for z in _ZKP}}, "yes"),
    # ── access ─────────────────────────────────────────────────────────────────────────────────────────────────────────
    Entry("invite_only", "access", "Invite only",
          "Registration needs a code you mint. Off means open to the internet.",
          ("yes", "no"), "yes", "operator", _yes_no("BETA_INVITE_REQUIRED"), "no"),
    Entry("email_verification", "access", "Email verification",
          "Needs a mail relay. Without one, invite only is what keeps the door shut.",
          ("yes", "no"), "no", "operator", _yes_no("REQUIRE_EMAIL_VERIFICATION"), "yes"),
    Entry("chat", "access", "Chat across registries",
          "Threads between people and agents reach other registries. Chat on this registry is always there.",
          ("yes", "no"), "yes", "operator", _yes_no("CHAT_FEDERATION_ENABLED"), "no"),
    Entry("operator_desk", "access", "Operator desk",
          "The arrangeable dashboard your admins work from.",
          ("yes", "no"), "yes", "operator", _yes_no("COCKPIT_DESK_ENABLED"), "no"),
    Entry("policy_engine", "access", "Policy engine",
          "An OPA sidecar mirrors every authorization decision so you can audit them.",
          ("yes", "no"), "no", "frame", _yes_no("OPA_ENABLED", {"OPA_ENFORCE": FALSE}), "no",
          reason="Its sidecar is set up by the frame for its operators."),
    # ── governance ─────────────────────────────────────────────────────────────────────────────────────────────────────
    Entry("governance_weight", "governance", "Votes by",
          "Member: one member, one vote. Lock: weight by locked points.",
          ("member", "lock"), "member", "frame", _modes("GOVERNANCE_WEIGHT_MODE", ("member", "lock")), "lock",
          reason="The frame's governance binds its operators."),
    Entry("federation_ballots", "governance", "Federation ballots",
          "Proposals put to every frame in the federation.",
          ("on", "off"), "on", "frame", _modes("FEDERATION_BALLOT_MODE", ("on", "off")), "off",
          reason="The frame's governance binds its operators."),
    Entry("commons", "governance", "Commons",
          "Seasons of community work paid from a budget the members vote on.",
          ("yes", "no"), "no", "frame", _yes_no("COMMONS_ENABLED"), "no", reason="The frame's governance binds its operators."),
    Entry("jurisdiction", "governance", "Jurisdiction checks",
          "Actions are checked against the frame's declared jurisdiction. Shadow records and refuses nothing.",
          ("off", "shadow", "enforce"), "shadow", "frame", _modes("JURISDICTION_MODE", ("off", "shadow", "enforce")), "off",
          reason="The frame's legal posture binds its operators."),
    # ── operations ─────────────────────────────────────────────────────────────────────────────────────────────────────
    Entry("canaries", "operations", "Canaries",
          "Scheduled synthetic transactions that prove the rails work. They move real currency.",
          ("yes", "no"), "no", "frame",
          _yes_no("CANARY_RUNNER_ENABLED", {"CANARY_JUDGE_ENABLED": TRUE, "CANARY_VALIDATOR_ENABLED": TRUE},
                  {"CANARY_JUDGE_ENABLED": FALSE, "CANARY_VALIDATOR_ENABLED": FALSE}), "no", reason=_FRAME_OPS),
    Entry("simulation", "operations", "Simulation",
          "Market simulator driving synthetic load and trust scoring.",
          ("yes", "no"), "no", "frame", _yes_no("ADMIN_SIMULATION_ENABLED"), "no", reason=_FRAME_OPS),
    Entry("api_test_harness", "operations", "API test harness",
          "Runs the full endpoint suite against your own frame. Fine on a test frame, off anywhere real.",
          ("yes", "no"), "no", "frame", _yes_no("API_TEST_EXECUTION_ENABLED"), "no", reason=_FRAME_OPS),
)

BY_KEY: Dict[str, Entry] = {e.key: e for e in CATALOG}
GROUPS: Tuple[str, ...] = ("economy", "agents", "access", "governance", "operations")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _norm(v: str) -> str:
    """A switch word as the catalog writes it: true / false for the boolean spellings, the lowercase word otherwise."""
    s = (v or "").strip().lower()
    if s in _TRUE and s != "on":
        return TRUE
    if s in _FALSE and s != "off":
        return FALSE
    return s


def current_option(entry: Entry, env: Mapping[str, str]) -> Tuple[Optional[str], str]:
    """This registry's option for one entry, read from its PRIMARY flag: (option, how) where how is "set" (the flag is
    set to a value the catalog writes), "default" (unset: the code's default) or "unknown" (set to anything else)."""
    raw = env.get(entry.primary)
    if raw is None or str(raw).strip() == "":
        return entry.unset_means, "default"
    got = _norm(str(raw))
    for opt in entry.options:
        want = entry.writes[opt][entry.primary]
        if _norm(want) == got or (want == "on" and got == TRUE) or (want == "off" and got == FALSE):
            return opt, "set"
    return None, "unknown"


def validate_choices(choices: Mapping[str, str], applicant: str) -> Tuple[Dict[str, str], List[str]]:
    """Clean choices and the reasons for every one refused. `applicant` is "operator" (frame-scope keys refused: the
    frame decides them) or "frame" (every key). Paired entries must agree; a pair half alone takes its partner along."""
    clean: Dict[str, str] = {}
    errors: List[str] = []
    for k, v in (choices or {}).items():
        e = BY_KEY.get(str(k))
        if e is None:
            errors.append(f"{k}: not a setting this registry knows")
            continue
        if applicant == "operator" and e.scope == "frame":
            errors.append(f"{k}: set by the frame, not by an operator ({e.reason or 'frame-exclusive'})")
            continue
        val = str(v).strip().lower()
        if val not in e.options:
            errors.append(f"{k}: '{v}' is not one of {', '.join(e.options)}")
            continue
        clean[e.key] = val
    for k in list(clean):
        p = BY_KEY[k].pair
        if p and p in clean and clean[p] != clean[k]:
            errors.append(f"{k} and {p} move together; they were given {clean[k]} and {clean[p]}")
        elif p and p not in clean:
            clean[p] = clean[k]
    return clean, errors


def env_lines(choices: Mapping[str, str]) -> List[Tuple[str, str]]:
    """The env lines validated choices mean, in catalog order, each name once (a later entry never undoes an earlier)."""
    out: Dict[str, str] = {}
    for e in CATALOG:
        opt = choices.get(e.key)
        if opt is None:
            continue
        for name, value in e.writes[opt].items():
            out.setdefault(name, value)
    return list(out.items())


def public_view(env: Mapping[str, str], role: str) -> dict:
    """What GET /public/env-catalog answers: every entry with its options and scope, and this registry's own option
    (how it was read: set / default / unknown). `role` is this registry's: "frame" or "operator"."""
    entries = []
    for e in CATALOG:
        opt, how = current_option(e, env)
        entries.append({
            "key": e.key, "group": e.group, "label": e.label, "hint": e.hint, "options": list(e.options),
            "default": e.default, "scope": e.scope, "reason": e.reason or None, "pair": e.pair,
            "env": e.primary, "current": opt, "current_source": how,
        })
    return {"catalog_version": 1, "role": role, "groups": list(GROUPS), "entries": entries}
