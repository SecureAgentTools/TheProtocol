"""The shot meter (V0660 (c)): a hash-linked log of what each job really ran, committed when it runs.

It serves accurateResourceUsagePolicy/v2.0.0, whose contract was read from the registry, not guessed:

    public:  max_discrepancy_bps (u32), transaction_ref (Field, non-zero), reported_units (u64)
    private: logged_units (u64), salt (Field)
    output:  log_commitment = Poseidon2(DOMAIN, transaction_ref, logged_units, salt)
    rule:    |reported_units - logged_units| * 10000 <= logged_units * max_discrepancy_bps
    policy:  max_discrepancy_bps at_most 100

Two things follow from that contract and shape this whole module.

**The commitment has to exist before the report.** The circuit's own Limits note says a verifier "should
compare log_commitment with one the meter published", and the reason is that a provider free to pick
logged_units after seeing its own report can always satisfy the rule. So `record()` commits when the work
runs and `claim()` refuses a job that was never metered. That ordering is the only thing here that an
adversary cannot work around, so it is the property with the most tests on it.

**We will not write a log_commitment we did not compute.** Poseidon2 over BN254 comes from the circuit,
through nargo and bb, which are not dependencies of this SDK. A claim therefore carries the exact
pre-image and reports the commitment as NOT_COMPUTED. A plausible-looking hash of our own under the name
the circuit uses would be worse than an absent one: it would be compared against the real commitment and
fail somewhere far from the mistake.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

# "tp.resource_usage.v2", as the circuit's own global states it
DOMAIN_RESOURCE_USAGE_V2 = 0x74702E7265736F757263655F75736167652E7632
POLICY_MAX_DISCREPANCY_BPS = 100          # the registry's policy: at_most 100
REFERENCE_DOMAIN = b"tp.attestation.ref.v1|"
BN254_FIELD_BYTES = 31                    # 31 bytes always fits the field; the reference is defined over them
METERING_CIRCUIT = "accurateResourceUsagePolicy/v2.0.0"   # the card advertises this, the claim cites it
LOG_FILE = "shots.jsonl"
FORMAT = "theprotocol-quantum-meter/1"


class MeterRefused(ValueError):
    """The meter will not do this, and says which rule stopped it."""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def derive_reference(agent_did: str, label: str) -> int:
    """The reference the registry requires of a v2 proof: the first 31 bytes of
    SHA-256("tp.attestation.ref.v1|" + did + "|" + label), big-endian.

    It is derived rather than chosen so that a proof made for one agent does not verify when another agent
    submits it. A reference we invented would be refused by the registry, so this is not a detail."""
    if not agent_did:
        raise MeterRefused("a reference needs the agent's DID: the registry binds a proof to its submitter")
    if not label:
        raise MeterRefused("a reference needs a label: the job id")
    raw = hashlib.sha256(REFERENCE_DOMAIN + agent_did.encode("utf-8") + b"|" + label.encode("utf-8")).digest()
    value = int.from_bytes(raw[:BN254_FIELD_BYTES], "big")
    return value or 1          # the circuit requires non-zero; SHA-256 of 31 zero bytes is not reachable


@dataclass(frozen=True)
class MeterEntry:
    job_id: str
    logged_units: int
    transaction_ref: int
    salt: str
    committed_at: str
    prev: str = ""
    hash: str = ""

    def unhashed(self) -> Dict[str, Any]:
        return {"v": 1, "job_id": self.job_id, "logged_units": self.logged_units,
                "transaction_ref": str(self.transaction_ref), "salt": self.salt,
                "committed_at": self.committed_at, "prev": self.prev}


@dataclass(frozen=True)
class ShotClaim:
    """What a provider hands a prover, and what it must not hand anyone."""
    job_id: str
    public: Dict[str, Any]
    preimage: Dict[str, Any]
    log_commitment: Optional[str] = None
    log_commitment_state: str = "NOT_COMPUTED"
    log_commitment_reason: str = ""
    circuit_id: str = METERING_CIRCUIT


class ShotMeter:
    """One meter per proxy. Its log is a file; its commitments are published as the work runs."""

    def __init__(self, dir: str, agent_did: str, *, max_discrepancy_bps: int = POLICY_MAX_DISCREPANCY_BPS):
        self.dir = Path(dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.agent_did = agent_did
        if max_discrepancy_bps > POLICY_MAX_DISCREPANCY_BPS:
            raise MeterRefused(f"{max_discrepancy_bps} bps is looser than the registry policy of "
                               f"{POLICY_MAX_DISCREPANCY_BPS} bps, which refuses such a proof")
        self.max_discrepancy_bps = int(max_discrepancy_bps)

    @property
    def path(self) -> Path:
        return self.dir / LOG_FILE

    # ── the log ──────────────────────────────────────────────────────────────────────────────────────────

    def entries(self) -> List[MeterEntry]:
        out: List[MeterEntry] = []
        if not self.path.exists():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out.append(MeterEntry(job_id=row["job_id"], logged_units=int(row["logged_units"]),
                                  transaction_ref=int(row["transaction_ref"]), salt=row["salt"],
                                  committed_at=row["committed_at"], prev=row.get("prev", ""),
                                  hash=row.get("hash", "")))
        return out

    def _append(self, entry: MeterEntry) -> None:
        row = entry.unhashed()
        row["hash"] = entry.hash
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(canonical(row) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def record(self, job_id: str, *, shots: int) -> MeterEntry:
        """Meter one job and commit to it, now, while the work is what it is."""
        if not job_id:
            raise MeterRefused("a metered job needs its id")
        if shots < 1:
            raise MeterRefused(f"{shots} shots is not a run")
        existing = {e.job_id: e for e in self.entries()}
        if job_id in existing:
            was = existing[job_id]
            if was.logged_units != shots:
                raise MeterRefused(f"job {job_id!r} is already metered at {was.logged_units} shots and this "
                                   f"says {shots}: a job's shot count does not change")
            return was              # exactly once, as the core promises for everything else
        rows = self.entries()
        prev = rows[-1].hash if rows else ""
        entry = MeterEntry(job_id=job_id, logged_units=int(shots),
                           transaction_ref=derive_reference(self.agent_did, job_id),
                           salt=secrets.token_hex(16), committed_at=_now(), prev=prev)
        entry = MeterEntry(**{**entry.__dict__, "hash": hashlib.sha256(canonical(entry.unhashed()).encode()).hexdigest()})
        self._append(entry)
        return entry

    def verify(self) -> List[str]:
        """Read the log back and say what is wrong with it, by name. An empty list means it holds."""
        problems: List[str] = []
        prev = ""
        seen = set()
        for i, entry in enumerate(self.entries(), start=1):
            want = hashlib.sha256(canonical(entry.unhashed()).encode()).hexdigest()
            if entry.hash != want:
                problems.append(f"line {i} ({entry.job_id}): its hash does not match its contents")
            if entry.prev != prev:
                problems.append(f"line {i} ({entry.job_id}): its prev does not link to the line before")
            if entry.job_id in seen:
                problems.append(f"line {i}: job {entry.job_id!r} is metered twice")
            seen.add(entry.job_id)
            prev = entry.hash
        return problems

    # ── the report ───────────────────────────────────────────────────────────────────────────────────────

    def claim(self, job_id: str, *, reported_units: int,
              max_discrepancy_bps: Optional[int] = None) -> ShotClaim:
        bps = self.max_discrepancy_bps if max_discrepancy_bps is None else int(max_discrepancy_bps)
        if bps > POLICY_MAX_DISCREPANCY_BPS:
            raise MeterRefused(f"{bps} bps is looser than the registry policy of {POLICY_MAX_DISCREPANCY_BPS} "
                               "bps, and the verifier refuses such a proof")
        entry = next((e for e in self.entries() if e.job_id == job_id), None)
        if entry is None:
            raise MeterRefused(f"job {job_id!r} was never metered, so there is no committed log to report "
                               "against; a commitment made now would prove nothing, because the logged "
                               "units could be chosen to match the report")
        if reported_units < 0:
            raise MeterRefused(f"{reported_units} is not a count of units")
        logged = entry.logged_units
        if abs(reported_units - logged) * 10_000 > logged * bps:
            raise MeterRefused(f"reporting {reported_units} units against {logged} in the log is outside the "
                               f"{bps} bps tolerance this proof would have to satisfy")
        return ShotClaim(
            job_id=job_id,
            public={"max_discrepancy_bps": bps, "transaction_ref": entry.transaction_ref,
                    "reported_units": int(reported_units)},
            preimage={"domain": DOMAIN_RESOURCE_USAGE_V2, "transaction_ref": entry.transaction_ref,
                      "logged_units": logged, "salt": entry.salt},
            log_commitment=None,
            log_commitment_state="NOT_COMPUTED",
            log_commitment_reason=("Poseidon2 over BN254 comes from the circuit through nargo and bb, which "
                                   "are not dependencies of this SDK: the pre-image is carried so a prover "
                                   "can compute it, and nothing is written under the circuit's name that we "
                                   "did not compute"),
        )
