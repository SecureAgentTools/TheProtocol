"""The QPU proxy recipe's three plugins (V0660 (c)), in the core's existing kinds and with no core change.

    sink   quantum_submit   a job arrives from TheProtocol -> submitted to the backend, metered as it runs
    source quantum_results  finished jobs -> Records, the job id as the stable record id
    action quantum_report   the counts and the receipt posted back, with the metering claim beside them

Asynchronous on purpose. A real QPU queues — the card extension carries `queue.status` and
`estimated_wait_seconds` — so a caller that blocked on a circuit would be modelling a machine that does
not exist. It also means the recipe needs no fourth plugin kind: the core has source, action and sink,
and this is exactly the shape those three were built for.

`quantum_report` SUBCLASSES the core's AttestationAction rather than restating it, because that class
holds the status ladder this rail really needs: a 409 whose body says the attestation already landed is a
success, a 422 whose body says the idempotency key is still claimed is a retry, and 408/425/429/5xx are
retries with the server's own Retry-After. Re-deriving that ladder here would have been a second copy to
get wrong.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Mapping, Optional

from ..actions_builtin import AttestationAction
from ..plugins import Event, Outcome, Record, Refused, Sink, Source
from .backends import backend_from
from .jobs import FINISHED, JobStore
from .meter import METERING_CIRCUIT, MeterRefused, ShotMeter
from .qasm import QasmUnsupported

DEFAULT_ATTESTATION_TYPE = "quantum.job.receipt"
CURSOR = "quantum.results.cursor"


def _dig(data: Mapping[str, Any], path: str) -> Any:
    node: Any = data
    for part in str(path).split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


class _Backed:
    """The backend, the store and the meter, built from one plugin's own config section.

    Built lazily and idempotently rather than only in start(). The core calls start() before any other
    method, but the plugin contract harness constructs a plugin and calls deliver() straight away, and a
    plugin that works for one of its two callers is a plugin that is broken for the other."""

    def _open(self) -> None:
        if getattr(self, "_opened", False):
            return
        cfg = dict(self.config)                                        # type: ignore[attr-defined]
        self.backend = backend_from(cfg.get("backend") or {})
        self.meter = ShotMeter(dir=str(cfg.get("meter_dir") or cfg.get("dir") or "."),
                               agent_did=self.ctx.agent_did)          # type: ignore[attr-defined]
        self.store = JobStore(dir=str(cfg.get("dir") or "."), backend=self.backend, meter=self.meter)
        self._opened = True


class QuantumSubmitSink(Sink, _Backed):
    name = "quantum_submit"
    description = "Submit an arriving quantum job to the backend and meter the shots as they run"
    config_schema = {
        "type": "object",
        "required": ["dir", "backend"],
        "additionalProperties": False,
        "properties": {
            "dir": {"type": "string", "minLength": 1},
            "meter_dir": {"type": "string", "minLength": 1},
            "backend": {"type": "object"},
            "program_field": {"type": "string", "default": "program"},
            "shots_field": {"type": "string", "default": "shots"},
            "job_id_field": {"type": "string", "default": ""},
            "max_shots": {"type": "integer", "minimum": 1},
            "seed": {"type": "integer"},
        },
    }

    async def start(self) -> None:
        self._open()

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        self._open()
        data = dict(event.data or {})
        program = _dig(data, self.config.get("program_field") or "program")
        shots_raw = _dig(data, self.config.get("shots_field") or "shots")
        field = self.config.get("job_id_field") or ""
        job_id = str(_dig(data, field) or "") if field else (event.event_id or key)

        if not isinstance(program, str) or not program.strip():
            raise Refused(f"the event carries no OpenQASM 3 program at "
                          f"{self.config.get('program_field') or 'program'!r}: nothing to run")
        try:
            shots = int(shots_raw)
        except (TypeError, ValueError):
            raise Refused(f"the event's shot count {shots_raw!r} is not a number")
        ceiling = self.config.get("max_shots")
        if ceiling is not None and shots > int(ceiling):
            raise Refused(f"{shots} shots is past this recipe's ceiling of {ceiling}")

        if dry_run:
            return Outcome.dry(f"would submit job {job_id} for {shots} shots",
                               job_id=job_id, shots=shots, backend=self.backend.id)

        try:
            job = await self.store.submit(job_id, program, shots=shots,
                                          seed=self.config.get("seed"))
        except (QasmUnsupported, MeterRefused) as exc:
            # a circuit this backend will not run, or a shot count the meter will not stand behind, does
            # not get better on a retry: it is a refusal, and the dead letters keep the reason
            raise Refused(str(exc))
        if job.status == "failed":
            raise Refused(f"job {job_id} failed on the backend: {job.error}")
        return Outcome.done(job.job_id, f"submitted job {job.job_id} ({job.shots} shots)",
                            status=job.status, backend=job.backend_id)


class QuantumResultSource(Source, _Backed):
    name = "quantum_results"
    description = "Yield each finished job once: its counts, its shots and its digests, never its circuit"
    config_schema = {
        "type": "object",
        "required": ["dir", "backend"],
        "additionalProperties": False,
        "properties": {
            "dir": {"type": "string", "minLength": 1},
            "meter_dir": {"type": "string", "minLength": 1},
            "backend": {"type": "object"},
        },
    }

    async def start(self) -> None:
        self._open()

    async def records(self) -> AsyncIterator[Record]:
        self._open()
        done = set(await self.ctx.state.get(CURSOR) or [])
        for job in self.store.jobs(status=FINISHED):
            if job.job_id in done:
                continue
            yield Record(source=self.name, record_id=job.job_id, payload=job.record_payload())

    async def committed(self, record: Record) -> None:
        done = list(await self.ctx.state.get(CURSOR) or [])
        if record.record_id not in done:
            done.append(record.record_id)
            await self.ctx.state.set(CURSOR, done)

    async def rewind(self, point: str) -> None:
        """`all` reads every finished job again; a job id reads that one again. The core's keys stop a
        record already in the outbox from being sent twice, so this is safe to use after a fix."""
        if str(point).strip().lower() in ("all", "*", ""):
            await self.ctx.state.set(CURSOR, [])
            return
        done = [j for j in (await self.ctx.state.get(CURSOR) or []) if j != str(point)]
        await self.ctx.state.set(CURSOR, done)


class QuantumReportAction(AttestationAction):
    name = "quantum_report"
    description = "Report one finished job: its counts and receipt facts, with the metering claim beside them"
    config_schema = {
        "type": "object",
        "required": ["meter_dir"],
        "additionalProperties": False,
        "properties": {
            "meter_dir": {"type": "string", "minLength": 1},
            "attestation_type": {"type": "string", "minLength": 1, "maxLength": 120},
            "target_agent_did": {"type": "string", "pattern": "^did:"},
            "report_units_field": {"type": "string", "default": "shots"},
        },
    }

    def request(self, mapped: Mapping[str, Any], key: str) -> dict:
        claim = dict(mapped)
        job_id = str(claim.get("job_id") or "")
        units_field = self.config.get("report_units_field") or "shots"
        reported = claim.get(units_field)

        meter = ShotMeter(dir=str(self.config["meter_dir"]), agent_did=self.ctx.agent_did)
        metering: Dict[str, Any]
        try:
            shot_claim = meter.claim(job_id, reported_units=int(reported))
            metering = {
                "circuit_id": shot_claim.circuit_id,
                "public_inputs": shot_claim.public,
                "log_commitment": shot_claim.log_commitment,
                "log_commitment_state": shot_claim.log_commitment_state,
                "log_commitment_reason": shot_claim.log_commitment_reason,
            }
        except (MeterRefused, TypeError, ValueError) as exc:
            # The report still goes, and it SAYS the shots are unproven. Dropping the claim silently would
            # publish a number with no evidence behind it and no sign that any was missing.
            metering = {"circuit_id": METERING_CIRCUIT,
                        "state": "NOT_PROVEN", "reason": str(exc)}

        body = {
            "target_agent_did": self.config.get("target_agent_did") or self.ctx.agent_did,
            "attestation_type": self.config.get("attestation_type") or DEFAULT_ATTESTATION_TYPE,
            "attestation_data": {"claim": claim, "record": key, "metering": metering},
            "metadata": {"proxy": self.ctx.proxy_name, "record": key},
        }
        return body
