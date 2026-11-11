"""The quantum workload agent card extension, version 1.0, as Pydantic models (V0660 (a)).

The spec: PRODUCTION_DOCS/SPECS/Quantum_Agent_Card_Extension_v1.0.md (TheProtocol's stack). The extension is one entry of
an A2A agent card's top-level ``extensions[]``, URI ``https://theprotocol.cloud/extensions/v1/quantum/workload``. These
models carry the same rules as the JSON Schema shipped beside them (``quantum_workload_v1.0.schema.json``, the same bytes
a registry checks cards against): every object is closed, every device fact carries its ``as_of``, the amount and the
unit of account stay in the A2A payment extension, rung 3 is signed claims only, and the ledger keeps hashes and
verdicts, never circuits. A registry also applies the spec's semantic rules (section 7) when a card is written; those
read the whole card, so they are the registry's, not these models', except one the models can state alone: every
``as_of`` is a real date-time.

The models are strict, as the schema is: a JSON string, a boolean or a number is not coerced into another type ("32"
or true is not a count of qubits, "true" or 1 is not a flag). A whole number written with a decimal point (32.0) is the
number the schema accepts, and the models write every whole number as an integer (180, not 180.0): a card is signed over
python's ``json.dumps`` and a browser verifies it with ``JSON.stringify``, which writes 180 for both.

    from theprotocol.quantum import QuantumWorkload
    workload = QuantumWorkload.from_card(card)          # None when the card states none
    card["extensions"].append(workload.to_extension_dict())
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from ..models.agent_card import AgentExtension

QUANTUM_WORKLOAD_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/quantum/workload"
QUANTUM_WORKLOAD_VERSION = "1.0"
PAYMENT_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"

_TS = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$"
_HTTPS = r"^https://[^\s]+$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_CODE = r"^(EU|EEA|[A-Z]{2}(-[A-Z0-9]{1,3})?)$"
_ALG = r"^[A-Za-z0-9][A-Za-z0-9+._-]{1,47}$"
_HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
_KNOWN_FORMATS = ("openqasm3", "openqasm2", "qir", "quil", "ahs", "qubo")

Role = Literal["provider", "compiler", "mitigator", "verifier", "router", "meter"]
Kind = Literal["qpu", "simulator", "emulator"]
Modality = Literal["superconducting", "trapped-ion", "neutral-atom", "photonic", "spin", "annealer", "simulator"]


def as_datetime(value: str) -> _dt.datetime:
    """An ``as_of`` as an aware datetime (any fraction of 1 to 6 digits, on every Python the SDK supports)."""
    s = value[:-1] + "+00:00" if value.endswith("Z") else value
    s = _re.sub(r"\.([0-9]{1,6})(?=[+-][0-9]{2}:[0-9]{2}$)", lambda m: "." + m.group(1).ljust(6, "0"), s)
    return _dt.datetime.fromisoformat(s)


def _a_real_date_time(value: str) -> str:
    try:
        as_datetime(value)
    except ValueError:
        raise ValueError(f"not a date-time ({value[:40]!r}): an as_of is an RFC 3339 date-time with its offset") from None
    return value


def _whole_as_int(value: Any) -> Any:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _not_a_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("a rung is the number 1, 2 or 3, not a boolean")
    return value


def _a_bool(value: Any) -> Any:
    if not isinstance(value, bool):
        raise ValueError("self_declared is the boolean true")
    return value


Timestamp = Annotated[str, Field(pattern=_TS), AfterValidator(_a_real_date_time)]
Int = Annotated[int, BeforeValidator(_whole_as_int)]
Num = Annotated[Union[int, float], BeforeValidator(_whole_as_int)]
OfferedRung = Annotated[Literal[1, 2], BeforeValidator(_not_a_bool)]
Rung = Annotated[Literal[1, 2, 3], BeforeValidator(_not_a_bool)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Operator(_Closed):
    name: str = Field(..., min_length=1, max_length=120)
    url: Optional[str] = Field(None, pattern=_HTTPS, max_length=2048)


class Location(_Closed):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    country: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    region: Optional[str] = Field(None, pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    jurisdiction: str = Field(..., pattern=_CODE)


class Decoder(_Closed):
    """A real-time decoder runs next to the hardware, never as a network service."""
    name: str = Field(..., min_length=1, max_length=120)
    version: str = Field(..., min_length=1, max_length=48)
    placement: Literal["on-device", "co-located"]


class LogicalQubits(_Closed):
    count: Int = Field(..., ge=1)
    code: str = Field(..., pattern=r"^[a-z0-9][a-z0-9.+-]{0,47}$")
    decoder: Optional[Decoder] = None


class Qubits(_Closed):
    physical: Int = Field(..., ge=1, le=10_000_000)
    logical: Optional[LogicalQubits] = None


class CouplingMap(_Closed):
    digest: str = Field(..., pattern=_DIGEST)
    url: str = Field(..., pattern=_HTTPS, max_length=2048)
    edges: Optional[Int] = Field(None, ge=0)


class Connectivity(_Closed):
    topology: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    coupling_map: Optional[CouplingMap] = None

    @model_validator(mode="after")
    def _a_map_unless_all_to_all(self) -> "Connectivity":
        if self.topology != "all-to-all" and self.coupling_map is None:
            raise ValueError("a topology other than all-to-all names its coupling map (digest and url)")
        return self


class Limits(_Closed):
    max_shots: Int = Field(..., ge=1)
    max_depth: Optional[Int] = Field(None, ge=1)
    max_width: Optional[Int] = Field(None, ge=1)
    max_circuits_per_task: Optional[Int] = Field(None, ge=1)
    mid_circuit_measurement: bool
    dynamic_circuits: bool


class Snapshot(_Closed):
    digest: str = Field(..., pattern=_DIGEST)
    url: Optional[str] = Field(None, pattern=_HTTPS, max_length=2048)
    signing_algorithm: Optional[str] = Field(None, pattern=_ALG)


class Calibration(_Closed):
    as_of: Timestamp
    median_1q_error: Optional[Num] = Field(None, ge=0, le=1)
    median_2q_error: Optional[Num] = Field(None, ge=0, le=1)
    median_readout_error: Optional[Num] = Field(None, ge=0, le=1)
    median_t1_us: Optional[Num] = Field(None, gt=0)
    median_t2_us: Optional[Num] = Field(None, gt=0)
    snapshot: Snapshot


class Queue(_Closed):
    as_of: Timestamp
    status: Literal["online", "paused", "offline", "maintenance", "retired"]
    estimated_wait_seconds: Optional[Int] = Field(None, ge=0)
    pending_tasks: Optional[Int] = Field(None, ge=0)


class Window(_Closed):
    days: Literal["everyday", "weekdays", "weekend", "monday", "tuesday", "wednesday", "thursday", "friday",
                  "saturday", "sunday"]
    start_utc: str = Field(..., pattern=_HHMM)
    end_utc: str = Field(..., pattern=_HHMM)


class Availability(_Closed):
    as_of: Timestamp
    windows: List[Window] = Field(..., min_length=1, max_length=32)


class Backend(_Closed):
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    kind: Kind
    modality: Modality
    as_of: Timestamp
    operator: Optional[Operator] = None
    location: Location
    qubits: Qubits
    connectivity: Connectivity
    native_gates: List[str] = Field(..., min_length=1, max_length=64)
    formats: List[str] = Field(..., min_length=1, max_length=16)
    limits: Limits
    calibration: Optional[Calibration] = None
    queue: Queue
    availability: Optional[Availability] = None

    @model_validator(mode="after")
    def _rules(self) -> "Backend":
        import re
        if len(set(self.native_gates)) != len(self.native_gates) or len(set(self.formats)) != len(self.formats):
            raise ValueError("native_gates and formats list each name once")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", g) for g in self.native_gates):
            raise ValueError("a native gate is a lowercase name such as cx, rz or ms")
        if any(f not in _KNOWN_FORMATS and not re.fullmatch(r"x-[a-z0-9][a-z0-9.-]{0,30}", f) for f in self.formats):
            raise ValueError(f"a format is one of {', '.join(_KNOWN_FORMATS)} or an x- name")
        if self.kind == "simulator" and self.modality != "simulator":
            raise ValueError("a simulator states the modality simulator")
        if self.kind != "simulator" and self.modality == "simulator":
            raise ValueError(f"a backend of kind {self.kind} states the modality of its device")
        if self.kind == "qpu" and (self.operator is None or self.calibration is None):
            raise ValueError("a QPU names its operator and states its calibration")
        return self


class Pricing(_Closed):
    """How use is metered. The amount and the unit of account live in the A2A payment extension, never here."""
    model: Literal["per_shot", "per_task", "per_second", "per_gate_shot"]
    unit: Literal["shot", "task", "circuit", "qpu-second", "gate-shot"]
    payment_extension: Literal["https://theprotocol.cloud/extensions/v1/auth/a2a-payment"]

    @model_validator(mode="after")
    def _unit_follows_model(self) -> "Pricing":
        allowed = {"per_shot": ("shot",), "per_task": ("task", "circuit"), "per_second": ("qpu-second",),
                   "per_gate_shot": ("gate-shot",)}[self.model]
        if self.unit not in allowed:
            raise ValueError(f"pricing model {self.model} meters in {' or '.join(allowed)}")
        return self


class Receipt(_Closed):
    schema_version: str = Field(..., pattern=r"^[0-9]{1,3}\.[0-9]{1,3}$")
    signing_algorithm: str = Field(..., pattern=_ALG)


class AcceptanceTest(_Closed):
    template: str = Field(..., pattern=r"^[a-z0-9][a-z0-9.-]{0,63}/v[0-9]{1,3}\.[0-9]{1,3}(\.[0-9]{1,3})?$")
    rung: OfferedRung
    method: Literal["answer_check", "test_circuits", "classical_simulation", "independent_repeat"]
    false_accept_rate: Optional[Num] = Field(None, ge=0, le=1)
    false_reject_rate: Optional[Num] = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _rung_rules(self) -> "AcceptanceTest":
        if self.rung == 1 and self.method != "answer_check":
            raise ValueError("a rung 1 test checks the answer (answer_check)")
        if self.rung == 2:
            if self.method == "answer_check":
                raise ValueError("a rung 2 test is statistical: test_circuits, classical_simulation or independent_repeat")
            if self.false_accept_rate is None or self.false_reject_rate is None:
                raise ValueError("a rung 2 test states its false-accept and false-reject rates")
        return self


class Evidence(_Closed):
    receipt: Receipt
    acceptance_tests: Optional[List[AcceptanceTest]] = Field(None, max_length=16)
    metering_circuit: Optional[str] = Field(None, pattern=r"^[A-Za-z][A-Za-z0-9]{0,63}/v[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")
    verification_rungs: List[Rung] = Field(..., min_length=1)
    rung_3_basis: Optional[Literal["signed_claims"]] = None

    @model_validator(mode="after")
    def _rung3(self) -> "Evidence":
        if len(set(self.verification_rungs)) != len(self.verification_rungs):
            raise ValueError("verification_rungs lists each rung once")
        if 3 in self.verification_rungs and self.rung_3_basis != "signed_claims":
            raise ValueError("rung 3 is offered as signed claims only (rung_3_basis: signed_claims)")
        return self


class Retention(_Closed):
    circuits_days: Int = Field(..., ge=0, le=3650)
    results_days: Int = Field(..., ge=0, le=3650)


class ExportControl(_Closed):
    self_declared: Annotated[Literal[True], BeforeValidator(_a_bool)]
    note: str = Field(..., min_length=1, max_length=500)


class DataTerms(_Closed):
    retention: Retention
    residency: List[str] = Field(..., min_length=1, max_length=32)
    export_control: Optional[ExportControl] = None
    ledger_keeps: List[Literal["hashes", "verdicts"]] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _codes(self) -> "DataTerms":
        import re
        if any(not re.fullmatch(_CODE[1:-1], c) for c in self.residency) or len(set(self.residency)) != len(self.residency):
            raise ValueError("residency lists jurisdiction codes (DE, US-CA, EU), each once")
        if len(set(self.ledger_keeps)) != len(self.ledger_keeps):
            raise ValueError("ledger_keeps lists each item once")
        return self


class QuantumWorkload(_Closed):
    """The extension's ``params``: what a quantum workload agent offers, the facts of its backends, and its terms."""
    version: str = Field(..., pattern=r"^1\.[0-9]{1,3}$")
    roles: List[Role] = Field(..., min_length=1)
    backends: Optional[List[Backend]] = Field(None, min_length=1, max_length=32)
    pricing: Optional[Pricing] = None
    evidence: Evidence
    data: DataTerms

    @model_validator(mode="after")
    def _provider_has_backends(self) -> "QuantumWorkload":
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("roles lists each role once")
        if "provider" in self.roles and not self.backends:
            raise ValueError("a provider lists its backends")
        return self

    # ── on a card ────────────────────────────────────────────────────────────

    @classmethod
    def from_extension(cls, entry: Dict[str, Any]) -> "QuantumWorkload":
        if not isinstance(entry, dict) or entry.get("uri") != QUANTUM_WORKLOAD_EXTENSION_URI:
            raise ValueError(f"not a quantum workload extension entry ({QUANTUM_WORKLOAD_EXTENSION_URI})")
        return cls.model_validate(entry.get("params"))

    @classmethod
    def from_card(cls, card: Union[Dict[str, Any], BaseModel, None]) -> Optional["QuantumWorkload"]:
        """The workload a card states in its top-level extensions[] (the first entry), or None. A dict card or a
        theprotocol.models.AgentCard; an entry placed under capabilities.extensions is not read."""
        if card is None:
            return None
        data = card.model_dump(mode="json", by_alias=True) if isinstance(card, BaseModel) else card
        exts = data.get("extensions") if isinstance(data, dict) else None
        for e in exts or []:
            if isinstance(e, dict) and e.get("uri") == QUANTUM_WORKLOAD_EXTENSION_URI:
                return cls.from_extension(e)
        return None

    def to_extension(self, *, description: Optional[str] = None, required: bool = False) -> AgentExtension:
        return AgentExtension(uri=QUANTUM_WORKLOAD_EXTENSION_URI, description=description, required=required,
                              params=self.model_dump(mode="json", exclude_none=True))

    def to_extension_dict(self, *, description: Optional[str] = None, required: bool = False) -> Dict[str, Any]:
        """The entry as a card carries it: {uri, description?, required?, params}."""
        out: Dict[str, Any] = {"uri": QUANTUM_WORKLOAD_EXTENSION_URI}
        if description:
            out["description"] = description
        if required:
            out["required"] = True
        out["params"] = self.model_dump(mode="json", exclude_none=True)
        return out

    def facets(self) -> Dict[str, Any]:
        """The index the spec derives (section 8), as a registry's discovery and the Directory state it."""
        bs = self.backends or []
        logical = [b.qubits.logical.count for b in bs if b.qubits.logical]
        return {
            "version": self.version,
            "roles": sorted(set(self.roles)),
            "kinds": sorted({b.kind for b in bs}),
            "modalities": sorted({b.modality for b in bs}),
            "backends": len(bs),
            "max_qubits": max((b.qubits.physical for b in bs), default=None),
            "max_logical_qubits": max(logical) if logical else None,
            "formats": sorted({f for b in bs for f in b.formats}),
            "jurisdictions": sorted({b.location.jurisdiction for b in bs}),
            "rungs": sorted(set(self.evidence.verification_rungs)),
            "pricing_model": self.pricing.model if self.pricing else None,
        }


__all__ = [
    "QUANTUM_WORKLOAD_EXTENSION_URI", "QUANTUM_WORKLOAD_VERSION", "PAYMENT_EXTENSION_URI", "as_datetime",
    "QuantumWorkload", "Backend", "Operator", "Location", "Qubits", "LogicalQubits", "Decoder", "Connectivity",
    "CouplingMap", "Limits", "Calibration", "Snapshot", "Queue", "Availability", "Window", "Pricing", "Evidence",
    "Receipt", "AcceptanceTest", "DataTerms", "Retention", "ExportControl",
]
