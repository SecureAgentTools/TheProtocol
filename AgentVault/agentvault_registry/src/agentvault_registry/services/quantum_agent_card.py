"""V0660 (a): the quantum workload extension on agent cards, our proposed standard.

Spec: PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0.md (the stack). The extension is one entry of a card's
TOP-LEVEL extensions[] (like the A2A payment extension), URI EXTENSION_URI, version 1.0: the roles an agent holds, the
backends it offers with their device facts (each with its as_of), how its use is metered (by reference to the payment
extension, which keeps the amount), the evidence it signs and the data terms it keeps.

ONE module for the extension, so the write check, discovery, the read routes and the MCP tools ask the same question:
- the schema: static_schemas/quantum_workload_v1.0.schema.json, a byte copy of the spec's JSON Schema (the SDK carries
  the same bytes; both pin SCHEMA_SHA256 in their tests);
- check(): the schema plus the spec's semantic rules (section 7), as sentences a writer can act on;
- gate(): the frame switch on a card write (core/quantum_mode.py): off checks nothing and changes nothing, shadow logs
  and counts what on would refuse and writes the card anyway, on refuses with the sentences;
- facets(): the index discovery and the Directory derive (roles, modalities, kinds, qubits, formats, jurisdictions,
  rungs), the same derivation the spec states, so the console's filters and the Directory's agree;
- the SQL discovery filters with (sql_extension, SQL_FILTERS, discover_filters).

What this module never does: refuse a card for a value judgement (a QPU is as legal as a simulator here), read or
store a circuit, or move anything: pricing names a model and points at the payment extension.
"""
from __future__ import annotations

import copy
import datetime as dt
import functools
import json
import logging
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

from ..core.quantum_mode import quantum_workloads_mode
from .quantum_receipts import METERING_CIRCUIT, TEMPLATES

logger = logging.getLogger(__name__)

EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/quantum/workload"
EXTENSION_VERSION = "1.0"
PAYMENT_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"
SPEC_NAME = "Quantum_Agent_Card_Extension_v1.0"
SCHEMA_FILE = "quantum_workload_v1.0.schema.json"
# The bytes every copy carries (the spec's, the SDK's, this registry's): a change to the schema changes all three and
# both pins, or a test in each repository fails.
SCHEMA_SHA256 = "99af03a3ac40a0977c85a7c4aebdd94c9e06020b55e63a95f31184b2732abfab"
# A device fact may be read a little ahead of this registry's clock; further ahead it is a claim about the future.
CLOCK_SKEW_SECONDS = 300
MAX_PROBLEMS = 10

OFF_SENTENCE = (
    "quantum_workloads_off: Quantum workloads are not enabled on this registry (QUANTUM_WORKLOADS_MODE=off). A card "
    "keeps a quantum workload extension as card data; this registry neither checks, indexes nor serves it."
)

try:  # metrics are best-effort; observability never breaks a card write
    from prometheus_client import Counter as _Counter
    _CHECKS = _Counter(
        "quantum_workload_card_checks_total",
        "Quantum workload extension checks on card writes, by frame mode, write path and outcome",
        ["mode", "where", "outcome"],
    )
except Exception:  # pragma: no cover
    _CHECKS = None


def _count(mode: str, where: str, outcome: str) -> None:
    if _CHECKS is not None:
        try:
            _CHECKS.labels(mode=mode, where=where, outcome=outcome).inc()
        except Exception:  # noqa: BLE001
            pass


# ── the schema ───────────────────────────────────────────────────────────────

def schema_path() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent / "static_schemas" / SCHEMA_FILE


@functools.lru_cache(maxsize=1)
def _schema_text() -> str:
    return schema_path().read_text(encoding="utf-8")


def schema() -> Dict[str, Any]:
    """The JSON Schema (a fresh copy: a caller may not change the one the check uses)."""
    return copy.deepcopy(_schema())


@functools.lru_cache(maxsize=1)
def _schema() -> Dict[str, Any]:
    return json.loads(_schema_text())


@functools.lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator
    return Draft202012Validator(_schema())


# ── reading the extension off a card ─────────────────────────────────────────

def _is_entry(e: Any) -> bool:
    return isinstance(e, dict) and e.get("uri") == EXTENSION_URI


def entries(card_data: Any) -> List[Dict[str, Any]]:
    """Every top-level extensions[] entry with this URI (a valid card carries exactly one)."""
    if not isinstance(card_data, dict) or not isinstance(card_data.get("extensions"), list):
        return []
    return [e for e in card_data["extensions"] if _is_entry(e)]


def extension_from_card(card_data: Any) -> Optional[Dict[str, Any]]:
    """The card's quantum workload extension (the first top-level entry), or None."""
    found = entries(card_data)
    return found[0] if found else None


def params_from_card(card_data: Any) -> Optional[Dict[str, Any]]:
    ext = extension_from_card(card_data)
    p = ext.get("params") if ext else None
    return p if isinstance(p, dict) else None


def _misplaced(card_data: Any) -> int:
    caps = card_data.get("capabilities") if isinstance(card_data, dict) else None
    exts = caps.get("extensions") if isinstance(caps, dict) else None
    return sum(1 for e in exts if _is_entry(e)) if isinstance(exts, list) else 0


def _has_payment_extension(card_data: Dict[str, Any]) -> bool:
    """Either legal placement of the payment extension counts (the ONE price rule reads both)."""
    caps = card_data.get("capabilities") if isinstance(card_data.get("capabilities"), dict) else {}
    for seq in (card_data.get("extensions"), caps.get("extensions")):
        if isinstance(seq, list) and any(isinstance(e, dict) and e.get("uri") == PAYMENT_EXTENSION_URI for e in seq):
            return True
    return False


# ── the check ────────────────────────────────────────────────────────────────

def _where(path) -> str:
    parts = [str(p) for p in path]
    return ".".join(parts) if parts else "extension"


def _parse_ts(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str):
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _timestamps(params: Dict[str, Any]) -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    for i, b in enumerate(params.get("backends") or []):
        if not isinstance(b, dict):
            continue
        out.append((f"params.backends.{i}.as_of", b.get("as_of")))
        for block in ("calibration", "queue", "availability"):
            if isinstance(b.get(block), dict):
                out.append((f"params.backends.{i}.{block}.as_of", b[block].get("as_of")))
    return out


def _semantic(card_data: Dict[str, Any], params: Dict[str, Any], now: dt.datetime) -> List[str]:
    """The spec's rules the schema cannot state (section 7), on an extension the schema already accepted."""
    problems: List[str] = []
    roles = set(params.get("roles") or [])
    backends = [b for b in (params.get("backends") or []) if isinstance(b, dict)]
    ids = [b.get("id") for b in backends]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"params.backends: the backend id {dup!r} is used more than once; each backend needs its own id")
    for i, b in enumerate(backends):
        q = b.get("qubits") or {}
        logical = q.get("logical") or {}
        if logical and int(logical.get("count") or 0) > int(q.get("physical") or 0):
            problems.append(f"params.backends.{i}.qubits.logical.count: more logical qubits ({logical.get('count')}) "
                            f"than physical ones ({q.get('physical')})")
        width = (b.get("limits") or {}).get("max_width")
        if width is not None and int(width) > int(q.get("physical") or 0):
            problems.append(f"params.backends.{i}.limits.max_width: a circuit wider ({width}) than the backend's "
                            f"qubits ({q.get('physical')})")
        for j, w in enumerate(((b.get("availability") or {}).get("windows")) or []):
            if isinstance(w, dict) and w.get("start_utc") == w.get("end_utc"):
                problems.append(f"params.backends.{i}.availability.windows.{j}: a window that starts when it ends")
    limit = now + dt.timedelta(seconds=CLOCK_SKEW_SECONDS)
    for where, value in _timestamps(params):
        t = _parse_ts(value)
        if t is None:
            problems.append(f"{where}: not a timestamp with an offset ({str(value)[:40]!r})")
        elif t > limit:
            problems.append(f"{where}: {value} is later than this registry's clock; a device fact names when it "
                            "was read, never a time to come")
    if isinstance(params.get("pricing"), dict) and not _has_payment_extension(card_data):
        problems.append("params.pricing: points at the A2A payment extension, and the card does not carry it; the "
                        f"amount and the unit of account live there ({PAYMENT_EXTENSION_URI})")
    ev = params.get("evidence") or {}
    rungs = set(ev.get("verification_rungs") or [])
    tests = [t for t in (ev.get("acceptance_tests") or []) if isinstance(t, dict)]
    templates = [t.get("template") for t in tests]
    for dup in sorted({t for t in templates if templates.count(t) > 1}):
        problems.append(f"params.evidence.acceptance_tests: the template {dup!r} is listed more than once")
    for k, t in enumerate(tests):
        known = TEMPLATES.get(t.get("template")) if isinstance(t.get("template"), str) else None
        if known and (t.get("rung"), t.get("method")) != (known["rung"], known["method"]):
            problems.append(f"params.evidence.acceptance_tests.{k}: {t.get('template')} is a rung {known['rung']} "
                            f"{known['method']} test (the receipt verifier's catalog); this one says rung "
                            f"{t.get('rung')} {t.get('method')}")
        if t.get("rung") not in rungs:
            problems.append(f"params.evidence.acceptance_tests.{k}: offers rung {t.get('rung')}, which "
                            "verification_rungs does not list")
    for r in (1, 2):
        if r in rungs and not any(t.get("rung") == r for t in tests):
            problems.append(f"params.evidence.verification_rungs: lists rung {r} and no acceptance test offers it")
    if "verifier" in roles and not tests:
        problems.append("params.evidence.acceptance_tests: a verifier names the acceptance tests it runs")
    if "meter" in roles and not ev.get("metering_circuit"):
        problems.append("params.evidence.metering_circuit: a meter names the circuit its log commitments are proved "
                        f"against ({METERING_CIRCUIT})")
    return problems


def check(card_data: Any, *, now: Optional[dt.datetime] = None) -> List[str]:
    """What is wrong with a card's quantum workload extension, as sentences; [] when the card carries none or a valid one.

    The order: placement first (a misplaced or doubled entry is not read at all), then the schema, then the semantic
    rules (only on an entry the schema accepted, so a sentence never describes a value of the wrong type)."""
    if not isinstance(card_data, dict):
        return []
    found = entries(card_data)
    problems: List[str] = []
    misplaced = _misplaced(card_data)
    if misplaced:
        problems.append("capabilities.extensions: the quantum workload extension belongs in the card's top-level "
                        "extensions[], where every reader looks for it")
    if not found:
        return problems
    if len(found) > 1:
        problems.append(f"extensions: a card carries one quantum workload extension; this one carries {len(found)}")
        return problems
    errors = sorted(_validator().iter_errors(found[0]), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        for e in errors:
            problems.append(f"{_where(e.absolute_path)}: {e.message[:200]}")
        return problems
    problems.extend(_semantic(card_data, found[0]["params"], now or dt.datetime.now(dt.timezone.utc)))
    return problems


def sentence(problems: List[str]) -> str:
    more = f" (and {len(problems) - MAX_PROBLEMS} more)" if len(problems) > MAX_PROBLEMS else ""
    return ("Invalid quantum workload extension (spec " + SPEC_NAME + "): " + "; ".join(problems[:MAX_PROBLEMS]) + more)


def gate(card_data: Any, *, where: str, name: Optional[str] = None) -> Optional[str]:
    """The frame switch on a card write. off: nothing is read, nothing changes. shadow: the check runs; what on would
    refuse is logged and counted, and the write goes ahead. on: a card whose extension fails the check is refused
    (ValueError with the sentences; the routes answer 422 with them). Returns the sentence shadow reported, else None."""
    mode = quantum_workloads_mode()
    if mode == "off":
        return None
    problems = check(card_data)
    if not problems:
        if entries(card_data):
            _count(mode, where, "valid")
        return None
    said = sentence(problems)
    if mode == "shadow":
        _count(mode, where, "would_refuse")
        logger.warning("[QUANTUM-SHADOW] %s: card %r would be refused under QUANTUM_WORKLOADS_MODE=on: %s",
                       where, name or (card_data.get("name") if isinstance(card_data, dict) else None), said)
        return said
    _count(mode, where, "refused")
    logger.info("[QUANTUM] %s: card %r refused: %s", where,
                name or (card_data.get("name") if isinstance(card_data, dict) else None), said)
    raise ValueError(said)


def served() -> bool:
    """Does this registry index and serve the extension (discovery filters, the read routes and tools)? shadow and on."""
    return quantum_workloads_mode() != "off"


# ── the index ────────────────────────────────────────────────────────────────

_ROLES = ("provider", "compiler", "mitigator", "verifier", "router", "meter")
_KINDS = ("qpu", "simulator", "emulator")
_MODALITIES = ("superconducting", "trapped-ion", "neutral-atom", "photonic", "spin", "annealer", "simulator")


def _strs(values, allowed=None) -> List[str]:
    """Strings in a closed vocabulary, or (allowed None) open names of 1 to 64 characters, as the Directory keeps them
    (directory/quantum_reader.py: the same derivation, spec section 8.1)."""
    out = sorted({v for v in values if isinstance(v, str) and 0 < len(v) <= 64 and (allowed is None or v in allowed)})
    return out


def facets(params: Any) -> Optional[Dict[str, Any]]:
    """The index one extension contributes (spec section 8), read defensively: a value of the wrong type is left out,
    never guessed. None when there are no params to read."""
    if not isinstance(params, dict):
        return None
    backends = [b for b in (params.get("backends") or []) if isinstance(b, dict)] \
        if isinstance(params.get("backends"), list) else []
    qubits = [b["qubits"]["physical"] for b in backends
              if isinstance(b.get("qubits"), dict) and isinstance(b["qubits"].get("physical"), int)
              and not isinstance(b["qubits"].get("physical"), bool)]
    logical = [b["qubits"]["logical"]["count"] for b in backends
               if isinstance(b.get("qubits"), dict) and isinstance(b["qubits"].get("logical"), dict)
               and isinstance(b["qubits"]["logical"].get("count"), int)
               and not isinstance(b["qubits"]["logical"].get("count"), bool)]
    formats: List[str] = []
    jurisdictions: List[str] = []
    for b in backends:
        if isinstance(b.get("formats"), list):
            formats.extend(b["formats"])
        loc = b.get("location")
        if isinstance(loc, dict):
            jurisdictions.append(loc.get("jurisdiction"))
    ev = params.get("evidence") if isinstance(params.get("evidence"), dict) else {}
    rungs = sorted({r for r in (ev.get("verification_rungs") or []) if r in (1, 2, 3) and not isinstance(r, bool)}) \
        if isinstance(ev.get("verification_rungs"), list) else []
    pricing = params.get("pricing") if isinstance(params.get("pricing"), dict) else {}
    return {
        "version": params.get("version") if isinstance(params.get("version"), str) else None,
        "roles": _strs(params.get("roles") or [], _ROLES) if isinstance(params.get("roles"), list) else [],
        "kinds": _strs((b.get("kind") for b in backends), _KINDS),
        "modalities": _strs((b.get("modality") for b in backends), _MODALITIES),
        "backends": len(backends),
        "max_qubits": max(qubits) if qubits else None,
        "max_logical_qubits": max(logical) if logical else None,
        "formats": _strs(formats),
        "jurisdictions": _strs(jurisdictions),
        "rungs": rungs,
        "pricing_model": pricing.get("model") if isinstance(pricing.get("model"), str) else None,
    }


def card_facets(card_data: Any) -> Optional[Dict[str, Any]]:
    return facets(params_from_card(card_data))


def freshness(params: Any, *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """How old each backend's facts are at this read (the card states when each was read; nothing here is refused)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    for b in (params.get("backends") or []) if isinstance(params, dict) else []:
        if not isinstance(b, dict):
            continue
        stamps = {"facts": b.get("as_of")}
        for block in ("calibration", "queue", "availability"):
            if isinstance(b.get(block), dict):
                stamps[block] = b[block].get("as_of")
        ages = {k: (round((now - t).total_seconds()) if (t := _parse_ts(v)) else None) for k, v in stamps.items()}
        known = [a for a in ages.values() if a is not None]
        rows.append({"id": b.get("id"), "as_of": stamps, "age_seconds": ages,
                     "oldest_age_seconds": max(known) if known else None})
    return {"read_at": now.isoformat().replace("+00:00", "Z"), "backends": rows}


# ── discovery ────────────────────────────────────────────────────────────────

def sql_extension(alias: str = "c") -> str:
    """The card's quantum workload extension as jsonb (NULL when it carries none): top level only, as the spec says.
    card_data is json on some older nodes, so it is cast (§JSONCAST)."""
    return ("jsonb_path_query_first(" + alias + ".card_data::jsonb, "
            "'$.extensions[*] ? (@.uri == \"" + EXTENSION_URI + "\")')")


# Every filter binds only when asked (a NULL bind is TRUE for its row), so a page that asks none of them lists exactly
# what it did before; each reads the extension the slim CTE carries as s.quantum_ext.
SQL_FILTERS = """
      AND (CAST(:quantum_only AS boolean) = FALSE OR s.quantum_ext IS NOT NULL)
      AND (CAST(:quantum_role AS text) IS NULL
           OR jsonb_path_exists(s.quantum_ext, '$.params.roles[*] ? (@ == $v)',
                                jsonb_build_object('v', CAST(:quantum_role AS text))))
      AND (CAST(:quantum_kind AS text) IS NULL
           OR jsonb_path_exists(s.quantum_ext, '$.params.backends[*].kind ? (@ == $v)',
                                jsonb_build_object('v', CAST(:quantum_kind AS text))))
      AND (CAST(:quantum_modality AS text) IS NULL
           OR jsonb_path_exists(s.quantum_ext, '$.params.backends[*].modality ? (@ == $v)',
                                jsonb_build_object('v', CAST(:quantum_modality AS text))))
      AND (CAST(:quantum_min_qubits AS integer) IS NULL
           OR jsonb_path_exists(s.quantum_ext, '$.params.backends[*].qubits.physical ? (@ >= $v)',
                                jsonb_build_object('v', CAST(:quantum_min_qubits AS integer))))
      AND (CAST(:quantum_format AS text) IS NULL
           OR jsonb_path_exists(s.quantum_ext, '$.params.backends[*].formats[*] ? (@ == $v)',
                                jsonb_build_object('v', CAST(:quantum_format AS text))))
      AND (CAST(:quantum_jurisdiction AS text) IS NULL
           OR jsonb_path_exists(s.quantum_ext, '$.params.backends[*].location.jurisdiction ? (@ == $v)',
                                jsonb_build_object('v', CAST(:quantum_jurisdiction AS text))))
      AND (CAST(:quantum_rung AS integer) IS NULL
           OR jsonb_path_exists(s.quantum_ext, '$.params.evidence.verification_rungs[*] ? (@ == $v)',
                                jsonb_build_object('v', CAST(:quantum_rung AS integer))))"""

# The quantum facets of the page's population (base, after every filter), in the page's own statement.
SQL_FACETS = """
    SELECT jsonb_build_object(
      'total', (SELECT COUNT(*) FROM base WHERE quantum_ext IS NOT NULL),
      'max_qubits', (SELECT MAX((x #>> '{}')::numeric) FROM base b,
                       LATERAL jsonb_path_query(b.quantum_ext, '$.params.backends[*].qubits.physical') x
                     WHERE b.quantum_ext IS NOT NULL AND jsonb_typeof(x) = 'number'),
      @@FACET_LISTS@@
    ) AS j
"""

_FACET_PATHS = (
    ("roles", "$.params.roles[*]"),
    ("kinds", "$.params.backends[*].kind"),
    ("modalities", "$.params.backends[*].modality"),
    ("formats", "$.params.backends[*].formats[*]"),
    ("jurisdictions", "$.params.backends[*].location.jurisdiction"),
    ("rungs", "$.params.evidence.verification_rungs[*]"),
)


def _facet_list_sql(name: str, path: str) -> str:
    return (f"'{name}', (SELECT COALESCE(jsonb_agg(jsonb_build_object('name', t.v, 'count', t.n) ORDER BY t.n DESC, t.v), "
            f"'[]'::jsonb) FROM (SELECT x #>> '{{}}' AS v, COUNT(DISTINCT b.id) AS n FROM base b, "
            f"LATERAL jsonb_path_query(b.quantum_ext, '{path}') x "
            f"WHERE b.quantum_ext IS NOT NULL AND jsonb_typeof(x) IN ('string', 'number') GROUP BY 1) t)")


SQL_FACETS = SQL_FACETS.replace("@@FACET_LISTS@@", ",\n      ".join(_facet_list_sql(n, p) for n, p in _FACET_PATHS))

DISCOVER_PARAMS = ("quantum_only", "quantum_role", "quantum_kind", "quantum_modality", "quantum_min_qubits",
                   "quantum_format", "quantum_jurisdiction", "quantum_rung")


def _int_param(name: str, raw: Optional[str], lo: int, hi: int) -> Tuple[Optional[int], Optional[str]]:
    if raw is None or str(raw).strip() == "":
        return None, None
    s = str(raw).strip()
    if not s.isdigit():
        return None, f"{name} must be a whole number from {lo} to {hi} (got {s[:40]!r})"
    n = int(s)
    if n < lo or n > hi:
        return None, f"{name} must be a whole number from {lo} to {hi} (got {n})"
    return n, None


def _enum_param(name: str, raw: Optional[str], allowed: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
    if raw is None or str(raw).strip() == "":
        return None, None
    s = str(raw).strip()
    if s not in allowed:
        return None, f"{name} must be one of {', '.join(allowed)} (got {s[:40]!r})"
    return s, None


def discover_filters(raw: Dict[str, Optional[str]]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """(binds, the applied_filters echo, problems) for the discovery query parameters. Called only where served():
    under off the parameters are not read at all, so a page is what it was before V0660."""
    problems: List[str] = []
    only_raw = str(raw.get("quantum_only") or "").strip().lower()
    if only_raw not in ("", "true", "false", "1", "0", "yes", "no"):
        problems.append(f"quantum_only must be true or false (got {only_raw[:40]!r})")
    only = only_raw in ("true", "1", "yes")
    role, p = _enum_param("quantum_role", raw.get("quantum_role"), _ROLES)
    problems += [p] if p else []
    kind, p = _enum_param("quantum_kind", raw.get("quantum_kind"), _KINDS)
    problems += [p] if p else []
    modality, p = _enum_param("quantum_modality", raw.get("quantum_modality"), _MODALITIES)
    problems += [p] if p else []
    qubits, p = _int_param("quantum_min_qubits", raw.get("quantum_min_qubits"), 1, 10_000_000)
    problems += [p] if p else []
    rung, p = _int_param("quantum_rung", raw.get("quantum_rung"), 1, 3)
    problems += [p] if p else []
    fmt = (str(raw.get("quantum_format") or "").strip() or None)
    if fmt is not None and (len(fmt) > 32 or not all(ch.isalnum() or ch in ".-" for ch in fmt)):
        problems.append(f"quantum_format must be a format name such as openqasm3 or qir (got {fmt[:40]!r})")
        fmt = None
    jur = (str(raw.get("quantum_jurisdiction") or "").strip().upper() or None)
    if jur is not None:
        if not re.fullmatch(r"EU|EEA|[A-Z]{2}(-[A-Z0-9]{1,3})?", jur):
            problems.append(f"quantum_jurisdiction must be a code such as DE, US-CA or EU (got {jur[:40]!r})")
            jur = None
    binds = {"quantum_only": only, "quantum_role": role, "quantum_kind": kind, "quantum_modality": modality,
             "quantum_min_qubits": qubits, "quantum_format": fmt, "quantum_jurisdiction": jur, "quantum_rung": rung}
    applied = {"quantum_only": only or None, "quantum_role": role, "quantum_kind": kind, "quantum_modality": modality,
               "quantum_min_qubits": qubits, "quantum_format": fmt, "quantum_jurisdiction": jur, "quantum_rung": rung}
    return binds, applied, problems


def facets_block(raw: Any) -> Dict[str, Any]:
    """The facets SQL_FACETS returned, as the response states them (an absent read reads as an empty population)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    raw = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {"total": int(raw.get("total") or 0),
                           "max_qubits": int(raw["max_qubits"]) if raw.get("max_qubits") is not None else None}
    for name, _p in _FACET_PATHS:
        rows = raw.get(name) if isinstance(raw.get(name), list) else []
        out[name] = [{"name": (int(r["name"]) if name == "rungs" and str(r.get("name")).isdigit() else r.get("name")),
                      "count": int(r.get("count") or 0)} for r in rows if isinstance(r, dict)]
    return out


__all__ = [
    "EXTENSION_URI", "EXTENSION_VERSION", "PAYMENT_EXTENSION_URI", "SPEC_NAME", "SCHEMA_FILE", "SCHEMA_SHA256",
    "OFF_SENTENCE", "schema", "schema_path", "entries", "extension_from_card", "params_from_card", "check", "sentence",
    "gate", "served", "facets", "card_facets", "freshness", "sql_extension", "SQL_FILTERS", "SQL_FACETS",
    "DISCOVER_PARAMS", "discover_filters", "facets_block",
]
