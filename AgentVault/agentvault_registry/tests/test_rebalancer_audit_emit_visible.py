"""§BATCH9 / S4 pass 5 — the canary rebalancer's audit emit failure was a DEBUG line and no counter."""
import logging

from agentvault_registry.background_tasks import canary_rebalancer as cr


class _Boom:
    """An emitter double that RECEIVES the call (recorded under `received`, the name the doubles gate reads) and then fails."""
    def __init__(self):
        self.received = []

    async def emit(self, **kw):
        self.received.append(kw)
        raise RuntimeError("ledger down")


async def test_a_failed_audit_emit_is_warned_and_counted(monkeypatch, caplog):
    import agentvault_registry.event_emitter as ee
    boom = _Boom()
    monkeypatch.setattr(ee, "get_event_emitter", lambda: boom)
    calls = []

    class _Ctr:
        def labels(self, **kw):
            calls.append(kw); return self
        def inc(self):
            calls.append("inc")
    monkeypatch.setattr(cr, "REBALANCE_ERRORS_TOTAL", _Ctr())
    with caplog.at_level(logging.WARNING):
        await cr._emit_audit_event("CanaryRebalancerFunded", "did:x", {"a": 1}, idempotency_key="k")
    assert boom.received == [{"event_type": "CanaryRebalancerFunded", "aggregate_id": "did:x", "aggregate_type": "CanaryAgent",
                              "data": {"a": 1}, "idempotency_key": "k"}]   # the attempt reached the emitter, then failed
    assert any("audit emit FAILED" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
    assert {"home_kind": "audit", "reason": "emit_failed"} in calls and "inc" in calls
