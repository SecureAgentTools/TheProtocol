"""V0660 (c): the recipe's three plugins, against the core's own contract harness.

The harness is used rather than hand-rolled assertions because it holds rules this recipe would otherwise
have to remember: a dry run sends nothing, every write carries the record's key as its Idempotency-Key, a
4xx is raised as Refused and a 5xx as Retry, and a source resumes from its cursor instead of re-yielding.
"""
from __future__ import annotations

import pytest

from theprotocol.proxy.plugins import Event, Record, Refused
from theprotocol.proxy.quantum.jobs import FINISHED, JobStore
from theprotocol.proxy.quantum.plugins import (
    QuantumReportAction,
    QuantumResultSource,
    QuantumSubmitSink,
)
from theprotocol.proxy.testing import (
    FakeContext,
    FakeResponse,
    check_action,
    check_action_refusals,
    check_class,
    check_resume,
    check_sink,
    check_source,
)

BELL = 'OPENQASM 3;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[2] c;\nh q[0];\ncx q[0], q[1];\nc = measure q;\n'


def cfg(tmp_path, **kw):
    out = {"dir": str(tmp_path), "backend": {"kind": "simulator", "id": "sim-1", "qubits": 4}, "seed": 3}
    out.update(kw)
    return out


def job_event(job_id="job-1", shots=64, program=BELL):
    return Event(event_id=job_id, event_type="QuantumJobSubmitted", aggregate_id=job_id,
                 data={"program": program, "shots": shots})


async def seed(tmp_path, n=5, shots=16):
    """Put n finished jobs in the store, through the sink, so a source has something real to read."""
    sink = QuantumSubmitSink(cfg(tmp_path), FakeContext())
    await sink.start()
    for i in range(n):
        await sink.deliver(job_event(f"job-{i}", shots=shots), key=f"k-{i}", dry_run=False)
    return sink


class TestTheyKeepTheInterface:
    def test_the_sink(self):
        check_class(QuantumSubmitSink, "sink")

    def test_the_source(self):
        check_class(QuantumResultSource, "source")

    def test_the_action(self):
        check_class(QuantumReportAction, "action")

    def test_the_action_declares_the_permission_it_needs(self):
        """It rides the attestation rail, which needs reputation.signal; the owner grants the attestor role,
        which carries that and nothing else."""
        assert "reputation.signal" in QuantumReportAction.needs
        assert QuantumReportAction.moves_value is False, "reporting a job moves no value"


class TestTheSink:
    async def test_it_keeps_the_sink_contract(self, tmp_path):
        store = JobStore(dir=str(tmp_path), backend=__import__(
            "theprotocol.proxy.quantum.backends", fromlist=["x"]).SimulatorBackend(
            {"id": "sim-1", "qubits": 4}))
        await check_sink(QuantumSubmitSink, cfg(tmp_path), job_event(),
                         delivered=lambda: store.jobs(status=FINISHED))

    async def test_it_runs_and_finishes_a_job(self, tmp_path):
        sink = QuantumSubmitSink(cfg(tmp_path), FakeContext())
        await sink.start()
        out = await sink.deliver(job_event(shots=128), key="k1", dry_run=False)
        assert out.status == "done"
        job = sink.store.get("job-1")
        assert job.status == FINISHED and job.shots == 128
        assert set(job.counts) <= {"00", "11"}

    async def test_it_meters_the_shots_as_the_job_runs(self, tmp_path):
        """The meter's entry has to exist before any report, which is the ordering the proof depends on."""
        sink = QuantumSubmitSink(cfg(tmp_path), FakeContext())
        await sink.start()
        await sink.deliver(job_event(shots=50), key="k1", dry_run=False)
        entries = sink.meter.entries()
        assert [e.job_id for e in entries] == ["job-1"]
        assert entries[0].logged_units == 50

    async def test_an_event_with_no_program_is_refused(self, tmp_path):
        sink = QuantumSubmitSink(cfg(tmp_path), FakeContext())
        await sink.start()
        bad = Event(event_id="job-x", event_type="T", aggregate_id="a", data={"shots": 8})
        with pytest.raises(Refused) as e:
            await sink.deliver(bad, key="k", dry_run=False)
        assert "program" in str(e.value)

    async def test_a_shot_count_that_is_not_a_number_is_refused(self, tmp_path):
        sink = QuantumSubmitSink(cfg(tmp_path), FakeContext())
        await sink.start()
        bad = Event(event_id="job-x", event_type="T", aggregate_id="a",
                    data={"program": BELL, "shots": "lots"})
        with pytest.raises(Refused) as e:
            await sink.deliver(bad, key="k", dry_run=False)
        assert "lots" in str(e.value)

    async def test_shots_past_the_ceiling_are_refused(self, tmp_path):
        sink = QuantumSubmitSink(cfg(tmp_path, max_shots=100), FakeContext())
        await sink.start()
        with pytest.raises(Refused) as e:
            await sink.deliver(job_event(shots=101), key="k", dry_run=False)
        assert "101" in str(e.value) and "100" in str(e.value)

    async def test_a_circuit_it_cannot_run_is_refused_not_retried(self, tmp_path):
        """A gate this backend will not run does not get better on a retry: Refused, so the record lands in
        the dead letters with the reason instead of spinning until the breaker stops the mapping."""
        sink = QuantumSubmitSink(cfg(tmp_path), FakeContext())
        await sink.start()
        with pytest.raises(Refused) as e:
            await sink.deliver(job_event(program=BELL.replace("h q[0];", "ccx q[0], q[1], q[0];")),
                               key="k", dry_run=False)
        assert "ccx" in str(e.value)

    async def test_the_same_job_runs_once(self, tmp_path):
        """A replayed event must not re-run paid work."""
        sink = QuantumSubmitSink(cfg(tmp_path), FakeContext())
        await sink.start()
        await sink.deliver(job_event(shots=32), key="k1", dry_run=False)
        first = sink.store.get("job-1").finished_at
        await sink.deliver(job_event(shots=32), key="k1", dry_run=False)
        assert sink.store.get("job-1").finished_at == first
        assert len(sink.meter.entries()) == 1


class TestTheSource:
    async def test_it_keeps_the_source_contract(self, tmp_path):
        await seed(tmp_path, n=5)
        await check_source(QuantumResultSource, cfg(tmp_path), limit=3)

    async def test_it_resumes_from_its_cursor(self, tmp_path):
        await seed(tmp_path, n=5)
        await check_resume(QuantumResultSource, cfg(tmp_path), first=2, limit=5)

    async def test_it_yields_a_finished_job_once(self, tmp_path):
        await seed(tmp_path, n=1)
        src = QuantumResultSource(cfg(tmp_path), FakeContext())
        await src.start()
        first = [r async for r in src.records()]
        assert [r.record_id for r in first] == ["job-0"]
        for r in first:
            await src.committed(r)
        assert [r async for r in src.records()] == []

    async def test_what_it_yields_carries_the_counts_and_never_the_circuit(self, tmp_path):
        """The extension's data rule: the ledger keeps hashes and verdicts, never circuits."""
        await seed(tmp_path, n=1, shots=24)
        src = QuantumResultSource(cfg(tmp_path), FakeContext())
        await src.start()
        record = [r async for r in src.records()][0]
        assert record.payload["shots"] == 24
        assert record.payload["counts"]
        assert record.payload["circuit_digest"].startswith("sha256:")
        assert "program" not in record.payload and "qasm" not in record.payload

    async def test_rewind_all_reads_every_finished_job_again(self, tmp_path):
        await seed(tmp_path, n=2)
        src = QuantumResultSource(cfg(tmp_path), FakeContext())
        await src.start()
        for r in [r async for r in src.records()]:
            await src.committed(r)
        assert [r async for r in src.records()] == []
        await src.rewind("all")
        assert len([r async for r in src.records()]) == 2


class TestTheAction:
    async def test_it_keeps_the_action_contract(self, tmp_path):
        await seed(tmp_path, n=1, shots=16)
        mapped = {"job_id": "job-0", "shots": 16, "counts": {"00": 8, "11": 8}}
        await check_action(QuantumReportAction, {"meter_dir": str(tmp_path)}, mapped,
                           answers=lambda m, p, r: FakeResponse(201, {"attestation_id": "att-1"}))

    async def test_it_raises_refused_and_retry_as_the_contract_demands(self, tmp_path):
        await seed(tmp_path, n=1, shots=16)
        await check_action_refusals(QuantumReportAction, {"meter_dir": str(tmp_path)},
                                    {"job_id": "job-0", "shots": 16})

    async def test_the_report_carries_the_metering_claim(self, tmp_path):
        await seed(tmp_path, n=1, shots=16)
        ctx = FakeContext(answers=lambda m, p, r: FakeResponse(201, {"attestation_id": "att-1"}))
        action = QuantumReportAction({"meter_dir": str(tmp_path)}, ctx)
        await action.perform({"job_id": "job-0", "shots": 16}, key="k1", dry_run=False)
        body = ctx.calls[0]["json"]
        metering = body["attestation_data"]["metering"]
        assert metering["circuit_id"] == "accurateResourceUsagePolicy/v2.0.0"
        assert metering["public_inputs"]["reported_units"] == 16
        assert metering["public_inputs"]["transaction_ref"] != 0
        assert metering["log_commitment_state"] == "NOT_COMPUTED"

    async def test_an_unmetered_job_is_reported_as_not_proven_rather_than_silently(self, tmp_path):
        """The report still goes; what it must not do is publish a shot count with no evidence behind it and
        no sign that any was missing."""
        ctx = FakeContext(answers=lambda m, p, r: FakeResponse(201, {"attestation_id": "att-1"}))
        action = QuantumReportAction({"meter_dir": str(tmp_path)}, ctx)
        await action.perform({"job_id": "never-metered", "shots": 16}, key="k1", dry_run=False)
        metering = ctx.calls[0]["json"]["attestation_data"]["metering"]
        assert metering["state"] == "NOT_PROVEN"
        assert "never-metered" in metering["reason"]
        assert "log_commitment" not in metering

    async def test_the_private_figures_never_reach_the_report(self, tmp_path):
        await seed(tmp_path, n=1, shots=16)
        ctx = FakeContext(answers=lambda m, p, r: FakeResponse(201, {"attestation_id": "att-1"}))
        action = QuantumReportAction({"meter_dir": str(tmp_path)}, ctx)
        await action.perform({"job_id": "job-0", "shots": 16}, key="k1", dry_run=False)
        text = __import__("json").dumps(ctx.calls[0]["json"])
        assert "salt" not in text, "the salt is a private input of the circuit"
        assert "logged_units" not in text, "the meter log's figure is private; the report carries the claim"


class TestTheyAreWiredIn:
    """A plugin that exists and is not registered is a plugin nobody can name in a spec: the recipe would
    be present in the package and absent from the product. This is the cheapest test here and the one that
    catches the whole thing being unreachable."""

    def test_all_three_are_in_BUILTINS(self):
        from theprotocol.proxy.plugins import BUILTINS

        assert BUILTINS["sink"].get("quantum_submit") == "theprotocol.proxy.quantum.plugins:QuantumSubmitSink"
        assert BUILTINS["source"].get("quantum_results") == "theprotocol.proxy.quantum.plugins:QuantumResultSource"
        assert BUILTINS["action"].get("quantum_report") == "theprotocol.proxy.quantum.plugins:QuantumReportAction"

    def test_the_core_really_loads_each_one_by_its_spec_name(self):
        """Registration is a string; this follows the string the way the core does, so a typo in a module
        path or a renamed class fails here instead of at a provider's first run."""
        from theprotocol.proxy.plugins import load

        assert load("sink", "quantum_submit") is QuantumSubmitSink
        assert load("source", "quantum_results") is QuantumResultSource
        assert load("action", "quantum_report") is QuantumReportAction
