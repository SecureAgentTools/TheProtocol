"""A small OpenQASM 3 reader for the QPU proxy recipe (V0660 (c)).

It reads the subset the built-in simulator really runs and REFUSES everything else by name. That refusal is
the whole point of the module: a reader that skipped a gate it does not implement would return counts that
look like a result and are not one, and a receipt signed over those counts would make the lie durable.

The subset: the `OPENQASM 3;` header, an optional `include`, one `qubit[n]` register, optional `bit[n]`
registers, the gates in `SUPPORTED_GATES`, `barrier`, and `measure` (per qubit or over the whole register).
A real provider plugs its own compiler in behind the same `Circuit`; this reader exists so the recipe runs
with nothing installed.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

# name -> (how many qubits it takes, how many angles it takes). Published, so a card can state the backend's
# native gates from the set the backend actually runs rather than from a comment.
SUPPORTED_GATES: Dict[str, Tuple[int, int]] = {
    "h": (1, 0), "x": (1, 0), "y": (1, 0), "z": (1, 0),
    "s": (1, 0), "sdg": (1, 0), "t": (1, 0), "tdg": (1, 0),
    "rx": (1, 1), "ry": (1, 1), "rz": (1, 1), "p": (1, 1),
    "cx": (2, 0), "cz": (2, 0), "swap": (2, 0),
    "measure": (0, 0),
}

MEASURE = "measure"


class QasmUnsupported(ValueError):
    """The reader will not run this circuit, and says which part it will not run."""


@dataclass(frozen=True)
class Op:
    name: str
    qubits: Tuple[int, ...] = ()
    params: Tuple[float, ...] = ()


@dataclass(frozen=True)
class Circuit:
    """A circuit the simulator can run. `measured` is the qubits a result's bitstring reports, left to right
    in the order they were measured, so a count key reads the same way the program wrote it."""
    qubits: int
    ops: Tuple[Op, ...] = ()
    measured: Tuple[int, ...] = ()
    source_digest: str = ""

    @property
    def depth(self) -> int:
        return sum(1 for op in self.ops if op.name != MEASURE)


_HEADER = re.compile(r"^OPENQASM\s+([0-9](?:\.[0-9])?)\s*;", re.MULTILINE)
_QUBIT_DECL = re.compile(r"^\s*qubit\s*\[\s*(\d+)\s*\]\s*([A-Za-z_]\w*)\s*;", re.MULTILINE)
_BIT_DECL = re.compile(r"^\s*bit\s*\[\s*(\d+)\s*\]\s*([A-Za-z_]\w*)\s*;", re.MULTILINE)
_INCLUDE = re.compile(r'^\s*include\s+"[^"]+"\s*;', re.MULTILINE)
_INDEXED = re.compile(r"^([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]$")


def _angle(text: str) -> float:
    """An angle as OpenQASM writes one: a number, or a simple multiple or fraction of pi."""
    t = text.strip().replace(" ", "")
    if not t:
        raise QasmUnsupported("an empty angle")
    try:
        return float(t)
    except ValueError:
        pass
    m = re.fullmatch(r"(-?)(?:(\d+(?:\.\d+)?)\*)?pi(?:/(\d+(?:\.\d+)?))?", t)
    if not m:
        raise QasmUnsupported(f"the angle {text.strip()!r} is not a number or a simple multiple of pi")
    sign = -1.0 if m.group(1) else 1.0
    value = math.pi * (float(m.group(2)) if m.group(2) else 1.0)
    if m.group(3):
        value /= float(m.group(3))
    return sign * value


def read_openqasm3(text: str) -> Circuit:
    import hashlib

    header = _HEADER.search(text or "")
    if not header:
        raise QasmUnsupported("no 'OPENQASM 3;' header: this reader speaks OpenQASM 3 only")
    version = header.group(1)
    if not version.startswith("3"):
        raise QasmUnsupported(f"OpenQASM {version} is not OpenQASM 3; this reader speaks 3 only")

    body = _HEADER.sub("", text)
    body = _INCLUDE.sub("", body)

    qubit_regs: Dict[str, Tuple[int, int]] = {}   # name -> (offset, width)
    width = 0
    for size, name in _QUBIT_DECL.findall(body):
        qubit_regs[name] = (width, int(size))
        width += int(size)
    if not qubit_regs:
        raise QasmUnsupported("no 'qubit[n] name;' declaration: the reader needs one qubit register")
    bit_regs = {name: int(size) for size, name in _BIT_DECL.findall(body)}
    body = _QUBIT_DECL.sub("", body)
    body = _BIT_DECL.sub("", body)

    def resolve(token: str) -> List[int]:
        token = token.strip()
        m = _INDEXED.match(token)
        if m:
            name, index = m.group(1), int(m.group(2))
            if name not in qubit_regs:
                raise QasmUnsupported(f"{name!r} is not a declared qubit register")
            offset, size = qubit_regs[name]
            if index >= size:
                raise QasmUnsupported(f"{name}[{index}] is outside {name}[{size}]")
            return [offset + index]
        if token in qubit_regs:
            offset, size = qubit_regs[token]
            return list(range(offset, offset + size))
        raise QasmUnsupported(f"{token!r} is not a declared qubit register")

    ops: List[Op] = []
    measured: List[int] = []
    for raw in body.split(";"):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        line = line.split("//", 1)[0].strip()
        if not line:
            continue

        if line.startswith("barrier"):
            continue

        if MEASURE in line:
            target = line.split(MEASURE, 1)[1].strip()
            if not target:
                raise QasmUnsupported("a measure with no target")
            for q in resolve(target):
                if q not in measured:
                    measured.append(q)
            continue

        head, _, args = line.partition(" ")
        gate = head.strip().lower()
        params: Tuple[float, ...] = ()
        if "(" in gate:
            gate, _, rest = gate.partition("(")
            args = (rest + " " + args)
            inside, _, after = args.partition(")")
            params = tuple(_angle(p) for p in inside.split(",") if p.strip())
            args = after
            gate = gate.strip().lower()

        if gate not in SUPPORTED_GATES or gate == MEASURE:
            raise QasmUnsupported(f"the gate {gate!r} is not one this reader runs; it runs "
                                  f"{', '.join(sorted(g for g in SUPPORTED_GATES if g != MEASURE))}")
        want_qubits, want_params = SUPPORTED_GATES[gate]
        targets: List[int] = []
        for token in args.split(","):
            if token.strip():
                targets.extend(resolve(token))
        if len(targets) != want_qubits:
            raise QasmUnsupported(f"the gate {gate!r} takes {want_qubits} qubit(s), not {len(targets)}")
        if len(params) != want_params:
            raise QasmUnsupported(f"the gate {gate!r} takes {want_params} angle(s), not {len(params)}")
        ops.append(Op(gate, tuple(targets), params))

    if not measured:
        raise QasmUnsupported("the circuit measures nothing, so it has no counts: add a measure")
    ops.append(Op(MEASURE, tuple(measured)))
    digest = "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    return Circuit(qubits=width, ops=tuple(ops), measured=tuple(measured), source_digest=digest)
