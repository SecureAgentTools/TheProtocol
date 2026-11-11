"""V0660 (a) (session-code, 2026-11-08): the quantum workload extension, as the Directory indexes it.

A card states the extension as one entry of its top-level extensions[] (URI QUANTUM_EXTENSION_URI, version 1.x; spec
PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0.md). The Directory keeps only the INDEX the spec derives from it
(section 8: roles, backend kinds and modalities, how many backends, the most physical and logical qubits, the formats,
the jurisdictions, the verification rungs and the metering model), the same derivation a registry's discovery states
(agentvault_registry.services.quantum_agent_card.facets), so a filter here and a filter at a registry agree. The device
facts themselves stay on the card at its home, signed by that registry, with their as_of.

Read defensively, as the registry reads it: a value of the wrong type is left out, never guessed, and roles, kinds and
modalities are read in the spec's closed vocabularies (formats and jurisdictions are open names, kept as stated up to 64
characters). The index does not check the extension (its home registry does, under that frame's
QUANTUM_WORKLOADS_MODE); it states what the card says. Kept free of any registry import, so the Directory's CI job (a plain Python container) can test it.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

QUANTUM_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/quantum/workload"
ROLES = ("provider", "compiler", "mitigator", "verifier", "router", "meter")
KINDS = ("qpu", "simulator", "emulator")
MODALITIES = ("superconducting", "trapped-ion", "neutral-atom", "photonic", "spin", "annealer", "simulator")


def _int(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _named(v: str) -> bool:
    return 0 < len(v) <= 64


def _strs(values: Iterable[Any], ok) -> List[str]:
    return sorted({v for v in values if isinstance(v, str) and ok(v)})


def extension_from_card(card_data: Any) -> Optional[Dict[str, Any]]:
    """The card's first top-level entry with the quantum workload URI, or None."""
    exts = card_data.get("extensions") if isinstance(card_data, dict) else None
    if not isinstance(exts, list):
        return None
    return next((e for e in exts if isinstance(e, dict) and e.get("uri") == QUANTUM_EXTENSION_URI), None)


def facets(params: Any) -> Optional[Dict[str, Any]]:
    """The index one extension contributes; None when there are no params to read."""
    if not isinstance(params, dict):
        return None
    backends = [b for b in params.get("backends") if isinstance(b, dict)] if isinstance(params.get("backends"), list) else []
    qubits = [q for b in backends if isinstance(b.get("qubits"), dict) for q in [_int(b["qubits"].get("physical"))] if q]
    logical = [q for b in backends if isinstance(b.get("qubits"), dict) and isinstance(b["qubits"].get("logical"), dict)
               for q in [_int(b["qubits"]["logical"].get("count"))] if q]
    formats = [f for b in backends if isinstance(b.get("formats"), list) for f in b["formats"]]
    places = [b["location"].get("jurisdiction") for b in backends if isinstance(b.get("location"), dict)]
    ev = params.get("evidence") if isinstance(params.get("evidence"), dict) else {}
    rungs = sorted({r for r in ev.get("verification_rungs") if _int(r) in (1, 2, 3)}) \
        if isinstance(ev.get("verification_rungs"), list) else []
    pricing = params.get("pricing") if isinstance(params.get("pricing"), dict) else {}
    return {
        "version": params.get("version") if isinstance(params.get("version"), str) else None,
        "roles": _strs(params.get("roles") if isinstance(params.get("roles"), list) else [], lambda v: v in ROLES),
        "kinds": _strs((b.get("kind") for b in backends), lambda v: v in KINDS),
        "modalities": _strs((b.get("modality") for b in backends), lambda v: v in MODALITIES),
        "backends": len(backends),
        "max_qubits": max(qubits) if qubits else None,
        "max_logical_qubits": max(logical) if logical else None,
        "formats": _strs(formats, _named),
        "jurisdictions": _strs(places, _named),
        "rungs": rungs,
        "pricing_model": pricing.get("model") if isinstance(pricing.get("model"), str) else None,
    }


def facets_from_card(card_data: Any) -> Optional[Dict[str, Any]]:
    """The index a card's quantum workload extension contributes, or None when the card states none."""
    ext = extension_from_card(card_data)
    return facets(ext.get("params")) if ext else None
