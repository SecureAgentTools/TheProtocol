"""§OPDIST — the registry's half of provisioning an operator through the frame runner.

The registry resolves every value, hands the runner a spec, and writes every row from the facts that come back. It
never holds the docker socket and the one-shot never holds the database: that exchange is the whole point, so this
module's job is to make the spec complete enough that the far side needs nothing else.

Pairs with `operator_host_work` (the module the one-shot runs) and with the runner's `operator_provision` op. The
three share a contract in three places, which is deliberate — each side checks what it depends on rather than
trusting the others to have checked — and none of the three changes a key without telling the other two.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, Optional

from agentvault_registry.services import frame_runner_client

# The operator socket's op names. The seam lives in three places; these are the registry's copy of it.
OP_PROVISION = "operator_provision"
OP_STATUS = "operator_status"
OP_TEARDOWN = "operator_teardown"

# The two phases the one-shot serves, and what each promises to return. One home: operator_host_work
# checks the same names on its side, deliberately (two doors that both check disagree less often
# than one that assumes the other did).
PHASES = ("bundle", "stack", "full")
RESULT_KEYS_BY_PHASE = {
    "bundle": ("bundle_path", "bundle_filename", "fingerprint"),
    # ⚠ THE STACK PHASE WAS MISSING FROM BOTH TABLES until 2026-09-16, so cloud_provisioner's runner branch could
    # not submit the job it was written to submit: build_operator_spec refused its own caller with "phase 'stack'
    # is not one the runner serves". The route was dead on arrival and nothing said so until a real provision ran
    # (agentvault2-6a, beacon). `notes` is not required: an empty list is a complete answer.
    "stack": ("stack_dir", "container_count"),
    "full": ("bundle_path", "bundle_filename", "fingerprint", "stack_dir"),
}

SECRET_KEYS = ("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET", "AUDITOR_RO_PASSWORD",
               "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG")
# Longer than the runner's plan ceiling: a provision pulls three images and brings nine containers up.
# ⚠ THIS MUST EXCEED THE FAR SIDE'S OWN CEILINGS, or the caller reports a failure for a job that is still working
# — and an operator would then be RUNNING on the frame with no row on this side describing it, which is the
# half-provisioned outcome the whole route is arranged to avoid. host_work's steps carry their own timeouts
# (extract, the env script, compose up, ps, the health wait, the log read and the psql stamps); this sits above
# their sum with room, and the timeout message says to read the job rather than provision again.
# ⚠ MOVED BY THE GATE THAT DERIVES IT, not by hand: test_the_deadline_exceeds_the_far_sides_own_ceilings sums
# host_work's own timeouts and refused at 2400 once V0389 added the bounded schema wait. A caller that gives up
# while the far side is still working reports a failure for a job that succeeds, and the frame then carries an
# operator no row describes.
PROVISION_DEADLINE_S = 3000.0
POLL_INTERVAL_S = 3.0


class SpecIncomplete(Exception):
    """The registry has not resolved everything the far side needs. Nothing was sent."""


def build_operator_spec(
    *,
    operator_name: str,
    safe_name: str,
    operator_did: str,
    frame: str,
    docker_pull_token: str,
    operator_secrets: Optional[Dict[str, str]] = None,
    phase: str = "full",
    env: Optional[Dict[str, str]] = None,
    stack_dir: Optional[str] = None,
    application_id: Optional[str] = None,
    local_images: bool = False,
) -> Dict[str, Any]:
    """Everything the one-shot needs and nothing it must not have.

    Refuses here rather than letting the far side refuse, for the one reason that matters: this side can still fix
    it. A spec that reaches the runner and comes back refused has cost a round trip and a job record for a mistake
    that was visible before it left.
    """
    _fields = [("operator_name", operator_name), ("safe_name", safe_name), ("operator_did", operator_did),
               ("frame", frame)]
    if not local_images:
        # §HELLOFRAME lane 6 (2026-09-18): a host whose operator images are LOCAL tags (the export's own step loaded
        # them under IMAGES_PREFIX) has nothing to pull and no token to carry; every other frame still refuses to send
        # a spec that could not pull, for the reason this whole builder exists — this side can still fix it.
        _fields.append(("docker_pull_token", docker_pull_token))
    missing = [n for n, v in _fields if not v]
    if missing:
        raise SpecIncomplete(f"the registry has not resolved {missing}; nothing was sent to the runner")
    if phase not in PHASES:
        raise SpecIncomplete(f"phase {phase!r} is not one the runner serves ({', '.join(PHASES)}); nothing was sent")
    # THE BUNDLE PHASE CARRIES NO SECRETS AT ALL — not even an empty field. The one-shot writes the operator's env
    # and its markers in steps 3 and 4, which only the full phase runs; a bundle job that carried them would put four
    # live secrets in a spec file on disk for a job that never opens them, and the runner REFUSES them there
    # (agentvault2-85, 599080a). An absent field says "this does not apply"; an empty one claims it applies and is
    # empty. The full phase still refuses without them.
    if phase == "bundle":
        operator_secrets = {}
    short = [] if phase == "bundle" else [
        k for k in SECRET_KEYS if len(str((operator_secrets or {}).get(k, ""))) < 32]
    if short:
        raise SpecIncomplete(
            f"these of the operator's own secrets are missing or under 32 characters: {short}. Short is not weak "
            f"here, it is OFF: the apps turn the header path off below 32 and would refuse every forwarded "
            f"certificate. Nothing was sent."
        )
    # ⚠ NO image_id, DELIBERATELY. The runner takes the image from the frame's own registry container and REFUSES a
    # caller that sends one (agentvault2-85, 2026-09-16, on my recommendation): a value nobody is asked for is a
    # value nobody can lie about, and it makes the one-shot provably the code the frame is RUNNING rather than the
    # code someone believed it was running. This side therefore has no REGISTRY_IMAGE_ID to resolve and no tag to
    # check; there is nothing here to keep in step with the image.
    # The frame's SPIRE identity travels in the spec because only this side knows it: the one-shot holds no frame
    # environment at all, and the provisioner it loads would otherwise fall to Frame A's defaults. Refused here
    # rather than there, for the reason this whole builder exists — this side can still fix it.
    _spire = {
        "spire_container": os.getenv("SPIRE_CONTAINER", ""),
        "spire_trust_domain": os.getenv("SPIRE_TRUST_DOMAIN", ""),
        "spire_server_address": os.getenv("SPIRE_SERVER_ADDRESS", ""),
        "spire_server_port": os.getenv("SPIRE_SERVER_PORT", ""),
    }
    _need = (("spire_container", "spire_trust_domain") if phase == "stack" else tuple(_spire))
    if True:
        _unset = sorted(k for k in _need if not str(_spire.get(k, "")).strip())
        if _unset:
            raise SpecIncomplete(
                f"this registry does not name its own SPIRE identity ({_unset}), so a bundle built from it would "
                f"register the operator's entries wherever the provisioner's defaults point, which is Frame A. "
                f"Nothing was sent.")
    spec: Dict[str, Any] = {
        "phase": phase,
        # The stack phase needs WHERE its data entry goes and nothing else: the runner verifies these two against
        # the frame's own registry, and the fingerprint is deliberately NOT carried — the stack phase extracts the
        # bundle, so it holds agent-attestation.crt and derives the x509pop fingerprint from it. A value nobody is
        # asked for is a value nobody can lie about, and a carried fingerprint that disagreed with the certificate
        # would register a parentID no agent ever attests as. (The same reasoning as image_id, above.)
        **({k: str(v).strip() for k, v in _spire.items() if k in ("spire_container", "spire_trust_domain")}
           if phase == "stack" else {k: str(v).strip() for k, v in _spire.items()}),
        "operator_name": operator_name,
        "safe_name": safe_name,
        "operator_did": operator_did,
        "frame": frame,
        "docker_pull_token": docker_pull_token,
        **({} if phase == "bundle" else
           {"operator_secrets": {k: operator_secrets[k] for k in SECRET_KEYS}}),
        "env": dict(env or {}),
    }
    if stack_dir:
        spec["stack_dir"] = stack_dir
    if application_id:
        # Nothing reads it; the runner records it so a human correlating a job with an application can.
        spec["application_id"] = str(application_id)
    if local_images:
        # the far side reads `images_local` and requires no pull token; the key is ABSENT rather than empty, because
        # an absent field says "this does not apply" and an empty one claims it applies and is empty
        spec.pop("docker_pull_token", None)
        spec["images_local"] = True
    return spec


def peer_row_action(status, deactivated_reason):
    """What a re-provision owes this peer row: "revive", "clear_stale", or "" for nothing.

    ⚠ THE MEASURED STATE WAS NOT THE ONE I WROTE THE FIRST VERSION FOR. After jelgava's successful re-provision
    beacon's row read status ACTIVE with deactivated_reason still "teardown" and deactivated_at still set — so
    something other than the provision path (a sync, or the operator's own registration) flips the STATUS and
    leaves the deactivation fields behind. A predicate that only fired on INACTIVE would never have run against
    the row that actually exists, and the fix would have looked exactly like a fix that did not work.
    An ACTIVE row claiming it was torn down is not cosmetic: deactivated_reason is what tells the next reader
    whether a peer is down on purpose, and every rail that consults it is being told something false.

    A teardown marks the parent's row INACTIVE with reason "teardown" and nothing revived it, so a re-provisioned
    operator came up federated with nobody from the side that decides (beacon/jelgava, 2026-09-16). "Never
    auto-revived" is a rule about WORKERS — a background pass must not resurrect what an admin took down — and a
    re-provision of the same application is the admin doing it again, which is the intent the rule protects.

    Everything else stays down and says so. A row deactivated as a self-echo, a duplicate frame, a revoked
    federation or by an admin is not this operator's teardown, and a provision is not an amnesty for it.
    """
    state = (status or "").strip().upper()
    reason = (deactivated_reason or "").strip().lower()
    if reason and reason != "teardown":
        # Not this operator's teardown: a self-echo, a duplicate frame, a revoked federation or an admin's
        # decision. A re-provision is not an amnesty for any of them, whatever the status now reads.
        return "", f"deactivated for {reason}, which a re-provision does not undo"
    if state == "INACTIVE" and reason == "teardown":
        return "revive", ""
    if state == "ACTIVE" and reason == "teardown":
        return "clear_stale", "active but still carrying its teardown fields"
    return "", "nothing to do"


def may_rebundle(status, activated_at):
    """May this application have a bundle rebuilt for it? Answered from the facts the WRITERS actually write.

    ⚠ THE PREVIOUS VERSION OF THIS GUARD ASKED FOR A STATE NOTHING HAS EVER WRITTEN. It read
    `status == "activated"`, taken from models.py's docstring ("pending -> approved -> activated / rejected"),
    and the only occurrence of that string as a status value anywhere in the tree was the guard READING it: the
    writers are pending, approved, rejected, revoked and suspended, and /operators/activate stamps `activated_at`
    while leaving the status at "approved". So the recovery could never run for any application in any state, and
    the route it was written to rescue answered 500 naming a status the product does not have. Prose next to a
    field is a hypothesis; the writers are the answer.

    `activated_at` is the same fact the upstream guard in routers/cloud_operators.py reads before it ever calls
    provisioning, so the two agree by construction rather than by coincidence. The status term is what that guard
    does NOT ask and this one must: a revoked or suspended application still carries an activated_at, and must
    not be handed a fresh bundle and a fresh pull token on its way past.
    """
    if activated_at is None:
        return False, "has never been activated, so there is no bundle to rebuild and none was built"
    s = (status or "").strip().lower()
    if s != "approved":
        return False, (f"is {s!r}; only an approved application may have a bundle rebuilt, because a revoked or "
                       f"suspended one must not be handed fresh credentials")
    return True, ""


async def bundle_through_runner(
    *, frame: str, operator_name: str, safe_name: str, operator_did: str,
    application_id: Optional[str] = None, docker_pull_token: str = "", docker_username: str = "",
) -> Dict[str, Any]:
    """A bundle built by the frame runner, in the shape the application row is written from.

    TWO callers and one implementation, deliberately: activation builds the first bundle, and provisioning rebuilds
    one when activation could not (the promise in activation's own except clause, which until 2026-09-16 nothing
    kept — the route answered 200, the row carried no bundle, and the next step said "Bundle not found at None").

    ⚠ THE PULL TOKEN IS THE CALLER'S. Pass the one whose hash the caller is about to record. Minting inside a
    recovery would hand the operator's compose a credential the row does not know, which is the exact state that
    made beacon's ventspils unrecoverable rather than merely unfinished.
    """
    import hashlib as _hl
    from agentvault_registry.services.operator_provisioner import generate_docker_credentials
    if not frame:
        raise SpecIncomplete("this frame cannot name itself to the runner (no TEG_LAYER_URL and no REGISTRY_NAME), "
                             "so it cannot ask for an operator bundle; nothing was done")
    if not docker_pull_token:
        docker_username, docker_pull_token = generate_docker_credentials(safe_name)
    spec = build_operator_spec(
        operator_name=operator_name, safe_name=safe_name, operator_did=operator_did, frame=frame,
        docker_pull_token=docker_pull_token, phase="bundle", application_id=application_id)
    result = await provision_through_runner(frame=frame, spec=spec)
    bundles_dir = os.getenv("OPERATOR_BUNDLES_DIR", "/app/operator-bundles")
    return {
        # The FILENAME is the only thing both sides agree on: the one-shot and this registry see one file at two
        # paths. The row is written from this side's view of it, never from the far side's.
        "bundle_path": os.path.join(bundles_dir, result["bundle_filename"]),
        "bundle_filename": result["bundle_filename"],
        "fingerprint": result.get("fingerprint"),
        "docker_username": docker_username,
        "docker_pull_token": docker_pull_token,
        "docker_pull_token_hash": _hl.sha256(docker_pull_token.encode()).hexdigest(),
        "docker_pull_token_prefix": docker_pull_token[:8],
        "entries_registered": result.get("spire_entries_registered"),
        "where": f"the frame runner (job on {frame})",
    }


def _reason_from(job: Dict[str, Any], last: Dict[str, Any]) -> str:
    """The runner's own sentence about why a job ended, wherever it put it.

    ⚠ TWO BRANCHES ASKED THIS QUESTION AND ONLY ONE WAS TAUGHT THE ANSWER. `reason` was added to the refused
    branch and not to the failed one, so a provision that died on a dependency logged "no reason given" while
    operator_status carried "dependency failed to start: container cloud-op-jelgava-teg is unhealthy · ALREADY
    WRITTEN: stack dir ..." (job 908a9513d677432c, 2026-09-16). That is the widening rule this project already
    has: after adding a predicate, grep every OTHER site still asking the old question. One function now, so a
    third branch cannot be written without it.
    """
    for candidate in (job.get("reason"), job.get("refused_reason"), job.get("error"), last.get("error")):
        if candidate and candidate is not True:
            return str(candidate)
    return ""


async def teardown_through_runner(*, frame: str, safe_name: str, application_id: Optional[str] = None,
                                  deadline_s: float = PROVISION_DEADLINE_S) -> Dict[str, Any]:
    """Tear the operator's stack down through the runner, for a frame whose registry holds no docker socket.

    ⚠ THE HOST HALF MUST HAPPEN BEFORE THE DATABASE HALF SAYS IT DID. Today's route calls the SDK path, which
    returns False on a socketless frame and only logs it, and then stamps cloud_torn_down_at, deactivates the peer
    and revokes the licence anyway — so the database would read "torn down" while the operator kept serving
    (agentvault2-6a measured it on beacon, V0390). This raises instead, and every DB write sits after it.

    `purge` is deliberately not offered: the runner refuses it, and a parameter whose only answer is a refusal is
    a promise the caller has to discover is empty.
    """
    if not frame or not safe_name:
        raise SpecIncomplete("a teardown needs the frame and the operator's safe name; nothing was sent")
    spec: Dict[str, Any] = {"operator_name": safe_name, "safe_name": safe_name, "purge": False}
    if application_id:
        spec["application_id"] = str(application_id)
    return await provision_through_runner(frame=frame, spec=spec, deadline_s=deadline_s, op=OP_TEARDOWN)


async def provision_through_runner(
    *, frame: str, spec: Dict[str, Any], deadline_s: float = PROVISION_DEADLINE_S,
    poll_interval_s: float = POLL_INTERVAL_S, op: str = OP_PROVISION,
) -> Dict[str, Any]:
    """Submit, wait, and return the far side's facts.

    ⚠ THE TWO FAILURES ARE NOT THE SAME FAILURE, and every layer of this keeps them apart. RunnerRefused means
    nothing started: the caller's activation code is still good and its pull token was never used. RunnerError means
    something may have run. This morning cost a one-time activation code precisely because a rail could not tell
    those apart, so the distinction is propagated rather than collapsed into "provisioning failed".
    """
    submitted = await frame_runner_client.call(op, timeout=frame_runner_client.SHORT_TIMEOUT_S,
                                               frame=frame, spec=spec)
    # ⚠ TWO SHAPES, ONE ANSWER. The runner answers {"started": true, "job": {"id": ...}}; a top-level "job_id"
    # was added beside it on 2026-09-16. Reading only one of them cost a real activation: beacon's ventspils job
    # SUCCEEDED (3 SPIRE entries, the tar on disk) while this side raised "accepted without returning a job id"
    # and wrote no bundle to the row, which is the worst of both — the work happened and nothing recorded it.
    # Accept either, so a registry and a runner that disagree about the shape still agree about the job.
    _sub = submitted or {}
    job_id = _sub.get("job_id") or ((_sub.get("job") or {}) if isinstance(_sub.get("job"), dict) else {}).get("id")
    if not job_id:
        raise frame_runner_client.RunnerError(
            f"the runner accepted {op} without returning a job id: {submitted!r}")

    deadline = time.monotonic() + deadline_s
    last: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = await frame_runner_client.call(OP_STATUS, timeout=frame_runner_client.SHORT_TIMEOUT_S,
                                              frame=frame, job_id=job_id) or {}
        # The runner answers {"job": {...}, "result": {...}} for a job id, and a frame summary without one. Read the
        # NESTED state: my first version read it at the top level, which would have polled a static object to the
        # deadline against a job that had already finished (agentvault2-85 found the other half of that break).
        job = last.get("job") or {}
        state = str(job.get("state") or last.get("state") or "").lower()
        if job.get("refused"):
            # ⚠ `refused` IS A FLAG, AND THE REASON IS A DIFFERENT FIELD. Formatting the flag printed
            # "Provisioning failed: True (job ...; nothing was done)" into the registry's log — a boolean where a
            # sentence was meant, in the one line a human reads to learn why. Take the reason from wherever the
            # runner actually put it, and fall back to the flag only when there is nothing better to say.
            _why = _reason_from(job, last) or f"the runner refused (no reason given; refused={job.get('refused')!r})"
            raise frame_runner_client.RunnerRefused(f"{_why} (job {job_id}; nothing was done)")
        if state in ("succeeded", "finished", "done", "ok"):
            result = last.get("result") or {}
            # A result is judged against the phase THIS SPEC ASKED FOR. The first version demanded stack_dir of every
            # result, which would have read a perfectly good bundle job as a broken one the day activation started
            # asking for one: a contract that outlived the single caller it was written for.
            # A teardown has no phase and its own result keys; a provision is judged by the phase it asked for.
            want = () if op == OP_TEARDOWN else RESULT_KEYS_BY_PHASE[str(spec.get("phase") or "full")]
            # PRESENCE, never truth. `container_count` is legitimately 0 on a compose that brought nothing up,
            # and a falsy test would report the phase as having broken its promise precisely when it is telling
            # you the most interesting thing it can tell you. A key that is absent, or present as null, is short.
            short = [k for k in want if k not in result or result[k] is None]
            if short:
                raise frame_runner_client.RunnerError(
                    f"job {job_id} finished without {short}, which the {spec.get('phase') or 'full'} phase promises "
                    f"(it returned {sorted(result)})")
            return result
        if state in ("refused",):
            raise frame_runner_client.RunnerRefused(
                f"{job.get('refused') or last.get('error') or 'the runner refused'} (job {job_id}; nothing started)")
        if state in ("failed", "error"):
            _exit = job.get("exit_code")
            # Exit 4 is the one-shot saying it had ALREADY WRITTEN to the frame, so a caller must not treat this
            # as a clean re-runnable failure the way a refusal is.
            _wrote = " (the one-shot had already written to the frame)" if _exit == 4 else ""
            raise frame_runner_client.RunnerError(
                f"job {job_id} failed (exit {_exit}){_wrote}: "
                f"{_reason_from(job, last) or 'no reason given'}")
        await asyncio.sleep(poll_interval_s)

    raise frame_runner_client.RunnerError(
        f"job {job_id} did not finish within {deadline_s:.0f}s (last state {last.get('state') or last.get('status')!r}). "
        f"It may still be running: read the job rather than provisioning again."
    )
