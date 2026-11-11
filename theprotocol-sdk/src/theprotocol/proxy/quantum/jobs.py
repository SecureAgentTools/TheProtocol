"""The job store (V0660 (c)): submitted and finished quantum jobs on disk, beside the meter's log.

A real QPU queues, so the recipe is asynchronous by construction: a job is submitted, it finishes later,
and its result is read and reported then. The built-in simulator finishes immediately, which the store
models honestly as a queue of depth one rather than pretending a result came back from a submit call.

One file per job, so an operator can read the queue with `ls` and `cat` while it runs.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .backends import Backend, Result
from .meter import MeterRefused, ShotMeter
from .qasm import QasmUnsupported, read_openqasm3

SUBMITTED, FINISHED, FAILED = "submitted", "finished", "failed"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Job:
    job_id: str
    status: str
    shots: int
    backend_id: str
    circuit_digest: str = ""
    counts: Optional[Dict[str, int]] = None
    submitted_at: str = ""
    finished_at: str = ""
    error: str = ""
    seed: Optional[int] = None

    def record_payload(self) -> Dict[str, Any]:
        """What the source yields: the facts a receipt is built from, and never the circuit itself (the
        ledger keeps hashes and verdicts, never circuits — the extension's own data rule)."""
        return {"job_id": self.job_id, "status": self.status, "shots": self.shots,
                "backend_id": self.backend_id, "circuit_digest": self.circuit_digest,
                "counts": self.counts, "submitted_at": self.submitted_at,
                "finished_at": self.finished_at, "error": self.error}


class JobStore:
    def __init__(self, dir: str, backend: Backend, meter: Optional[ShotMeter] = None):
        self.dir = Path(dir)
        (self.dir / "jobs").mkdir(parents=True, exist_ok=True)
        self.backend = backend
        self.meter = meter

    def _path(self, job_id: str) -> Path:
        if not _SAFE_ID.match(job_id or ""):
            raise QasmUnsupported(f"{job_id!r} is not a usable job id: letters, digits and . _ : - only")
        return self.dir / "jobs" / f"{job_id}.json"

    def get(self, job_id: str) -> Optional[Job]:
        path = self._path(job_id)
        if not path.exists():
            return None
        return Job(**json.loads(path.read_text(encoding="utf-8")))

    def _write(self, job: Job) -> None:
        path = self._path(job.job_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(job), sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def jobs(self, status: Optional[str] = None) -> List[Job]:
        out: List[Job] = []
        for path in sorted((self.dir / "jobs").glob("*.json")):
            job = Job(**json.loads(path.read_text(encoding="utf-8")))
            if status is None or job.status == status:
                out.append(job)
        return out

    async def submit(self, job_id: str, program: str, *, shots: int, seed: Optional[int] = None) -> Job:
        """Submit one job. Repeating a submit with the same id returns the job already there, because the
        core's exactly-once promise has to hold here too: a replayed event must not re-run paid work."""
        existing = self.get(job_id)
        if existing is not None:
            return existing

        circuit = read_openqasm3(program)        # refuses by name before anything is metered or charged
        job = Job(job_id=job_id, status=SUBMITTED, shots=int(shots), backend_id=self.backend.id,
                  circuit_digest=circuit.source_digest, submitted_at=_now(), seed=seed)
        self._write(job)

        try:
            result: Result = await self.backend.run(circuit, shots=int(shots), seed=seed)
        except (QasmUnsupported, MeterRefused) as exc:
            job.status, job.error, job.finished_at = FAILED, str(exc), _now()
            self._write(job)
            return job

        # Metered at RUN time, before the result is readable, so the commitment cannot be chosen to match a
        # later report. A meter that refuses stops the job: an unmetered result is one nobody can prove.
        if self.meter is not None:
            self.meter.record(job_id, shots=result.shots)

        job.status, job.counts, job.finished_at = FINISHED, dict(result.counts), _now()
        job.shots = result.shots
        self._write(job)
        return job
