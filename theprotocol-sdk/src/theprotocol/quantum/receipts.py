"""Quantum job receipts and acceptance tests, version 1.0 (TheProtocol V0660 (b)).

One file, byte for byte the same in the registry (agentvault_registry/services/quantum_receipts.py) and in the SDK
(theprotocol/quantum/receipts.py), so the registry's check at a verify or release step and a buyer's offline check are
the same code. It imports only the standard library, and `cryptography` when a signature is made or checked. Both
repositories pin its SHA-256 in a test.

What it holds:
- the constants every reader of a quantum workload names: the receipt schema version, the signature algorithms this
  code can verify, the acceptance rungs, the acceptance-test templates with their rung and method, and the metering
  circuit (the registry card's quantum_workloads block and the agent card extension read them from here);
- the receipt chain: hash-linked steps from the submitted circuits to the verdict, each signed by its participant,
  with the algorithm and the public key inside the signed bytes;
- the acceptance agreement, made before a run, and the recomputation of its verdict from the evidence. An agreement
  may name the piece of work it settles (`work`: a rail, a reference and, for a milestone, its number), so the same
  terms agreed for two pieces of work are two agreements with two digests, and check_job(work=...) holds a chain to
  the work it is checked for.

The chain, step by step (in this order; the two marked optional may be left out):
    circuit_submitted   client, router       circuits_digest, format, shots, acceptance_digest
    circuit_compiled    compiler, provider   source_digest (= circuits_digest), compiled_digest, format   (optional)
    backend_bound       provider             backend, kind, calibration_digest (required for a qpu)
    run_executed        provider             shots (= the submitted shots), counts_digest
    result_reported     provider, mitigator  from_counts_digest (= counts_digest), result_digest           (optional)
    verdict             verifier             template, rung, passed, acceptance_digest, evidence_digest, the two rates

Every step is {receipt, job, seq, kind, prev, participant, role, at, body, signature}. `prev` is the digest of the step
before it (null for the first). The signature is {algorithm, public_key, value}: `value` signs SIGNING_PREFIX followed
by the canonical JSON of the step without `value`, so the algorithm and the key are signed too. A step's digest is the
SHA-256 of its canonical JSON with the value, so each link commits to the signature before it.

Canonical JSON: keys sorted, no spaces, UTF-8, ASCII keys only, and no floating-point numbers anywhere (a fraction is
a decimal string such as "0.05"; an integer stays an integer). A digest is "sha256:" and 64 lower-case hex digits.

An algorithm this code cannot verify is refused, never passed: a post-quantum signer is a name in the signed bytes,
and a verifier that knows it is a later release, not a different format.

Settlement stays deterministic: rung 1 checks the answer, rung 2 applies the rule both parties agreed before the run,
with the false-accept and false-reject rates they stated. The rates are stated, never computed here.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ── the constants ────────────────────────────────────────────────────────────────────────────────────────────────────

RECEIPT_SCHEMA_VERSION = "1.0"
SIGNING_PREFIX = b"theprotocol.quantum.receipt/1.0\n"
# what this code signs and verifies; any other named algorithm is refused
SIGNING_ALGORITHMS = ("Ed25519",)
# the algorithm this code signs and verifies today, by the name V0660 (c)'s proxy card generator reads
RECEIPT_SIGNING_ALGORITHM = SIGNING_ALGORITHMS[0]
ALGORITHM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._-]{1,47}$")
ACCEPTANCE_RUNGS = (1, 2)
METERING_CIRCUIT = "accurateResourceUsagePolicy/v2.0.0"
# the templates a verdict is recomputed for: their rung and the agent card extension's method name
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "answer-check/v1.0": {"rung": 1, "method": "answer_check"},
    "test-circuits/v1.0": {"rung": 2, "method": "test_circuits"},
    "independent-repeat/v1.0": {"rung": 2, "method": "independent_repeat"},
}
ANSWER_PROBLEMS = ("factorisation", "assignment", "objective_threshold")
STEP_KINDS = ("circuit_submitted", "circuit_compiled", "backend_bound", "run_executed", "result_reported", "verdict")
ROLES_FOR_KIND: Dict[str, Tuple[str, ...]] = {
    "circuit_submitted": ("client", "router"),
    "circuit_compiled": ("compiler", "provider"),
    "backend_bound": ("provider",),
    "run_executed": ("provider",),
    "result_reported": ("provider", "mitigator"),
    "verdict": ("verifier",),
}
BACKEND_KINDS = ("qpu", "simulator", "emulator")
MAX_STEPS = 16
MAX_FACTORS = 64
MAX_PARTICIPANTS = 16
MAX_COUNT_ENTRIES = 200_000
MAX_INT = 2 ** 53 - 1

_STEP_KEYS = ("receipt", "job", "seq", "kind", "prev", "participant", "role", "at", "body", "signature")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_JOB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DID = re.compile(r"^did:[a-z0-9]+:[^\s]{1,190}$")
_FORMAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,31}$")
_BITS = re.compile(r"^[01]{1,128}$")
_DIGITS = re.compile(r"^[1-9][0-9]{0,4095}$")
_DECIMAL = re.compile(r"^-?[0-9]{1,30}(\.[0-9]{1,30})?$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")

_BODY_KEYS: Dict[str, Tuple[str, ...]] = {
    "circuit_submitted": ("circuits_digest", "format", "shots", "acceptance_digest"),
    "circuit_compiled": ("source_digest", "compiled_digest", "format"),
    "backend_bound": ("backend", "kind", "calibration_digest"),
    "run_executed": ("shots", "counts_digest"),
    "result_reported": ("from_counts_digest", "result_digest"),
    "verdict": ("template", "rung", "passed", "acceptance_digest", "evidence_digest", "false_accept_rate",
                "false_reject_rate"),
}
_AGREEMENT_KEYS = ("template", "problem", "params", "verifier", "participants", "false_accept_rate",
                   "false_reject_rate", "note", "work")
_WORK_KEYS = ("rail", "ref", "seq")
_WORK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class ReceiptError(ValueError):
    """A document that cannot be put in canonical form (a float, a non-ASCII key, a type JSON does not carry)."""


# ── canonical JSON and digests ───────────────────────────────────────────────────────────────────────────────────────

def _check_canonical(value: Any, where: str = "$") -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        if abs(value) > MAX_INT:
            raise ReceiptError(f"{where}: an integer past 2^53 - 1; write it as a decimal string")
        return
    if isinstance(value, float):
        raise ReceiptError(f"{where}: a floating-point number; write a fraction as a decimal string such as \"0.05\"")
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_canonical(v, f"{where}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not k.isascii():
                raise ReceiptError(f"{where}: keys are ASCII strings")
            _check_canonical(v, f"{where}.{k}")
        return
    raise ReceiptError(f"{where}: a {type(value).__name__}, which JSON does not carry")


def canonical(doc: Any) -> bytes:
    """The canonical JSON bytes of a document (raises ReceiptError on a value it cannot carry)."""
    _check_canonical(doc)
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest_of(doc: Any) -> str:
    """'sha256:' and the hex SHA-256 of the document's canonical JSON."""
    return "sha256:" + hashlib.sha256(canonical(doc)).hexdigest()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64url(text: Any) -> Optional[bytes]:
    if not isinstance(text, str) or not text or not _B64URL.match(text):
        return None
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        return None


# ── keys and signatures ──────────────────────────────────────────────────────────────────────────────────────────────

def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as e:  # pragma: no cover: both repositories install it
        raise RuntimeError("checking a receipt signature needs the 'cryptography' package (pip install cryptography)") \
            from e
    return ed25519, serialization, InvalidSignature


def new_signing_key():
    """A fresh Ed25519 private key (cryptography's object), for a participant or a test."""
    ed25519, _s, _i = _crypto()
    return ed25519.Ed25519PrivateKey.generate()


def public_jwk(private_key) -> Dict[str, str]:
    """The public half of an Ed25519 private key as a JWK: {kty: OKP, crv: Ed25519, x}."""
    _e, serialization, _i = _crypto()
    raw = private_key.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                                format=serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}


def _jwk_bytes(jwk: Any) -> Optional[bytes]:
    """The raw 32-byte Ed25519 public key a JWK names, or None."""
    if not isinstance(jwk, Mapping) or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        return None
    raw = _unb64url(jwk.get("x"))
    return raw if raw is not None and len(raw) == 32 else None


def same_key(a: Any, b: Any) -> bool:
    """Do two JWKs name the same Ed25519 public key? (other members, such as kid or alg, are not compared)"""
    ra, rb = _jwk_bytes(a), _jwk_bytes(b)
    return ra is not None and ra == rb


def signed_bytes(step: Mapping[str, Any]) -> bytes:
    """The bytes a step's signature value signs: the prefix and the step without the value."""
    sig = dict(step.get("signature") or {})
    sig.pop("value", None)
    unsigned = dict(step)
    unsigned["signature"] = sig
    return SIGNING_PREFIX + canonical(unsigned)


def sign_step(step: Mapping[str, Any], private_key, algorithm: str = "Ed25519") -> Dict[str, Any]:
    """The step with its signature: {algorithm, public_key, value}. Only the algorithms in SIGNING_ALGORITHMS sign."""
    if algorithm not in SIGNING_ALGORITHMS:
        raise ReceiptError(f"this code signs with {', '.join(SIGNING_ALGORITHMS)}, not {algorithm!r}")
    out = {k: v for k, v in step.items() if k != "signature"}
    out["signature"] = {"algorithm": algorithm, "public_key": public_jwk(private_key)}
    out["signature"]["value"] = _b64url(private_key.sign(signed_bytes(out)))
    return out


def _verify_signature(step: Mapping[str, Any]) -> Optional[str]:
    """None when the step's signature verifies, else what is wrong with it."""
    sig = step.get("signature")
    if not isinstance(sig, Mapping) or set(sig) != {"algorithm", "public_key", "value"}:
        return "the signature is {algorithm, public_key, value}"
    alg = sig.get("algorithm")
    if not isinstance(alg, str) or not ALGORITHM_PATTERN.match(alg):
        return "the signature names no algorithm"
    if alg not in SIGNING_ALGORITHMS:
        return (f"algorithm_unsupported: it is signed with {alg}, which this verifier cannot check "
                f"(it checks {', '.join(SIGNING_ALGORITHMS)}); the step is refused, never passed")
    raw_key = _jwk_bytes(sig.get("public_key"))
    if raw_key is None:
        return "the public key is not an Ed25519 JWK {kty: OKP, crv: Ed25519, x}"
    value = _unb64url(sig.get("value"))
    if value is None or len(value) != 64:
        return "the signature value is not 64 bytes in base64url"
    ed25519, _s, invalid = _crypto()
    try:
        message = signed_bytes(step)
    except ReceiptError as e:
        return str(e)
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(raw_key).verify(value, message)
    except invalid:
        return "the signature does not verify"
    except ValueError:
        return "the public key is not a valid Ed25519 key"
    return None


def step_digest(step: Mapping[str, Any]) -> str:
    """The digest the next step names as its prev: of the whole step, signature value included."""
    return digest_of(dict(step))


# ── building a chain ─────────────────────────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_step(chain: Sequence[Mapping[str, Any]], *, kind: str, participant: str, role: str,
                body: Mapping[str, Any], private_key, job: Optional[str] = None, at: Optional[str] = None,
                algorithm: str = "Ed25519") -> List[Dict[str, Any]]:
    """A new chain: the given one and one more signed step at its end (the first step names the job)."""
    chain = [dict(s) for s in chain]
    if chain:
        job = chain[0].get("job")
        prev: Optional[str] = step_digest(chain[-1])
    else:
        if not job:
            raise ReceiptError("the first step names the job")
        prev = None
    step = {"receipt": RECEIPT_SCHEMA_VERSION, "job": job, "seq": len(chain), "kind": kind, "prev": prev,
            "participant": participant, "role": role, "at": at or _now(), "body": dict(body)}
    chain.append(sign_step(step, private_key, algorithm))
    return chain


# ── reading documents ────────────────────────────────────────────────────────────────────────────────────────────────

def _is_int(v: Any, lo: int = 0, hi: int = MAX_INT) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _digest_or_none(v: Any) -> bool:
    return v is None or (isinstance(v, str) and bool(_DIGEST.match(v)))


def _fraction(v: Any, *, lo: Fraction = Fraction(0), hi: Fraction = Fraction(1),
              open_lo: bool = False) -> Optional[Fraction]:
    """A decimal string in [lo, hi] (or (lo, hi]) as an exact Fraction, or None."""
    if not isinstance(v, str) or not _DECIMAL.match(v):
        return None
    try:
        f = Fraction(Decimal(v))
    except (InvalidOperation, ValueError):
        return None
    if f < lo or f > hi or (open_lo and f == lo):
        return None
    return f


def _number(v: Any) -> Optional[Fraction]:
    """An integer or a decimal string as an exact Fraction, or None."""
    if _is_int(v, -MAX_INT, MAX_INT):
        return Fraction(v)
    if isinstance(v, str) and _DECIMAL.match(v):
        return Fraction(Decimal(v))
    return None


def _ts(v: Any) -> Optional[_dt.datetime]:
    if not isinstance(v, str) or len(v) > 40:
        return None
    try:
        t = _dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _body_problems(kind: str, body: Any) -> List[str]:
    if not isinstance(body, Mapping):
        return ["the body is an object"]
    keys = _BODY_KEYS[kind]
    out = [f"body.{k}: unknown member (known: {', '.join(keys)})" for k in body if k not in keys]
    out += [f"body.{k}: required" for k in keys if k not in body]
    if out:
        return out
    b = body
    if kind == "circuit_submitted":
        if not _digest_or_none(b["circuits_digest"]) or b["circuits_digest"] is None:
            out.append("body.circuits_digest: a digest")
        if not isinstance(b["format"], str) or not _FORMAT.match(b["format"]):
            out.append("body.format: a format name such as openqasm3")
        if not _is_int(b["shots"], 1, 10 ** 9):
            out.append("body.shots: a whole number from 1 to 10^9")
        if not _digest_or_none(b["acceptance_digest"]):
            out.append("body.acceptance_digest: a digest or null")
    elif kind == "circuit_compiled":
        for k in ("source_digest", "compiled_digest"):
            if b[k] is None or not _digest_or_none(b[k]):
                out.append(f"body.{k}: a digest")
        if not isinstance(b["format"], str) or not _FORMAT.match(b["format"]):
            out.append("body.format: a format name such as openqasm3")
    elif kind == "backend_bound":
        if not isinstance(b["backend"], str) or not _ID.match(b["backend"]):
            out.append("body.backend: the backend's id (1 to 64 characters)")
        if b["kind"] not in BACKEND_KINDS:
            out.append(f"body.kind: one of {', '.join(BACKEND_KINDS)}")
        if not _digest_or_none(b["calibration_digest"]):
            out.append("body.calibration_digest: a digest or null")
        elif b["kind"] == "qpu" and b["calibration_digest"] is None:
            out.append("body.calibration_digest: a qpu run names the calibration snapshot it ran under")
    elif kind == "run_executed":
        if not _is_int(b["shots"], 1, 10 ** 9):
            out.append("body.shots: a whole number from 1 to 10^9")
        if b["counts_digest"] is None or not _digest_or_none(b["counts_digest"]):
            out.append("body.counts_digest: a digest")
    elif kind == "result_reported":
        for k in ("from_counts_digest", "result_digest"):
            if b[k] is None or not _digest_or_none(b[k]):
                out.append(f"body.{k}: a digest")
    elif kind == "verdict":
        if not isinstance(b["template"], str) or b["template"] not in TEMPLATES:
            out.append(f"body.template: one of {', '.join(TEMPLATES)}")
        if b["rung"] not in ACCEPTANCE_RUNGS or isinstance(b["rung"], bool):
            out.append("body.rung: 1 or 2")
        if not isinstance(b["passed"], bool):
            out.append("body.passed: true or false")
        for k in ("acceptance_digest", "evidence_digest"):
            if b[k] is None or not _digest_or_none(b[k]):
                out.append(f"body.{k}: a digest")
        for k in ("false_accept_rate", "false_reject_rate"):
            if b[k] is not None and _fraction(b[k]) is None:
                out.append(f"body.{k}: a decimal string from 0 to 1, or null")
    return out


_ORDER = re.compile(r"^SC?BRT?V?$")
_PARTIAL = re.compile(r"^S(C?(B(RT?)?)?)?$")   # a chain still being built (require_verdict=False)
_LETTER = {"circuit_submitted": "S", "circuit_compiled": "C", "backend_bound": "B", "run_executed": "R",
           "result_reported": "T", "verdict": "V"}


@dataclass
class ChainReport:
    """What a chain check found: ok when there are no problems."""
    problems: List[str] = field(default_factory=list)
    job: Optional[str] = None
    head: Optional[str] = None
    steps: int = 0
    key_binding: str = "self_asserted"

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems), "job": self.job, "head": self.head,
                "steps": self.steps, "key_binding": self.key_binding}


def _by_kind(chain: Sequence[Mapping[str, Any]], kind: str) -> Optional[Mapping[str, Any]]:
    return next((s for s in chain if isinstance(s, Mapping) and s.get("kind") == kind), None)


def verify_chain(chain: Any, *, keys: Optional[Mapping[str, Iterable[Any]]] = None,
                 require_verdict: bool = True) -> ChainReport:
    """Check a receipt chain: every step's form, its link to the step before it, its signature, the order of the steps
    and what each step repeats from an earlier one. `keys` maps a participant's DID to the public keys (JWKs) it may sign
    with; when given, every step's key must be one of its participant's. Without it the keys are the steps' own
    (key_binding self_asserted): the chain is whole, but who holds each key is not checked. Never raises."""
    rep = ChainReport(key_binding="self_asserted" if keys is None else "pinned")
    if not isinstance(chain, list) or not 1 <= len(chain) <= MAX_STEPS:
        rep.problems.append(f"chain: a list of 1 to {MAX_STEPS} steps")
        return rep
    rep.steps = len(chain)
    prev_digest: Optional[str] = None
    prev_at: Optional[_dt.datetime] = None
    order = ""
    for i, step in enumerate(chain):
        where = f"step {i}"
        if not isinstance(step, Mapping):
            rep.problems.append(f"{where}: an object")
            prev_digest = None
            continue
        kind = step.get("kind")
        where = f"step {i} ({kind})" if isinstance(kind, str) else where
        extra = [k for k in step if k not in _STEP_KEYS]
        missing = [k for k in _STEP_KEYS if k not in step]
        if extra or missing:
            rep.problems.append(f"{where}: the members are {', '.join(_STEP_KEYS)}"
                                + (f"; unknown: {', '.join(map(str, extra))}" if extra else "")
                                + (f"; missing: {', '.join(missing)}" if missing else ""))
            prev_digest = None
            continue
        if step["receipt"] != RECEIPT_SCHEMA_VERSION:
            rep.problems.append(f"{where}: receipt schema {step['receipt']!r} is not one this verifier reads "
                                f"({RECEIPT_SCHEMA_VERSION})")
        if not isinstance(step["job"], str) or not _JOB.match(step["job"]):
            rep.problems.append(f"{where}: job is an id of 1 to 128 characters")
        elif i == 0:
            rep.job = step["job"]
        elif step["job"] != rep.job:
            rep.problems.append(f"{where}: names job {step['job']!r}, the chain is job {rep.job!r}")
        if step["seq"] != i or isinstance(step["seq"], bool):
            rep.problems.append(f"{where}: seq is {step['seq']!r}, its place in the chain is {i}")
        if i == 0 and step["prev"] is not None:
            rep.problems.append(f"{where}: the first step links to nothing (prev null)")
        elif i > 0 and (prev_digest is None or step["prev"] != prev_digest):
            rep.problems.append(f"{where}: prev does not name the step before it; the chain is broken here")
        if kind not in STEP_KINDS:
            rep.problems.append(f"{where}: kind is one of {', '.join(STEP_KINDS)}")
        else:
            order += _LETTER[kind]
            if step["role"] not in ROLES_FOR_KIND[kind]:
                rep.problems.append(f"{where}: a {kind} step is signed as {' or '.join(ROLES_FOR_KIND[kind])}, "
                                    f"not {step['role']!r}")
            rep.problems.extend(f"{where}: {p}" for p in _body_problems(kind, step["body"]))
        participant = step["participant"]
        if not isinstance(participant, str) or not _DID.match(participant):
            rep.problems.append(f"{where}: participant is the signer's DID")
        at = _ts(step["at"])
        if at is None:
            rep.problems.append(f"{where}: at is a timestamp with an offset")
        else:
            if prev_at is not None and at < prev_at:
                rep.problems.append(f"{where}: signed before the step it follows")
            prev_at = at
        why = _verify_signature(step)
        if why:
            rep.problems.append(f"{where}: {why}")
        elif keys is not None and isinstance(participant, str):
            allowed = list(keys.get(participant) or [])
            if not any(same_key(step["signature"]["public_key"], k) for k in allowed):
                rep.problems.append(f"participant_key_unknown: {where}: {participant} is not known to sign with this "
                                    "key (neither registered for it nor pinned in the agreement)")
        try:
            prev_digest = step_digest(step)
        except ReceiptError as e:
            rep.problems.append(f"{where}: {e}")
            prev_digest = None
    if order and not (_ORDER.match(order) or (not require_verdict and _PARTIAL.match(order))):
        rep.problems.append("chain: the steps run circuit_submitted, circuit_compiled (optional), backend_bound, "
                            "run_executed, result_reported (optional), verdict, in that order, each once")
    elif require_verdict and not order.endswith("V"):
        rep.problems.append("chain: it ends with the verifier's verdict")
    if rep.problems:
        return rep
    sub, comp, run = _by_kind(chain, "circuit_submitted"), _by_kind(chain, "circuit_compiled"), \
        _by_kind(chain, "run_executed")
    res, ver = _by_kind(chain, "result_reported"), _by_kind(chain, "verdict")
    if comp and comp["body"]["source_digest"] != sub["body"]["circuits_digest"]:
        rep.problems.append("circuit_compiled: compiles circuits other than the ones submitted (source_digest)")
    if run and run["body"]["shots"] != sub["body"]["shots"]:
        rep.problems.append(f"run_executed: ran {run['body']['shots']} shots, {sub['body']['shots']} were submitted")
    if res and res["body"]["from_counts_digest"] != run["body"]["counts_digest"]:
        rep.problems.append("result_reported: reports a result from counts other than the run's (from_counts_digest)")
    if ver and ver["body"]["acceptance_digest"] != sub["body"]["acceptance_digest"]:
        rep.problems.append("verdict: judges against an agreement other than the one the circuits were submitted under")
    rep.head = step_digest(chain[-1]) if not rep.problems else None
    return rep


# ── the acceptance agreement ─────────────────────────────────────────────────────────────────────────────────────────

def _params_problems(template: str, problem: Any, p: Any) -> List[str]:
    if not isinstance(p, Mapping):
        return ["params: an object"]
    out: List[str] = []

    def known(*names: str) -> None:
        out.extend(f"params.{k}: unknown member (known: {', '.join(names)})" for k in p if k not in names)
        out.extend(f"params.{k}: required" for k in names if k not in p)

    if template == "answer-check/v1.0":
        if problem == "factorisation":
            known("n")
            if "n" in p and (not isinstance(p["n"], str) or not _DIGITS.match(p["n"]) or int(p["n"]) < 4):
                out.append("params.n: the number to factor, as a decimal string of at least 4")
        elif problem == "assignment":
            known("variables", "clauses")
            nv = p.get("variables")
            if "variables" in p and not _is_int(nv, 1, 100_000):
                out.append("params.variables: a whole number from 1 to 100000")
            cl = p.get("clauses")
            if "clauses" in p:
                if not isinstance(cl, list) or not 1 <= len(cl) <= 100_000:
                    out.append("params.clauses: a list of 1 to 100000 clauses")
                elif _is_int(nv, 1, 100_000):
                    for i, c in enumerate(cl):
                        if (not isinstance(c, list) or not 1 <= len(c) <= 64
                                or not all(_is_int(x, -nv, nv) and x != 0 for x in c)):
                            out.append(f"params.clauses[{i}]: 1 to 64 literals, each a non-zero whole number whose "
                                       f"size names a variable (1 to {nv})")
                            break
        elif problem == "objective_threshold":
            known("matrix", "sense", "threshold")
            m = p.get("matrix")
            if "matrix" in p:
                n = len(m) if isinstance(m, list) else 0
                if not 1 <= n <= 256 or not all(isinstance(r, list) and len(r) == n for r in m) \
                        or not all(_number(x) is not None for r in m for x in r):
                    out.append("params.matrix: a square QUBO matrix of 1 to 256 rows, each entry an integer or a "
                               "decimal string")
            if "sense" in p and p["sense"] not in ("minimize", "maximize"):
                out.append("params.sense: minimize or maximize")
            if "threshold" in p and _number(p["threshold"]) is None:
                out.append("params.threshold: an integer or a decimal string")
    elif template == "test-circuits/v1.0":
        known("tests_commitment", "test_count", "min_passed", "min_success_fraction")
        if "tests_commitment" in p and (p["tests_commitment"] is None or not _digest_or_none(p["tests_commitment"])):
            out.append("params.tests_commitment: the digest of the hidden tests document")
        tc = p.get("test_count")
        if "test_count" in p and not _is_int(tc, 1, 1024):
            out.append("params.test_count: a whole number from 1 to 1024")
        if "min_passed" in p and not (_is_int(p["min_passed"], 1, 1024) and (not _is_int(tc) or p["min_passed"] <= tc)):
            out.append("params.min_passed: a whole number from 1 to test_count")
        if "min_success_fraction" in p and _fraction(p["min_success_fraction"], open_lo=True) is None:
            out.append("params.min_success_fraction: a decimal string above 0 and at most 1")
    elif template == "independent-repeat/v1.0":
        known("circuit", "max_distance", "min_shots")
        if "circuit" in p and (not isinstance(p["circuit"], str) or not _ID.match(p["circuit"])):
            out.append("params.circuit: the id of the circuit both runs are compared on")
        if "max_distance" in p and _fraction(p["max_distance"]) is None:
            out.append("params.max_distance: a decimal string from 0 to 1 (total variation distance)")
        if "min_shots" in p and not _is_int(p["min_shots"], 1, 10 ** 9):
            out.append("params.min_shots: a whole number from 1 to 10^9")
    return out


def check_agreement(doc: Any) -> List[str]:
    """What is wrong with an acceptance agreement; [] when it can settle a verdict. Never raises.

        {"template": "answer-check/v1.0", "problem": "factorisation", "params": {"n": "15"},
         "verifier": "<DID, optional>", "participants": {"<DID>": <Ed25519 JWK>, ...}, "note": "...",
         "work": {"rail": "guild_work_order", "ref": "gwo_...", "seq": <a milestone's number, optional>},
         "false_accept_rate": "0.01", "false_reject_rate": "0.05"}      (the two rates: rung 2 only, both required)
    """
    if not isinstance(doc, Mapping):
        return ["the agreement is an object"]
    out = [f"{k}: unknown member (known: {', '.join(_AGREEMENT_KEYS)})" for k in doc if k not in _AGREEMENT_KEYS]
    try:
        canonical(dict(doc))
    except ReceiptError as e:
        out.append(str(e))
    template = doc.get("template")
    if not isinstance(template, str) or template not in TEMPLATES:
        out.append(f"template: one of {', '.join(TEMPLATES)}")
        return out
    rung = TEMPLATES[template]["rung"]
    problem = doc.get("problem")
    if template == "answer-check/v1.0":
        if problem not in ANSWER_PROBLEMS:
            out.append(f"problem: one of {', '.join(ANSWER_PROBLEMS)}")
            return out
    elif problem is not None:
        out.append("problem: only answer-check/v1.0 names a problem")
    out.extend(_params_problems(template, problem, doc.get("params")))
    for k in ("false_accept_rate", "false_reject_rate"):
        if rung == 1 and k in doc:
            out.append(f"{k}: a rung 1 check of the answer has no error rates to state")
        if rung == 2 and _fraction(doc.get(k)) is None:
            out.append(f"{k}: a rung 2 test states it before the run, as a decimal string from 0 to 1")
    if "verifier" in doc and (not isinstance(doc["verifier"], str) or not _DID.match(doc["verifier"])):
        out.append("verifier: the DID of the agent that signs the verdict")
    parts = doc.get("participants")
    if "participants" in doc:
        if not isinstance(parts, Mapping) or not 1 <= len(parts) <= MAX_PARTICIPANTS \
                or not all(isinstance(d, str) and _DID.match(d) and _jwk_bytes(k) is not None for d, k in parts.items()):
            out.append(f"participants: 1 to {MAX_PARTICIPANTS} DIDs, each with the Ed25519 JWK it signs with")
    if "note" in doc and (not isinstance(doc["note"], str) or len(doc["note"]) > 500):
        out.append("note: a string of at most 500 characters")
    if "work" in doc:
        w = doc["work"]
        if not isinstance(w, Mapping) or not {"rail", "ref"} <= set(w) or not set(w) <= set(_WORK_KEYS) \
                or not all(isinstance(w[k], str) and _WORK_ID.match(w[k]) for k in ("rail", "ref")) \
                or ("seq" in w and not _is_int(w["seq"], 1)):
            out.append('work: {"rail": "<rail>", "ref": "<id>", "seq": <a milestone\'s number, optional>}, the piece '
                       "of work this agreement settles")
    return out


def participants_of(*chains: Any) -> List[str]:
    """The participant DIDs the steps of the given chains name (read defensively, in order, each once)."""
    seen: List[str] = []
    for chain in chains:
        for step in chain if isinstance(chain, list) else []:
            d = step.get("participant") if isinstance(step, Mapping) else None
            if isinstance(d, str) and _DID.match(d) and d not in seen:
                seen.append(d)
    return seen


def pinned_keys(agreement: Mapping[str, Any]) -> Dict[str, List[Any]]:
    """The keys an agreement pins, as verify_chain's `keys`."""
    parts = agreement.get("participants") if isinstance(agreement, Mapping) else None
    return {d: [k] for d, k in parts.items()} if isinstance(parts, Mapping) else {}


# ── the evidence and the verdict ─────────────────────────────────────────────────────────────────────────────────────

def _counts_problems(doc: Any, name: str) -> List[str]:
    """A counts document: {"circuits": {"<id>": {"<bitstring>": <count>}}}."""
    if not isinstance(doc, Mapping) or set(doc) != {"circuits"} or not isinstance(doc["circuits"], Mapping):
        return [f"{name}: {{\"circuits\": {{\"<id>\": {{\"<bitstring>\": <count>}}}}}}"]
    entries = 0
    for cid, dist in doc["circuits"].items():
        if not isinstance(cid, str) or not _ID.match(cid) or not isinstance(dist, Mapping):
            return [f"{name}.circuits: each circuit id (1 to 64 characters) maps to its counts"]
        for bits, n in dist.items():
            entries += 1
            if not isinstance(bits, str) or not _BITS.match(bits) or not _is_int(n, 0, 10 ** 9):
                return [f"{name}.circuits.{cid}: each outcome is a bitstring of 1 to 128 bits with a count"]
        if entries > MAX_COUNT_ENTRIES:
            return [f"{name}: at most {MAX_COUNT_ENTRIES} outcomes in all"]
    return []


def _evidence_keys(evidence: Any, names: Tuple[str, ...]) -> List[str]:
    if not isinstance(evidence, Mapping):
        return ["evidence: an object"]
    out = [f"evidence.{k}: unknown member (known: {', '.join(names)})" for k in evidence if k not in names]
    out += [f"evidence.{k}: required" for k in names if k not in evidence]
    return out


def _check_answer(problem: str, p: Mapping[str, Any], result: Any) -> Tuple[Optional[bool], str, List[str]]:
    """(passed, the reason, problems) for a rung 1 answer; passed is None when the result cannot be read."""
    if problem == "factorisation":
        f = result.get("factors") if isinstance(result, Mapping) else None
        if not isinstance(f, list) or not 2 <= len(f) <= MAX_FACTORS or \
                not all(isinstance(x, str) and _DIGITS.match(x) for x in f) or set(result) != {"factors"}:
            return None, "", [f"evidence.result: {{\"factors\": [2 to {MAX_FACTORS} decimal strings]}}"]
        n, product = int(p["n"]), 1
        for x in f:
            product *= int(x)
        if any(not 1 < int(x) < n for x in f):
            return False, "a factor is 1 or the number itself, which is not a factorisation", []
        if product != n:
            return False, "the factors do not multiply to the number", []
        return True, f"{len(f)} factors multiply to the number", []
    if problem == "assignment":
        a = result.get("assignment") if isinstance(result, Mapping) else None
        nv = p["variables"]
        if not isinstance(a, list) or len(a) != nv or not all(isinstance(x, bool) for x in a) \
                or set(result) != {"assignment"}:
            return None, "", [f"evidence.result: {{\"assignment\": [{nv} true or false values]}}"]
        unsat = sum(1 for c in p["clauses"] if not any(a[abs(x) - 1] == (x > 0) for x in c))
        if unsat:
            return False, f"{unsat} of {len(p['clauses'])} clauses are not satisfied", []
        return True, f"all {len(p['clauses'])} clauses are satisfied", []
    m = p["matrix"]
    bits = result.get("bitstring") if isinstance(result, Mapping) else None
    if not isinstance(bits, str) or len(bits) != len(m) or not _BITS.match(bits) or set(result) != {"bitstring"}:
        return None, "", [f"evidence.result: {{\"bitstring\": a string of {len(m)} bits}}"]
    x = [int(c) for c in bits]
    value = sum((_number(m[i][j]) for i in range(len(m)) for j in range(len(m)) if x[i] and x[j]), Fraction(0))
    threshold = _number(p["threshold"])
    ok = value <= threshold if p["sense"] == "minimize" else value >= threshold
    rel = "at most" if p["sense"] == "minimize" else "at least"
    return ok, f"the objective is {_fmt(value)}; the agreement asks {rel} {_fmt(threshold)}", []


def _fmt(f: Fraction, places: int = 6) -> str:
    """An exact value as a short decimal string (rounded to `places`), for a reason a person reads."""
    q = (Decimal(f.numerator) / Decimal(f.denominator)).quantize(Decimal(1).scaleb(-places))
    s = format(q, "f")
    return (s.rstrip("0").rstrip(".") if "." in s else s) or "0"


def evaluate(agreement: Mapping[str, Any], chain: Sequence[Mapping[str, Any]],
             evidence: Any, *, keys: Optional[Mapping[str, Iterable[Any]]] = None) -> Tuple[Optional[bool], str,
                                                                                          List[str]]:
    """Recompute the verdict of a checked chain under its agreement: (passed, the reason, problems). passed is None when
    the evidence cannot be read; a failed test is passed False with its reason, never a problem."""
    template = agreement["template"]
    p = agreement["params"]
    run, res = _by_kind(chain, "run_executed"), _by_kind(chain, "result_reported")
    if template == "answer-check/v1.0":
        out = _evidence_keys(evidence, ("result",))
        if out:
            return None, "", out
        if res is None:
            return None, "", ["chain: a check of the answer needs the result_reported step the answer is bound to"]
        try:
            if digest_of(evidence["result"]) != res["body"]["result_digest"]:
                return None, "", ["evidence.result: is not the result the chain reports (result_digest)"]
        except ReceiptError as e:
            return None, "", [f"evidence.result: {e}"]
        return _check_answer(agreement["problem"], p, evidence["result"])
    if template == "test-circuits/v1.0":
        out = _evidence_keys(evidence, ("tests", "counts"))
        if out:
            return None, "", out
        tests, counts = evidence["tests"], evidence["counts"]
        out = _counts_problems(counts, "evidence.counts")
        try:
            if not out and digest_of(counts) != run["body"]["counts_digest"]:
                out.append("evidence.counts: are not the counts the run reports (counts_digest)")
            if digest_of(tests) != p["tests_commitment"]:
                out.append("evidence.tests: are not the hidden tests the agreement committed to (tests_commitment)")
        except ReceiptError as e:
            out.append(f"evidence: {e}")
        if out:
            return None, "", out
        circuits = tests.get("circuits") if isinstance(tests, Mapping) else None
        if not isinstance(tests, Mapping) or set(tests) != {"salt", "circuits"} or not isinstance(tests.get("salt"), str) \
                or not 16 <= len(tests["salt"]) <= 128 or not isinstance(circuits, list):
            return None, "", ["evidence.tests: {\"salt\": 16 to 128 characters, \"circuits\": [{\"id\", \"expected\"}]}"]
        ids = [c.get("id") for c in circuits if isinstance(c, Mapping)]
        if len(circuits) != p["test_count"] or len(set(ids)) != len(circuits) or not all(
                isinstance(c, Mapping) and set(c) == {"id", "expected"} and isinstance(c["id"], str)
                and _ID.match(c["id"]) and isinstance(c["expected"], str) and _BITS.match(c["expected"])
                for c in circuits):
            return None, "", [f"evidence.tests.circuits: {p['test_count']} tests, each {{id, expected bitstring}}, "
                              "ids unique"]
        need = _fraction(p["min_success_fraction"], open_lo=True)
        passed_tests = 0
        for c in circuits:
            dist = counts["circuits"].get(c["id"]) or {}
            shots = sum(dist.values())
            if shots and Fraction(dist.get(c["expected"], 0), shots) >= need:
                passed_tests += 1
        ok = passed_tests >= p["min_passed"]
        return ok, (f"{passed_tests} of {len(circuits)} hidden test circuits met their expected outcome "
                    f"(at least {p['min_passed']} needed)"), []
    # independent-repeat/v1.0
    out = _evidence_keys(evidence, ("counts", "repeat_chain", "repeat_counts"))
    if out:
        return None, "", out
    out = _counts_problems(evidence["counts"], "evidence.counts") + \
        _counts_problems(evidence["repeat_counts"], "evidence.repeat_counts")
    if out:
        return None, "", out
    rep = verify_chain(evidence["repeat_chain"], keys=keys, require_verdict=False)
    if not rep.ok:
        return None, "", [f"evidence.repeat_chain: {x}" for x in rep.problems]
    rc = evidence["repeat_chain"]
    rsub, rrun = _by_kind(rc, "circuit_submitted"), _by_kind(rc, "run_executed")
    sub = _by_kind(chain, "circuit_submitted")
    if rrun is None or _by_kind(rc, "verdict") is not None:
        return None, "", ["evidence.repeat_chain: the repeat runs to run_executed and carries no verdict of its own"]
    if rsub["body"]["circuits_digest"] != sub["body"]["circuits_digest"]:
        out.append("evidence.repeat_chain: repeats circuits other than the ones submitted (circuits_digest)")
    if rrun["participant"] == run["participant"]:
        out.append("evidence.repeat_chain: the repeat ran at the same provider; an independent repeat runs elsewhere")
    if digest_of(evidence["counts"]) != run["body"]["counts_digest"]:
        out.append("evidence.counts: are not the counts the run reports (counts_digest)")
    if digest_of(evidence["repeat_counts"]) != rrun["body"]["counts_digest"]:
        out.append("evidence.repeat_counts: are not the counts the repeat reports (counts_digest)")
    if out:
        return None, "", out
    cid = p["circuit"]
    a, b = evidence["counts"]["circuits"].get(cid), evidence["repeat_counts"]["circuits"].get(cid)
    if not a or not b:
        return False, f"circuit {cid} has no counts in one of the two runs", []
    na, nb = sum(a.values()), sum(b.values())
    if na < p["min_shots"] or nb < p["min_shots"]:
        return False, f"a run has fewer than {p['min_shots']} shots on circuit {cid} ({na} and {nb})", []
    tvd = sum((abs(Fraction(a.get(k, 0), na) - Fraction(b.get(k, 0), nb)) for k in set(a) | set(b)), Fraction(0)) / 2
    limit = _fraction(p["max_distance"])
    rel = "within" if tvd <= limit else "past"
    return tvd <= limit, (f"the two runs are {_fmt(tvd)} apart on circuit {cid} (total variation distance), {rel} "
                          f"the agreed {p['max_distance']}"), []


@dataclass
class JobReport:
    """A whole job's check: the chain, the agreement it ran under and the verdict recomputed from the evidence."""
    problems: List[str] = field(default_factory=list)
    chain: Optional[ChainReport] = None
    passed: Optional[bool] = None
    reason: str = ""
    template: Optional[str] = None
    rung: Optional[int] = None
    acceptance_digest: Optional[str] = None
    evidence_digest: Optional[str] = None
    false_accept_rate: Optional[str] = None
    false_reject_rate: Optional[str] = None
    verifier: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.problems

    def verdict(self) -> Dict[str, Any]:
        """What the ledger keeps: hashes and the verdict, never circuits, counts or results."""
        c = self.chain or ChainReport()
        return {"template": self.template, "rung": self.rung, "passed": self.passed, "reason": self.reason,
                "job": c.job, "head": c.head, "steps": c.steps, "key_binding": c.key_binding,
                "acceptance_digest": self.acceptance_digest, "evidence_digest": self.evidence_digest,
                "false_accept_rate": self.false_accept_rate, "false_reject_rate": self.false_reject_rate,
                "verifier": self.verifier, "receipt_schema": RECEIPT_SCHEMA_VERSION}

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems), "chain": (self.chain or ChainReport()).as_dict(),
                "verdict": self.verdict() if self.ok else None}


def check_job(agreement: Any, chain: Any, evidence: Any, *,
              keys: Optional[Mapping[str, Iterable[Any]]] = None,
              work: Optional[Mapping[str, Any]] = None) -> JobReport:
    """Check a finished job end to end: the agreement, the chain (bound to that agreement from its first step), the
    verifier's signed verdict, and the verdict recomputed from the evidence, which must be the one the verifier signed.
    `keys` (DID -> JWKs) is merged with the keys the agreement pins; with neither, the keys are the steps' own
    (self_asserted). `work`, when given, is the piece of work the job is checked for: the agreement must name exactly
    that work. ok means the job is checked; `passed` is then the verdict. Never raises."""
    rep = JobReport()
    rep.problems = [f"agreement: {p}" for p in check_agreement(agreement)]
    if rep.problems:
        return rep
    wanted = dict(work) if isinstance(work, Mapping) else work
    if wanted is not None and agreement.get("work") != wanted:
        named = agreement.get("work")
        rep.problems.append("agreement: names " + ("no work" if named is None else
                                                    f"other work ({json.dumps(named, sort_keys=True)})")
                            + f"; this check is for {json.dumps(wanted, sort_keys=True, default=str)}, and a receipt "
                            "chain settles only the work its agreement names")
        return rep
    rep.template = agreement["template"]
    rep.rung = TEMPLATES[rep.template]["rung"]
    rep.acceptance_digest = digest_of(dict(agreement))
    rep.false_accept_rate = agreement.get("false_accept_rate")
    rep.false_reject_rate = agreement.get("false_reject_rate")
    merged: Optional[Dict[str, List[Any]]] = None
    pins = pinned_keys(agreement)
    if keys is not None or pins:
        merged = {d: list(v) for d, v in (keys or {}).items()}
        for d, v in pins.items():
            merged.setdefault(d, []).extend(v)
    rep.chain = verify_chain(chain, keys=merged, require_verdict=True)
    if not rep.chain.ok:
        rep.problems.extend(f"chain: {p}" for p in rep.chain.problems)
        return rep
    sub, ver = _by_kind(chain, "circuit_submitted"), _by_kind(chain, "verdict")
    if sub["body"]["acceptance_digest"] != rep.acceptance_digest:
        rep.problems.append("chain: the circuits were not submitted under this agreement (acceptance_digest); an "
                            "acceptance test is agreed before the run")
    rep.verifier = ver["participant"]
    if agreement.get("verifier") and ver["participant"] != agreement["verifier"]:
        rep.problems.append(f"verdict: signed by {ver['participant']}, the agreement names {agreement['verifier']} as "
                            "its verifier")
    try:
        rep.evidence_digest = digest_of(evidence)
    except ReceiptError as e:
        rep.problems.append(f"evidence: {e}")
        return rep
    vb = ver["body"]
    if vb["evidence_digest"] != rep.evidence_digest:
        rep.problems.append("verdict: was signed over other evidence (evidence_digest)")
    if vb["template"] != rep.template or vb["rung"] != rep.rung:
        rep.problems.append(f"verdict: judges {vb['template']} rung {vb['rung']}; the agreement is {rep.template} rung "
                            f"{rep.rung}")
    if vb["false_accept_rate"] != rep.false_accept_rate or vb["false_reject_rate"] != rep.false_reject_rate:
        rep.problems.append("verdict: states other error rates than the agreement")
    if rep.problems:
        return rep
    passed, reason, problems = evaluate(agreement, chain, evidence, keys=merged)
    if problems:
        rep.problems.extend(problems)
        return rep
    if passed != vb["passed"]:
        rep.problems.append(f"verdict: the verifier signed passed={str(vb['passed']).lower()}; the evidence gives "
                            f"passed={str(passed).lower()} ({reason})")
        return rep
    rep.passed, rep.reason = passed, reason
    return rep


__all__ = [
    "RECEIPT_SCHEMA_VERSION", "SIGNING_PREFIX", "SIGNING_ALGORITHMS", "ALGORITHM_PATTERN", "ACCEPTANCE_RUNGS",
    "METERING_CIRCUIT", "TEMPLATES", "ANSWER_PROBLEMS", "STEP_KINDS", "ROLES_FOR_KIND", "BACKEND_KINDS", "MAX_STEPS",
    "ReceiptError", "canonical", "digest_of", "new_signing_key", "public_jwk", "same_key", "signed_bytes", "sign_step",
    "step_digest", "append_step", "ChainReport", "verify_chain", "check_agreement", "participants_of", "pinned_keys", "evaluate",
    "JobReport", "check_job",
]
