"""§EMITKEY (2026-09-05) — a keyed emit must reach EventEmitter.emit(), the ONLY method that
takes `idempotency_key`. `emit_event()` is a compatibility wrapper with no key parameter; a call
that passes one raises TypeError inside the caller's own except-and-log, so the money moves and
the ledger never hears of it. Every bond / slash-waterfall / policy event shipped that way from the
last §REPBOND bake to V0219, on the sandbox and on production (0 attempts on prod so far).

Two gates:
  1. source: no `emit_event(` call anywhere under src/ passes `idempotency_key`
  2. binding: the bond service's keyword set binds to the REAL EventEmitter.emit signature, and a
     strict fake emitter (real signature, no tolerance) actually RECEIVES the event and its key.
"""
import inspect
import os
import pathlib
import re

import pytest

_HERE = pathlib.Path(__file__).resolve().parent.parent / "src" / "agentvault_registry"
SRC = pathlib.Path(os.environ.get("EMITKEY_SRC", str(_HERE)))
CALL = re.compile(r"\.emit_event\(")


def _arg_text(text: str, start: int) -> str:
    depth, i = 1, start
    while i < len(text) and depth:
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        i += 1
    return text[start:i - 1]


def test_no_emit_event_call_passes_an_idempotency_key():
    bad = []
    for f in sorted(SRC.rglob("*.py")):
        if "__pycache__" in str(f) or ".bak" in str(f):
            continue
        text = f.read_text()
        for m in CALL.finditer(text):
            if "idempotency_key" in _arg_text(text, m.end()):
                bad.append(f"{f.relative_to(SRC)}:{text[:m.start()].count(chr(10)) + 1}")
    assert not bad, f"emit_event() takes no idempotency_key — these keyed emits are silently lost: {bad}"


def test_bond_emit_kwargs_bind_to_the_real_emit_signature():
    from agentvault_registry.event_emitter import EventEmitter
    from agentvault_registry.services.reputation_bond import _emit_call_kwargs
    kwargs = _emit_call_kwargs("ReputationBondDeposited", "did:theprotocol:x", {"a": 1}, "repbond-dep-x")
    inspect.signature(EventEmitter.emit).bind(None, **kwargs)  # raises TypeError if the contract drifts


@pytest.mark.asyncio
async def test_bond_emit_reaches_a_strict_emitter(monkeypatch):
    """A fake with the REAL signatures: emit() records, emit_event() has no key parameter."""
    from agentvault_registry.event_emitter import EventEmitter
    from agentvault_registry.services import reputation_bond as rb

    received = []

    class Strict:
        pass

    async def emit(self, **kw):
        inspect.signature(EventEmitter.emit).bind(self, **kw)
        received.append(kw)
        return True

    async def emit_event(self, aggregate_id, event_type, event_data):
        raise AssertionError("emit_event() must not be used for keyed emits")

    Strict.emit = emit
    Strict.emit_event = emit_event
    monkeypatch.setattr("agentvault_registry.event_emitter.get_event_emitter", lambda: Strict())
    await rb._emit("ReputationBondDeposited", "did:theprotocol:strict", {"amount": "250"}, key="repbond-dep-strict")
    assert received and received[0]["idempotency_key"] == "repbond-dep-strict"
    assert received[0]["event_type"] == "ReputationBondDeposited"
