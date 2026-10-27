"""
services/frame_policy.py — THE frame's policy document: one resolver, one hash.

§FRAMEPOLICY (2026-09-11). This module does not introduce a policy store — it
finishes the one that already exists:

    models.RegistryEnforcementPolicy      one active row, versioned, audited
    crud_enforcement.DEFAULT_POLICY_JSON  the factory default document
    core.base_network_params              LOCKED_PARAMS + BOUNDED_PARAMS
    federation_policy_validator           the admission validator

What it fixes, all of it measured live on 2026-09-11:

  * A frame with NO row runs the factory default, but the signed registry card
    hashed `{}` while `/federation/policy-compliance` hashed the real default —
    ONE frame publishing TWO hashes for ONE policy. `policy_hash()` here is the
    single answer both callers now use.
  * A frame with a PARTIAL row lost every section written after its row.
    registry-a's row is from 2026-04-09 and predates §REPBOND by five months, so
    it carries no `slash_waterfall`; `enforcement_engine.py` survived that only
    by holding a SECOND inline copy of the default (gone since 2026-09-11: the
    engine reads the one default). `resolve()` deep-merges the row ONTO the
    defaults, so a missing section is the documented default and never an
    absence. A stored `null` is "unset" too (§BATCH0911): it keeps the
    default, so the resolved document and `explain()` agree.
  * `explain()` exists because "unset" and "set to the default" are different
    facts and a readout that cannot tell them apart is the §29e class.

⚠ THE ONE RULE THIS MODULE MUST KEEP: a frame whose policy row is absent must
behave EXACTLY as it did before it shipped. Every default here is the value the
live code already used, not the value the document wished for. Where those two
disagreed (the document said one thing and the code did another, for months),
the DEFAULT follows the CODE and the difference is reported, never silently
applied — see `DECLARED_VS_LIVE`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..core.base_network_params import BOUNDED_PARAMS, LOCKED_PARAMS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deprecated key aliases — one rule must have one key
# ---------------------------------------------------------------------------
# M8: the shipped document carried TWO names for the policy-change thresholds.
# `policy_proposal_*` held 20/66 (what routers/governance.py actually did) and
# `policy_change_*` held 33/66 (what nothing did). `policy_change_*` is canonical
# because it matches proposal_type='policy_change' AND the BOUNDED_PARAMS key
# names. The alias is still READ so a frame that wrote the old key keeps its
# meaning; it is never written.
DEPRECATED_ALIASES: Dict[str, str] = {
    "governance.policy_change_quorum_percent": "governance.policy_proposal_quorum_percent",
    "governance.policy_change_pass_percent": "governance.policy_proposal_pass_percent",
    # §BONDFILL-3 (2026-09-11) — THE BOND'S RULES HAD TWO KEYS EACH, AND THE CARD AND THE GATE
    # READ DIFFERENT ONES. The signed card published `enforcement.bond_*` (bounded) while
    # `maturity_thresholds` read `reputation_bond.*` (UNBOUNDED). Measured on EU: the bounded
    # trust key refused 0.05 while the key the gate actually read accepted 0.0005, so a frame could
    # lower its real rule while its card went on publishing the old one. The BOUNDED name is
    # canonical (the M8 precedent: it is the name the network's bounds are written against).
    "enforcement.bond_maturity_min_transactions": "reputation_bond.min_transactions",
    "enforcement.bond_maturity_min_age_days": "reputation_bond.min_age_days",
    "enforcement.reputation_bond_min_avt": "reputation_bond.amount_avt",
}

# A RETIRED key is still ACCEPTED so a frame's existing document stays valid — EU's amended row
# carries both of these — but nothing reads it and it is never written. Refusing it would make a
# frame's own policy fail validation on its next governance vote, which is a worse outcome than
# carrying a dead line. Named here so a readout can SAY a value is retired rather than silently
# ignoring it.
RETIRED_PATHS: Dict[str, str] = {
    "enforcement.bond_min_eigentrust_at_maturity":
        "retired §BONDFILL-3: an absolute threshold on a normalised vector is unreachable; "
        "see enforcement.bond_maturity_min_trust_percentile",
    "reputation_bond.min_eigentrust":
        "retired §BONDFILL-3: the unbounded twin of the retired absolute trust gate",
}


# ---------------------------------------------------------------------------
# Policy paths an env var or the network profile OUTRANKS
# ---------------------------------------------------------------------------
# §CARDBOND (2026-09-11). The bond rail reads each of these through a knob (env > network profile >
# this document > default), so on a node where the knob is set, the document's value is not the
# rule. Measured on EU and ASIA: the network profile `lowsupply-2026` charges a 250 bond while the
# signed card published the document's 50 (EU's row carries 50 under both names), and a vote to
# change it would have passed, been stored, and changed nothing. This table is the ONE place the
# pairing is written: `reputation_bond` reads its knob names from it, `explain()` reports the value
# the rail applies for any path here, and a policy_change that would move one is refused.
KNOB_OVERRIDES: Dict[str, str] = {
    "enforcement.reputation_bond_min_avt": "REPUTATION_BOND_AMOUNT",
    "enforcement.bond_maturity_min_transactions": "REPUTATION_BOND_MIN_TRANSACTIONS",
    "enforcement.bond_maturity_min_age_days": "REPUTATION_BOND_MIN_AGE_DAYS",
    "enforcement.bond_maturity_min_trust_percentile": "REPUTATION_BOND_MIN_TRUST_PERCENTILE",
    "enforcement.bond_maturity_min_rated_peers": "REPUTATION_BOND_MIN_RATED_PEERS",
    "enforcement.bond_maturity_releases_percent": "REPUTATION_BOND_MATURITY_RELEASES_PERCENT",
}


def _knob_layer(path: str) -> Optional[Tuple[str, str]]:
    """(knob, "env" | "network_profile") when a knob decides this path on this node, else None."""
    knob = KNOB_OVERRIDES.get(path)
    if not knob:
        return None
    from ..core.network_profile import knob_source
    source = knob_source(knob)
    if source is None:
        return None
    return knob, ("env" if source == "env" else "network_profile")


def _plain_number(value: Any) -> Any:
    """A Decimal the rail applies, as the JSON number the card already publishes (250, not '250')."""
    from decimal import Decimal
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


# ---------------------------------------------------------------------------
# Paths this frame's own code reads. Anything here is a rule the frame OWNS.
# ---------------------------------------------------------------------------
GOVERNED_PATHS: Tuple[str, ...] = (
    "governance.standard_quorum_percent",
    "governance.standard_pass_percent",
    "governance.policy_change_quorum_percent",
    "governance.policy_change_pass_percent",
    "governance.min_stake_to_propose_avt",
    "governance.max_lock_days",
    "governance.flexible_stake_ve_multiplier_max",
)


# Namespaces whose CHILDREN are operator-defined data rather than a fixed set of
# rules: a frame may add a 5th escalation level or a new volume tier. Everything
# outside these must be a key the document actually declares, or a typo silently
# becomes a rule nobody applies.
OPEN_NAMESPACES: Tuple[str, ...] = (
    "dispute_escalation.levels.",
    "dispute_escalation.avt_volume_tiers.",
    "staking_rewards.lock_tiers",
    "slash_waterfall",
    "staking_reputation.volume_tiers",
)


def _defaults() -> Dict[str, Any]:
    """The factory document. Imported lazily — crud_enforcement pulls in models."""
    from ..crud.crud_enforcement import DEFAULT_POLICY_JSON
    return DEFAULT_POLICY_JSON


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base. Mutates and returns base.

    §BATCH0911 — A STORED NULL IS "UNSET", NEVER AN ERASER. Admission skips a null (every check
    reads `_get`, which cannot tell null from absent), `explain()` reports a null as the default,
    and `ResolvedPolicy.get` falls back past it; only this merge used to write it over the default,
    so `.doc` carried None where every readout said the default applied, and each reader's own
    literal fallback decided (the slash waterfall was the case measured). Now the resolved document
    and the readout agree: a null keeps the default. A key the default does not carry is still
    written as given (validation owns unknown keys).
    """
    for key, value in override.items():
        if value is None and key in base:
            continue
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _get(doc: Dict[str, Any], path: str) -> Any:
    """Dotted-path read. Returns None when any segment is missing."""
    cur: Any = doc
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def leaf_paths(doc: Dict[str, Any], prefix: str = "") -> List[str]:
    """Every dotted leaf path. Lists are leaves — `lock_tiers` and
    `slash_waterfall` are ordered values, not namespaces."""
    out: List[str] = []
    for key, value in doc.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out.extend(leaf_paths(value, f"{path}."))
        else:
            out.append(path)
    return out


def known_paths() -> set:
    """The paths a policy document may carry: every leaf of the factory default,
    plus every locked and bounded path the network declares."""
    return (
        set(leaf_paths(_defaults()))
        | set(LOCKED_PARAMS.keys())
        | set(BOUNDED_PARAMS.keys())
        | set(DEPRECATED_ALIASES.values())
        | set(RETIRED_PATHS.keys())
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve(row_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The document this frame is ACTUALLY running: the stored row deep-merged
    onto the factory default, so an unset field is the documented default and a
    section added after the row was written is never missing."""
    merged = copy.deepcopy(_defaults())
    if row_json:
        _deep_merge(merged, row_json)
        _promote_aliases(merged, row_json)
    return merged


def _set(doc: Dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    cur = doc
    for key in keys[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[keys[-1]] = value


def _promote_aliases(merged: Dict[str, Any], row_json: Dict[str, Any]) -> None:
    """A frame that set only the DEPRECATED key meant that value.

    Promotion must happen here and not in the getter: after the merge the
    canonical key is never absent (the factory default fills it), so a getter
    fallback can never fire and the frame's own choice would be silently
    replaced by the shipped default while the readout still claimed the frame
    had set it. Measured as exactly that contradiction before this existed.
    """
    for canonical, alias in DEPRECATED_ALIASES.items():
        if _get(row_json, canonical) is None:
            alias_value = _get(row_json, alias)
            if alias_value is not None:
                _set(merged, canonical, alias_value)


def policy_hash(doc: Dict[str, Any]) -> str:
    """THE canonical hash of a resolved policy document — bare lowercase hex.

    Callers that publish it on the registry card prefix it with 'sha256:'; the
    compliance endpoints publish it bare, which is the shape the poller has
    always compared. One function, so the two can never disagree again (M3/M4).
    """
    canonical = json.dumps(doc or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ResolvedPolicy:
    """A frame's rules, plus where each one came from."""
    doc: Dict[str, Any]
    version: int
    source: str                      # "factory_default" | "amended"
    modified_at: Optional[Any] = None
    modified_by: Optional[str] = None
    _row_json: Optional[Dict[str, Any]] = None

    def get(self, path: str, default: Any = None) -> Any:
        value = _get(self.doc, path)
        if value is None:
            alias = DEPRECATED_ALIASES.get(path)
            if alias:
                value = _get(self.doc, alias)
        return default if value is None else value

    def explain(self, path: str) -> Dict[str, Any]:
        """`value` plus the fact a readout must not lose: whether the FRAME set
        it or whether it is the shipped default. An unset field and a field set
        to the default value are different facts."""
        default_value = _get(self._defaults_doc(), path)
        set_here = _get(self._row_json or {}, path)
        used_alias = None
        if set_here is None:
            alias = DEPRECATED_ALIASES.get(path)
            if alias and _get(self._row_json or {}, alias) is not None:
                set_here = _get(self._row_json or {}, alias)
                used_alias = alias
        bounds = BOUNDED_PARAMS.get(path)
        value = self.get(path, default_value)
        out: Dict[str, Any] = {
            "path": path,
            "value": value,
            "default": default_value,
            "source": "policy" if set_here is not None else "default",
            "bounds": bounds,
            "in_bounds": _within(value, bounds) if bounds else None,
        }
        if used_alias:
            out["via_deprecated_key"] = used_alias

        # §CARDBOND — a rule an env var or the network profile outranks is reported as what the
        # rail APPLIES, asked of the rail itself (`reputation_bond.applied_rule`), so the value a
        # peer reads on the card is the value an agent is charged. Provenance keeps the card's two
        # words: an operator's own env value is the frame's choice ("policy"); the network profile
        # is a shipped default the frame did not write ("default"). The document's own value stays
        # readable as `policy_value`, and the policy HASH is untouched (it is over the document).
        governed = _knob_layer(path)
        if governed:
            from .reputation_bond import applied_rule
            applied = _plain_number(applied_rule(path, self.doc))
            if applied is not None:
                knob, layer = governed
                out["policy_value"] = out["value"]
                out["value"] = applied
                out["source"] = "policy" if layer == "env" else "default"
                out["governed_by"] = layer
                out["knob"] = knob
                out["in_bounds"] = _within(applied, bounds) if bounds else None
        return out

    def hash(self) -> str:
        return policy_hash(self.doc)

    @staticmethod
    def _defaults_doc() -> Dict[str, Any]:
        return _defaults()

    def posture(self, paths: Tuple[str, ...] = GOVERNED_PATHS) -> Dict[str, Any]:
        """The frame's declared posture for the rules its own code reads —
        the block the registry card publishes."""
        return {p: self.explain(p) for p in paths}


async def load(db) -> ResolvedPolicy:
    """Read the active row and resolve it. Never raises on an absent row: a
    frame with no policy is a frame running the factory default, and it says so."""
    from ..crud.crud_enforcement import get_active_policy
    row = await get_active_policy(db)
    row_json = (row.policy_json if row and row.policy_json else None)
    return ResolvedPolicy(
        doc=resolve(row_json),
        version=(row.version if row else 0),
        source=("amended" if row else "factory_default"),
        modified_at=(row.modified_at if row else None),
        modified_by=(row.modified_by if row else None),
        _row_json=row_json,
    )


# ---------------------------------------------------------------------------
# Validation — refuses what it should, passes what it should
# ---------------------------------------------------------------------------

def _within(value: Any, bounds: Optional[Dict[str, Any]]) -> Optional[bool]:
    if not bounds:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return False
    lo, hi = bounds.get("min"), bounds.get("max")
    if lo is not None and val < lo:
        return False
    if hi is not None and val > hi:
        return False
    return True


def validate_document(doc: Dict[str, Any]) -> List[str]:
    """Structural validation of a submitted/edited policy document.

    Refuses an UNKNOWN key (a typo silently becomes an ignored rule otherwise)
    and an OUT-OF-RANGE bounded value. Returns [] for a valid document — the
    factory default itself must return [], which is this function's own control.
    """
    problems: List[str] = []
    if not isinstance(doc, dict):
        return ["policy document must be an object"]

    allowed = known_paths()
    for path in leaf_paths(doc):
        if path in allowed:
            continue
        if any(path.startswith(ns) for ns in OPEN_NAMESPACES):
            continue          # operator-defined escalation levels / volume tiers
        problems.append(f"unknown policy key '{path}'")

    for path, bounds in BOUNDED_PARAMS.items():
        value = _get(doc, path)
        if value is None:
            continue
        if _within(value, bounds) is False:
            problems.append(
                f"'{path}' = {value!r} is outside its allowed range "
                f"[{bounds.get('min')}, {bounds.get('max')}]"
            )

    # §BONDFILL-3 — AN ALIAS IS BOUND BY ITS CANONICAL'S RANGE. `_promote_aliases` turns a
    # frame's old-key value into the canonical value at resolve time, so an alias that skipped
    # this check would be a way round every bound in the table: submit the old name, get the
    # value the new name forbids. Measured as exactly that hole before this existed.
    for canonical, alias in DEPRECATED_ALIASES.items():
        bounds = BOUNDED_PARAMS.get(canonical)
        value = _get(doc, alias)
        if not bounds or value is None:
            continue
        if _within(value, bounds) is False:
            problems.append(
                f"'{alias}' = {value!r} (deprecated name of '{canonical}') is outside its "
                f"allowed range [{bounds.get('min')}, {bounds.get('max')}]"
            )

    # §REPBOND structural checks (slash_waterfall / staking_reputation shapes).
    from ..crud.crud_enforcement import validate_policy_json
    problems.extend(validate_policy_json(doc))
    return problems


def knob_governed_changes(before_row: Optional[Dict[str, Any]],
                          after_row: Optional[Dict[str, Any]]) -> List[str]:
    """§CARDBOND — the rules a proposed change would MOVE while an env var or the network profile
    decides them on this node. A vote on such a rule could pass, be stored and change nothing.

    DIFF-BASED on the frame's stored row, before and after, under the canonical name AND its
    deprecated alias: EU's row carries the bond at 50 under both names while its profile charges
    250, so a document that restates today's values must pass, and only an actual move is refused.
    Returns [] when nothing governed moves (and always when no knob is set).
    """
    problems: List[str] = []
    for path in KNOB_OVERRIDES:
        governed = _knob_layer(path)
        if not governed:
            continue
        keys = [path] + ([DEPRECATED_ALIASES[path]] if path in DEPRECATED_ALIASES else [])
        moved = [k for k in keys if _get(before_row or {}, k) != _get(after_row or {}, k)]
        if not moved:
            continue
        knob, layer = governed
        from .reputation_bond import applied_rule
        applied = _plain_number(applied_rule(path, resolve(before_row)))
        where = "this node's environment" if layer == "env" else "the network profile"
        problems.append(
            f"'{moved[0]}' is decided on this frame by {knob} ({where}), currently {applied}, "
            f"which outranks the policy document: a vote on it cannot change what is applied"
        )
    return problems
