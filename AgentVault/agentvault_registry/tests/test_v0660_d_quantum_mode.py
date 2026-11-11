"""V0660 (d): QUANTUM_WORKLOADS_MODE, the frame switch for quantum workloads (core/quantum_mode.py).

The source default is off, and any value that is not off, shadow or on reads as off, so a typo never switches hosting on.
The mode is read on every call: a recreate with a new value takes effect without a code change. Both V0660 orders read
the switch through quantum_workloads_mode(), never the environment directly.

RED on 4b79322d7 (origin/v0658/cut): the module does not exist.
"""
from __future__ import annotations

import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


@pytest.mark.parametrize("raw,mode", [
    (None, "off"), ("", "off"), ("off", "off"), ("shadow", "shadow"), ("on", "on"),
    (" ON ", "on"), ("Shadow", "shadow"), ("enforce", "off"), ("true", "off"), ("1", "off"), ("o n", "off"),
])
def test_the_mode_reads_the_switch_and_anything_else_is_off(monkeypatch, raw, mode):
    from agentvault_registry.core.quantum_mode import quantum_workloads_mode
    if raw is None:
        monkeypatch.delenv("QUANTUM_WORKLOADS_MODE", raising=False)
    else:
        monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", raw)
    assert quantum_workloads_mode() == mode


def test_the_three_modes_and_off_first():
    from agentvault_registry.core.quantum_mode import MODES
    assert MODES == ("off", "shadow", "on")


def test_the_mode_is_read_on_every_call(monkeypatch):
    from agentvault_registry.core.quantum_mode import quantum_workloads_mode
    monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", "on")
    assert quantum_workloads_mode() == "on"
    monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", "shadow")
    assert quantum_workloads_mode() == "shadow"
    monkeypatch.delenv("QUANTUM_WORKLOADS_MODE")
    assert quantum_workloads_mode() == "off"


def test_nothing_else_reads_the_switch_from_the_environment():
    # one reader: a second os.environ read of the name is a second, drifting answer
    readers = []
    for p in SRC.rglob("*.py"):
        text = p.read_text(encoding="utf-8", errors="ignore")
        if 'environ.get("QUANTUM_WORKLOADS_MODE"' in text or 'getenv("QUANTUM_WORKLOADS_MODE"' in text:
            readers.append(str(p.relative_to(SRC)))
    assert sorted(readers) == ["core/quantum_mode.py"]
