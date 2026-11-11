"""The QPU proxy's backends (V0660 (c)): what runs a circuit, and the facts a card states about it.

Simulators only on our side, per V0660's ground rules, and no advantage claims: `SimulatorBackend` is a
small state-vector simulator that exists so the recipe runs with nothing installed. Cloud QPU adapters are
declared here and REFUSE to run — they sit behind credentials we do not hold and we do not call them.

A backend answers two questions and nothing else:
  * `facts()` — the device facts the quantum workload card extension requires of a `backends[]` entry,
    derived from the backend itself. tp-proxy builds the card from this, so nothing in a published card is
    hand-written prose that can rot away from the machine.
  * `run(circuit, shots, seed)` — the counts, with the shots it really ran, so the meter can prove them.
"""
from __future__ import annotations

import cmath
import datetime as dt
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .qasm import MEASURE, SUPPORTED_GATES, Circuit, QasmUnsupported

DEFAULT_MAX_SHOTS = 100_000
DEFAULT_MAX_QUBITS = 24          # 2**24 complex amplitudes is already 256 MiB: a limit, stated, not a boast


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Result:
    """What a run produced. `counts` keys read left to right in the order the circuit measured."""
    counts: Dict[str, int]
    shots: int
    backend_id: str = ""
    circuit_digest: str = ""
    ran_at: str = field(default_factory=_now)
    seed: Optional[int] = None


# ── the gates, as matrices ───────────────────────────────────────────────────────────────────────────────

_SQRT1_2 = 1.0 / math.sqrt(2.0)
_ONE_QUBIT = {
    "h": ((_SQRT1_2, _SQRT1_2), (_SQRT1_2, -_SQRT1_2)),
    "x": ((0.0, 1.0), (1.0, 0.0)),
    "y": ((0.0, -1j), (1j, 0.0)),
    "z": ((1.0, 0.0), (0.0, -1.0)),
    "s": ((1.0, 0.0), (0.0, 1j)),
    "sdg": ((1.0, 0.0), (0.0, -1j)),
    "t": ((1.0, 0.0), (0.0, cmath.exp(1j * math.pi / 4))),
    "tdg": ((1.0, 0.0), (0.0, cmath.exp(-1j * math.pi / 4))),
}


def _rotation(name: str, theta: float) -> Tuple[Tuple[complex, complex], Tuple[complex, complex]]:
    half = theta / 2.0
    if name == "rx":
        return ((math.cos(half), -1j * math.sin(half)), (-1j * math.sin(half), math.cos(half)))
    if name == "ry":
        return ((math.cos(half), -math.sin(half)), (math.sin(half), math.cos(half)))
    if name == "rz":
        return ((cmath.exp(-1j * half), 0.0), (0.0, cmath.exp(1j * half)))
    if name == "p":
        return ((1.0, 0.0), (0.0, cmath.exp(1j * theta)))
    raise QasmUnsupported(f"{name!r} is not a rotation this simulator runs")


def _apply_one(state: List[complex], n: int, target: int, m) -> None:
    step = 1 << target
    for base in range(0, 1 << n, step << 1):
        for off in range(step):
            i = base + off
            j = i + step
            a, b = state[i], state[j]
            state[i] = m[0][0] * a + m[0][1] * b
            state[j] = m[1][0] * a + m[1][1] * b


def _apply_controlled(state: List[complex], n: int, control: int, target: int, m) -> None:
    for i in range(1 << n):
        if (i >> control) & 1 and not (i >> target) & 1:
            j = i | (1 << target)
            a, b = state[i], state[j]
            state[i] = m[0][0] * a + m[0][1] * b
            state[j] = m[1][0] * a + m[1][1] * b


def _apply_swap(state: List[complex], n: int, a: int, b: int) -> None:
    for i in range(1 << n):
        if ((i >> a) & 1) and not ((i >> b) & 1):
            j = (i & ~(1 << a)) | (1 << b)
            state[i], state[j] = state[j], state[i]


def simulate(circuit: Circuit, shots: int, seed: Optional[int] = None) -> Dict[str, int]:
    """Run the circuit and sample `shots` outcomes over the qubits it measured."""
    n = circuit.qubits
    state: List[complex] = [0j] * (1 << n)
    state[0] = 1 + 0j

    for op in circuit.ops:
        if op.name == MEASURE:
            continue
        if op.name in _ONE_QUBIT:
            _apply_one(state, n, op.qubits[0], _ONE_QUBIT[op.name])
        elif op.name in ("rx", "ry", "rz", "p"):
            _apply_one(state, n, op.qubits[0], _rotation(op.name, op.params[0]))
        elif op.name == "cx":
            _apply_controlled(state, n, op.qubits[0], op.qubits[1], _ONE_QUBIT["x"])
        elif op.name == "cz":
            _apply_controlled(state, n, op.qubits[0], op.qubits[1], _ONE_QUBIT["z"])
        elif op.name == "swap":
            _apply_swap(state, n, op.qubits[0], op.qubits[1])
        else:  # pragma: no cover - the reader refuses anything else before we get here
            raise QasmUnsupported(f"the simulator does not run {op.name!r}")

    weights = [abs(amp) ** 2 for amp in state]
    total = sum(weights)
    if total <= 0:  # pragma: no cover - a normalised state always sums to one
        raise QasmUnsupported("the circuit left no amplitude to measure")

    rng = random.Random(seed)
    cumulative: List[float] = []
    running = 0.0
    for w in weights:
        running += w / total
        cumulative.append(running)

    counts: Dict[str, int] = {}
    for _ in range(shots):
        r = rng.random()
        lo, hi = 0, len(cumulative) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if r <= cumulative[mid]:
                hi = mid
            else:
                lo = mid + 1
        key = "".join("1" if (lo >> q) & 1 else "0" for q in circuit.measured)
        counts[key] = counts.get(key, 0) + 1
    return counts


# ── the backends ─────────────────────────────────────────────────────────────────────────────────────────

class Backend:
    """What the recipe needs of anything that runs circuits."""

    kind: str = ""

    def __init__(self, config: Mapping[str, Any]):
        self.config = dict(config or {})
        self.id = str(self.config.get("id") or "").strip()
        if not self.id:
            raise QasmUnsupported("a backend needs an 'id': the card names it and a receipt cites it")

    def facts(self) -> Dict[str, Any]:  # pragma: no cover - each backend answers for itself
        raise NotImplementedError

    async def run(self, circuit: Circuit, *, shots: int, seed: Optional[int] = None) -> Result:  # pragma: no cover
        raise NotImplementedError


class SimulatorBackend(Backend):
    """A state-vector simulator with no dependencies. Small on purpose."""

    kind = "simulator"

    def __init__(self, config: Mapping[str, Any]):
        super().__init__(config)
        self.qubits = int(self.config.get("qubits") or 0)
        if self.qubits < 1:
            raise QasmUnsupported("a simulator needs 'qubits': how many it offers")
        if self.qubits > DEFAULT_MAX_QUBITS:
            raise QasmUnsupported(f"{self.qubits} qubits is past this simulator's limit of {DEFAULT_MAX_QUBITS}")
        self.max_shots = int(self.config.get("max_shots") or DEFAULT_MAX_SHOTS)

    def facts(self) -> Dict[str, Any]:
        gates = sorted(g for g in SUPPORTED_GATES if g != MEASURE)
        return {
            "id": self.id,
            "name": str(self.config.get("name") or f"{self.id} (state-vector simulator)"),
            "kind": "simulator",
            "modality": "simulator",
            "as_of": _now(),
            "operator": dict(self.config.get("operator") or {"name": "self-hosted"}),
            # the spec's own vocabulary, not ours: location names a jurisdiction, limits are max_*, and a
            # queue's status is one of its five words. Every one of these was wrong when first written here
            # and (a)'s models caught all seven at once, which is the reason they judge the result.
            "location": dict(self.config.get("location") or {"jurisdiction": "EU"}),
            "qubits": {"physical": self.qubits},
            "connectivity": {"topology": "all-to-all"},
            "native_gates": gates,
            "formats": ["openqasm3"],
            "limits": {"max_shots": self.max_shots, "max_width": self.qubits,
                       "mid_circuit_measurement": False, "dynamic_circuits": False},
            "queue": {"as_of": _now(), "status": "online", "estimated_wait_seconds": 0,
                      "pending_tasks": 0},
        }

    async def run(self, circuit: Circuit, *, shots: int, seed: Optional[int] = None) -> Result:
        if shots < 1:
            raise QasmUnsupported(f"{shots} shots is not a run: ask for at least one")
        if shots > self.max_shots:
            raise QasmUnsupported(f"{shots} shots is past this backend's limit of {self.max_shots}")
        if circuit.qubits > self.qubits:
            raise QasmUnsupported(f"the circuit needs {circuit.qubits} qubits and this backend offers {self.qubits}")
        counts = simulate(circuit, shots, seed)
        return Result(counts=counts, shots=shots, backend_id=self.id,
                      circuit_digest=circuit.source_digest, seed=seed)


class CloudBackend(Backend):
    """A cloud QPU, declared and not called.

    The recipe ships the shape so a provider can see where its own credentials would go, and refuses to run:
    we hold no account with any QPU vendor, V0660 is simulators only, and a stub that quietly simulated while
    claiming a QPU would be the one lie this whole order exists to prevent."""

    kind = "qpu"
    vendors = ("ibm", "braket", "azure", "ionq", "quantinuum")

    def __init__(self, config: Mapping[str, Any]):
        super().__init__(config)
        self.vendor = str(self.config.get("vendor") or "").strip().lower()
        if self.vendor not in self.vendors:
            raise QasmUnsupported(f"{self.vendor!r} is not a vendor this recipe knows: {', '.join(self.vendors)}")

    def facts(self) -> Dict[str, Any]:
        raise QasmUnsupported(
            f"the {self.vendor} adapter states no device facts: it is a stub, and a card must never carry "
            "facts nobody read from a device")

    async def run(self, circuit: Circuit, *, shots: int, seed: Optional[int] = None) -> Result:
        raise QasmUnsupported(
            f"the {self.vendor} adapter does not run circuits: V0660 is simulators only, and this adapter "
            "holds no credentials. Point the recipe at a simulator backend, or bring your own account.")


BACKENDS: Dict[str, type] = {"simulator": SimulatorBackend, "qpu": CloudBackend}


def backend_from(config: Mapping[str, Any]) -> Backend:
    """Build the backend a spec names.

    `kind` is one of the words in BACKENDS, or a "module:Class" path to a provider's own Backend. The
    recipe ships one small simulator and no accelerated one on purpose: an accelerated path we cannot run
    cannot be tested, so the seam is here instead and a bigger simulator or a real QPU client is installed
    and named by whoever actually has it."""
    raw = str((config or {}).get("kind") or "simulator").strip()
    if ":" in raw:
        module, _, attr = raw.partition(":")
        try:
            import importlib
            cls = getattr(importlib.import_module(module), attr)
        except Exception as exc:
            raise QasmUnsupported(f"the backend {raw!r} does not load: {type(exc).__name__}: {exc}") from exc
        if not (isinstance(cls, type) and issubclass(cls, Backend)):
            raise QasmUnsupported(f"{raw!r} is not a Backend: a custom backend subclasses "
                                  "theprotocol.proxy.quantum.backends.Backend and answers facts() and run()")
        return cls(config)
    kind = raw.lower()
    if kind not in BACKENDS:
        raise QasmUnsupported(f"{kind!r} is not a backend kind: {', '.join(sorted(BACKENDS))}, or a "
                              "\"module:Class\" path to your own Backend")
    return BACKENDS[kind](config)
