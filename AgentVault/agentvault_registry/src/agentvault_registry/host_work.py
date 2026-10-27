"""§OPDIST — the HOST half of provisioning a cloud operator, run as a one-shot container the runner creates.

His decision 2026-09-16 (relayed by agentvault2-85): the privileged work moves to the privileged component. The
long-lived, internet-facing registry never holds the docker socket; the frame runner launches THIS module in a
one-shot container from the registry image with the socket mounted, and destroys it when it returns. The privilege
exists for the seconds it is used, under the runner's uid gate, its policy file and its audit log.

WHAT CROSSES THE SEAM, and why it is this and nothing more. The one-shot holds NO database URL, NO API token and no
ORM object: the registry resolves every value first and passes it in a spec, and the registry writes every row from
the facts that come back. That is the only reason the seam is worth having, so this module REFUSES a spec carrying
a database or API credential rather than trusting the runner to have checked (it does check; two doors that both
check disagree less often than one that assumes the other did).

The operator's OWN secrets do cross: its terminator markers and its Redis passwords, minted for it by the registry,
plus its one-time pull token. Those are the operator's to hold, they are useless elsewhere, and a token minted and
then lost with a failed provision is inert rather than consumed.

WHAT STAYS BEHIND, deliberately, and is named here so nobody looks for it:
  · the host nginx vhost write and `nginx -s reload` — the runner does it after this returns, because it is already
    root and the alternative is giving this container PID 1's namespace for one reload (agentvault2-85's call, and
    the right one: a namespace is a much larger thing to buy than a file write).
  · every database row: the application, the licence, the peer rows, the token hash. A thing issued once must not
    sit on the far side of a boundary that can fail after issuing it.

Contract: read the spec from $OPERATOR_SPEC, write the result to $OPERATOR_RESULT, exit 0 on success and non-zero
with one sentence on stderr on failure. Every step appends to `notes`, so a partial run says how far it got rather
than leaving the reader to infer it from what is missing.

⚠ WHY THIS FILE SITS AT THE TOP OF THE PACKAGE AND NOT UNDER `services`, MEASURED 2026-09-16 AND NOT GUESSED: the
entry point was `python3 -m agentvault_registry.services.operator_host_work`, and importing that package runs
`services/__init__.py` -> webhook_service -> models -> database -> Settings, which REQUIRES `DATABASE_URL` and
`API_KEY_SECRET`. This container is given neither, on purpose — that is the whole reason the seam is worth having —
so the one-shot died at IMPORT, before reading a spec, on every frame. Nobody would have seen it until the first
real provision: the runner's own refusals all happen before the container starts. The entry point is now
`python3 -m agentvault_registry.host_work`, the package init is empty, and the provisioner is loaded BY PATH below
for the same reason. `tests/test_operator_host_work_phases.py` pins it by importing with the environment empty.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import sys
from typing import Any, Dict, List, Optional

# A spec carrying either of these is refused: they are the credentials this seam exists to keep on the other side.
FORBIDDEN_KEYS = ("DATABASE_URL", "API_KEY_SECRET", "SECRET_KEY", "JWT_SECRET_KEY")
REQUIRED = ("operator_name", "safe_name", "operator_did", "frame", "stack_root", "job_id", "docker_pull_token")
# Only the phases that WRITE them require the secrets, and the bundle phase refuses them outright: a bundle job opens
# none of the four, so carrying them would put live secrets in a spec file on disk for nothing. The runner's door
# checks the same thing (agentvault2-85, 599080a) — two doors that both check disagree less often than one that
# assumes the other did.

# TWO CALLERS, ONE OP. Activation needs the BUNDLE (that is all activation has ever meant: the operator is given its
# identity and its tar, and its stack comes later at cloud-provision). Cloud-provision needs the whole thing. Serving
# both from one phaseless op would have made activation stand a stack up on a frame whose ports nothing has allocated
# yet, which is not what the same button does on EU and ASIA. An unknown phase is REFUSED rather than defaulted: a
# caller asking for something this module does not serve must hear so, not silently get the biggest thing.
PHASES = ("bundle", "stack", "full")
RESULT_KEYS_BY_PHASE = {
    "bundle": ("bundle_path", "bundle_filename", "spire_entries_registered", "notes"),
    "stack": ("stack_dir", "container_count", "notes"),
    "full": ("bundle_path", "bundle_filename", "stack_dir", "container_count", "spire_entries_registered", "notes"),
}
RESULT_KEYS = RESULT_KEYS_BY_PHASE["full"]
# What each phase needs beyond REQUIRED. The stack phase does NOT re-bundle: activation already built the tar and
# the application row already carries its fingerprint and its token hash, so building a second one would re-register
# SPIRE entries and leave the row describing a bundle nobody has.
# ⚠ THE BUNDLE PHASE REQUIRES THE FRAME'S SPIRE IDENTITY, and refuses without it rather than defaulting.
# The provisioner reads SPIRE_CONTAINER, SPIRE_TRUST_DOMAIN, SPIRE_SERVER_ADDRESS and SPIRE_SERVER_PORT from its
# environment with FRAME A's values as the fallback (`agentvault-spire-server`, `agentvault.com`,
# `spire.theprotocol.cloud`). The one-shot is handed none of that environment, so until 2026-09-16 a bundle built
# for ANY runner-built frame would have registered that operator's three entries in FRAME A's SPIRE, under Frame
# A's trust domain, and written Frame A's endpoint into the operator's agent.conf. Beacon's first attempt failed
# only because the CA key was not mounted either: the wrong-frame registration is what a working mount would have
# bought. A fallback that is right for exactly one frame in the fleet is not a fallback, and nobody finds out.
SPIRE_IDENTITY_KEYS = ("spire_container", "spire_trust_domain", "spire_server_address", "spire_server_port")
REQUIRED_BY_PHASE = {
    "bundle": SPIRE_IDENTITY_KEYS,
    "stack": ("bundle_filename", "operator_secrets", "compose"),
    "full": ("operator_secrets",) + SPIRE_IDENTITY_KEYS,
}


def provisioner_module_path(base_dir):
    """`services/operator_provisioner.py` under base_dir, or the compiled `.pyc` beside where it would be: a release
    image (§HELLOFRAME, the export's Dockerfile) ships bytecode only, and the first operator provisioned from such a
    frame died here with FileNotFoundError on the `.py`. Raises FileNotFoundError naming both when neither exists."""
    py = os.path.join(base_dir, "services", "operator_provisioner.py")
    if os.path.isfile(py):
        return py
    pyc = py + "c"
    if os.path.isfile(pyc):
        return pyc
    raise FileNotFoundError(f"neither {py} nor {pyc} exists: the provisioner is not in this image")


def _load_provisioner(base_dir=None):
    """The provisioner, loaded BY PATH so the import never touches `agentvault_registry.services.__init__`.

    That package init pulls the ORM and the settings object, which require a database URL and an API key this
    container must not hold. The module itself is a leaf (stdlib plus cryptography) and loads with an empty
    environment — measured in the image, not assumed. The path is the source, or its compiled sibling in a release
    image (importlib picks the sourceless loader for a `.pyc` path).
    """
    import importlib.util
    import sys
    path = provisioner_module_path(base_dir or os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("_opdist_operator_provisioner", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HostWorkRefused(Exception):
    """The spec is not one this module will act on. NOTHING WAS DONE — the caller may re-run unchanged."""


class HostWorkFailed(Exception):
    """A step failed AFTER this container had already written to the frame. The frame HAS state.

    ⚠ THE TWO ARE NOT THE SAME AND A CALLER ACTS ON THEM DIFFERENTLY, which is why they are different exits (3
    and 4) and different words. On 2026-09-16 beacon's first real stack phase failed at `compose up` having
    already made the stack dir, extracted the bundle, updated the svid-writer's SANs, created ten containers and
    chowned the Redis ACL to uid 999 — and the registry recorded "nothing was done". A retry into that state
    fails again on the ACL file it can no longer write, so "nothing was done" did not merely mislead a reader,
    it described the one thing that was not true of the only decision that mattered. (That retry itself: closed
    2026-09-26, V0453. operator_provisioner.write_redis_acl renames a fresh file over the old one instead of
    opening it, which needs the directory's write permission and not the file's.)"""


# Set the moment this container first writes anything to the frame. Read by _failure_class(), so a step that
# fails after a write cannot report itself as a refusal. A list rather than a bool so the notes can say WHAT.
_SIDE_EFFECTS: List[str] = []


def _side_effect(what: str) -> None:
    _SIDE_EFFECTS.append(what)


def _failure_class():
    return HostWorkFailed if _SIDE_EFFECTS else HostWorkRefused


def _forbidden_in(value: Any, path: str = "") -> List[str]:
    """Every place a credential could hide: a top-level key, an env map, a nested dict."""
    found: List[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k in FORBIDDEN_KEYS:
                found.append(f"{path}{k}")
            found.extend(_forbidden_in(v, f"{path}{k}."))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(_forbidden_in(v, f"{path}{i}."))
    return found


def read_spec(path: str) -> Dict[str, Any]:
    with open(path) as fh:
        spec = json.load(fh)
    if not isinstance(spec, dict):
        raise HostWorkRefused(f"{path} is not a JSON object")
    phase = str(spec.get("phase") or "full").lower()
    if phase not in PHASES:
        raise HostWorkRefused(f"phase {phase!r} is not one this module serves ({', '.join(PHASES)}). Nothing was done.")
    # ⚠ THE CREDENTIAL SCAN GOES FIRST, before any completeness check. A spec that both carries a credential and
    # lacks a required key must be refused for the CREDENTIAL: that is the dangerous half, and it is the half a
    # caller will otherwise fix last. Widening the required keys on 2026-09-16 changed which refusal such a spec
    # got, which is how the order was noticed at all — the test that pins the credential refusal went red naming a
    # missing key. Order is not a detail here; it decides what the sentence in the record says.
    leaked = _forbidden_in(spec)
    if leaked:
        raise HostWorkRefused(
            f"the spec carries {sorted(set(leaked))}: this container must hold no database or API credential, which "
            f"is the whole reason the work was moved here. Nothing was done."
        )
    required = REQUIRED + REQUIRED_BY_PHASE[phase]
    if spec.get("images_local") is True:
        # the images are local tags on this host (§HELLOFRAME lane 6): nothing to pull, so no pull token to require
        required = tuple(k for k in required if k != "docker_pull_token")
    missing = [k for k in required if not spec.get(k)]
    if missing:
        raise HostWorkRefused(f"the spec is missing {missing} (phase {phase}), so the host work cannot start")
    if phase == "bundle" and spec.get("operator_secrets"):
        raise HostWorkRefused("operator_secrets in phase 'bundle': this job opens none of them, so carrying them "
                              "would write four live secrets to disk for nothing. Nothing was done.")
    return spec


def _run(cmd: List[str], note: str, notes: List[str], timeout: int = 600,
         cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """A step whose failure is READ rather than logged: _run in the registry logs and returns, which is how a failed
    extract used to leave the rest of a provision working against an empty directory."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if proc.returncode != 0:
        # ⚠ THE TAIL, NOT THE HEAD. compose prints its warnings first and its actual error last, so a 300-char
        # HEAD of a failed `compose up` was 300 characters of "variable is not set" and the cause never reached
        # the job log at all (beacon/jelgava, 2026-09-16).
        _err = (proc.stderr or proc.stdout).strip()
        _tail = _err[-600:] if len(_err) > 600 else _err
        raise _failure_class()(f"{note} failed (exit {proc.returncode}): "
                               f"{'...' if len(_err) > 600 else ''}{_tail}")
    notes.append(f"{note}: ok")
    return proc


def _bundles_dir(spec: Dict[str, Any], notes: List[str]) -> str:
    """Where the tar must land so the FRAME'S OWN REGISTRY can serve it afterwards.

    Measured on lantern 2026-09-16: its registry has `<stack dir>/operator-bundles` bound at `/app/operator-bundles`,
    and that host directory is under the stack root this container mounts. The default (`/app/operator-bundles`) is
    this container's own filesystem, which the runner destroys on return, so a bundle written there would leave the
    application row naming a path nothing can open: "Bundle not found", the same sentence this whole route exists to
    remove, moved one step later. The frame's directory comes from the RUNNER (which built the frame and knows it),
    never from the caller, so a frame cannot name another frame's directory by claiming it.
    """
    frame_dir = spec.get("frame_stack_dir")
    if not frame_dir:
        raise HostWorkRefused(
            "spec lacks frame_stack_dir: without it the bundle would be written into this one-shot's own filesystem, "
            "which is destroyed when it returns, and the application row would name a path nothing can open. "
            "Nothing was done.")
    root = os.path.realpath(spec["stack_root"])
    resolved = os.path.realpath(frame_dir)
    if not (resolved == root or resolved.startswith(root + os.sep)):
        raise HostWorkRefused(f"frame_stack_dir {frame_dir!r} is not under the stack root this container mounts")
    out = os.path.join(resolved, "operator-bundles")
    os.makedirs(out, exist_ok=True)
    notes.append(f"bundles dir: {out}")
    return out


def _bundle_step(spec: Dict[str, Any], notes: List[str]) -> Dict[str, Any]:
    """Step 1: SPIRE entries, the trust bundle, agent.conf, the nginx confs, the tar.

    Needs the socket to exec into the frame's spire-server, which is exactly the dependency that made this container
    necessary in the first place.
    """
    bundles_dir = _bundles_dir(spec, notes)
    os.environ["OPERATOR_BUNDLES_DIR"] = bundles_dir
    # The frame's own SPIRE identity, resolved by the registry and required above. Set BEFORE the module loads,
    # because two of these are read into module constants at import; the other two are read per call. Writing the
    # environment first and re-binding the constants after leaves no order in which this is wrong.
    os.environ["SPIRE_CONTAINER"] = str(spec["spire_container"])
    os.environ["SPIRE_TRUST_DOMAIN"] = str(spec["spire_trust_domain"])
    os.environ["SPIRE_SERVER_ADDRESS"] = str(spec["spire_server_address"])
    os.environ["SPIRE_SERVER_PORT"] = str(spec["spire_server_port"])
    if spec.get("operator_ca_dir"):
        os.environ["OPERATOR_CA_DIR"] = str(spec["operator_ca_dir"])
    if spec.get("nginx_templates_dir"):
        os.environ["NGINX_TEMPLATES_DIR"] = str(spec["nginx_templates_dir"])
    _op = _load_provisioner()
    # ⚠ AND RE-BIND IT. `BUNDLES_DIR` is read at import into a module constant, so setting the environment only works
    # while nothing has imported that module first — a second copy of a value, which is the class that rots. Writing
    # both leaves no order in which this is wrong.
    _op.BUNDLES_DIR = bundles_dir
    if spec.get("operator_ca_dir"):
        _op.CA_DIR = str(spec["operator_ca_dir"])
    if spec.get("nginx_templates_dir"):
        _op.NGINX_TEMPLATES_DIR = str(spec["nginx_templates_dir"])
    notes.append(f"bundle: SPIRE {spec['spire_trust_domain']} via {spec['spire_container']}")
    _side_effect("SPIRE entries and the bundle tar")
    bundle = _op.provision_operator(spec["operator_name"], spec["operator_did"],
                                    docker_pull_token=spec["docker_pull_token"])
    notes.append(f"bundle: {bundle.entries_registered} SPIRE entries")
    return {
        "bundle_path": bundle.bundle_path,
        # The FILENAME is the only thing both sides agree on: this container and the frame's registry see that file
        # at different paths (the host's, and /app/operator-bundles/). The caller writes its own view from this.
        "bundle_filename": os.path.basename(bundle.bundle_path),
        "spire_entries_registered": bundle.entries_registered,
        "docker_pull_token_hash": bundle.docker_pull_token_hash,
        "docker_pull_token_prefix": bundle.docker_pull_token_prefix,
        "fingerprint": bundle.fingerprint,
        "cert_expiry": bundle.cert_expiry,
    }


def _existing_bundle(spec: Dict[str, Any], notes: List[str]) -> str:
    """The tar the ACTIVATION call already produced, found by name in the frame's own bundles directory.

    The stack phase never builds a second one: the application row already names this bundle's fingerprint and its
    pull token hash, and a rebuild would re-register SPIRE entries and leave that row describing a bundle nobody
    has. Absent is refused rather than silently re-bundled — a missing tar means the row and the disk disagree, and
    that is a thing a human must see.
    """
    path = os.path.join(_bundles_dir(spec, notes), os.path.basename(spec["bundle_filename"]))
    if not os.path.isfile(path):
        raise HostWorkRefused(
            f"the bundle this operator was activated with is not on this frame ({path}). Nothing was done: the "
            f"application row names a bundle the disk does not have, which a rebuild here would hide.")
    notes.append(f"bundle: reusing the one activation built ({os.path.basename(path)})")
    return path


def _assignment_count(text: str) -> int:
    """Assignments in an env file's text: the measure of whether a generator did its job."""
    return sum(1 for ln in (text or "").splitlines() if "=" in ln and not ln.lstrip().startswith("#"))


def _read_text(path: str) -> str:
    with open(path) as fh:
        return fh.read()


# ⚠ THE CLOSING QUOTE. Compose accepts `- ./x:/y` and `- './x':/y`, and a pattern that allowed the opening quote
# but not the closing one silently matched only half the forms — caught by a test that used both, not by reading.
_BIND = re.compile(r"^\s*-\s+[\"']?\./(?P<src>[^:\"'\s]+)[\"']?:", re.M)


def _ensure_bind_sources(compose_path: str, stack_dir: str, notes: List[str],
                         extra_composes: Optional[List[str]] = None) -> None:
    """Every `./x` the compose binds must exist before `up`, and must be OURS.

    ⚠ DOCKER CREATES A MISSING BIND SOURCE AS A root:root DIRECTORY, and nothing anywhere reports it. The compose
    binds `./bundle-storage` into the registry and nginx-federation; it is not in the bundle and nothing created
    it, so the operator's registry — uid 1000 — could not write it, `0076_bdl_seed_templates` died on
    `os.makedirs('/app/bundle-storage/templates')`, the single upgrade transaction rolled back, and the operator
    came up on a database with ZERO tables. Every later step then failed with "relation does not exist", and the
    lab could not reproduce it because a lab has no bind mount: /app/bundle-storage was the image's own directory.
    The in-registry provisioning path never hit it because that path creates the directory as uid 1000 itself.
    (beacon/jelgava, measured by agentvault2-6a 2026-09-16.)

    Derived from the compose, never a list: `bundle-storage` is what was missing this time, and the property is
    that NOTHING the compose binds may be created by Docker on our behalf.
    """
    # ⚠ THE SAME FILE SET THE `up` READS. This read only the BASE compose, so a `./` bind that exists only in an
    # override was checked by nobody — and V0391 introduced exactly such an override. Docker would create a
    # root-owned directory for it and mount that over the file, which is the defect V0389 fixed, returning through
    # a door V0391 opened. A gate that looks at fewer files than the command it guards is not guarding it.
    text = ""
    for path in [compose_path] + list(extra_composes or []):
        try:
            with open(path) as fh:
                text += "\n" + fh.read()
        except OSError:
            continue
    if not text.strip():
        return
    made, missing_files = [], []
    for m in _BIND.finditer(text):
        src = m.group("src").rstrip("/")
        if not src or ".." in src.split("/"):
            continue
        path = os.path.join(stack_dir, src)
        if os.path.exists(path):
            continue
        # A missing source that LOOKS like a file is a bundle that did not carry what its compose needs. Creating
        # a directory in its place would turn a clear absence into a mount that silently shadows the file.
        if os.path.splitext(src)[1]:
            missing_files.append(src)
            continue
        os.makedirs(path, exist_ok=True)
        made.append(src)
    if missing_files:
        raise _failure_class()(
            f"the compose binds {sorted(missing_files)}, which the bundle did not carry and which are file-shaped, "
            f"so they cannot be created here. Docker would mount a root-owned directory over each. Nothing was "
            f"brought up.")
    notes.append(f"bind sources: created {made}" if made else "bind sources: all present")


# The database's own TLS, as an OVERRIDE rather than a change to the base compose. FOUR RUNNING FRAMES mount the
# same live templates directory (eu, asia, sbx-alpha, sbx-beta, all on V0380, measured by agentvault2-6a), so a
# data-cert-writer added to the BASE file would break operator provisioning on every one of them the moment it
# landed: no image there registers a data entry, and the database would wait on a `.ready` that never comes. An
# override is invisible to an image that does not pass `-f`, which is what makes the two halves land independently.
DB_TLS_OVERRIDE = "docker-compose.operator.dbtls.yml"


def _db_tls_companions(override_text: str) -> List[str]:
    """Every `./` file the override itself names, read from the override.

    ⚠ THIS WAS A HARDCODED LIST, which is the one rule this module applies everywhere else and did not apply to
    itself. The list happened to match what the override referenced, so nothing broke; the moment the override
    gained a third reference, the file would simply not arrive — copied by nobody, checked by nobody, and the
    database would start with whatever was there instead. Derived, it cannot fall behind the file it serves.
    """
    return sorted({m for m in re.findall(r"\./([A-Za-z0-9._-]+)", override_text or "")})


def _fingerprint_from_attestation(stack_dir: str) -> str:
    """The x509pop fingerprint, DERIVED from the certificate the bundle carries rather than carried beside it.

    It is the SHA-1 of the attestation certificate's DER, which is exactly how generate_attestation_certs computed
    the one the other three entries were registered under. Deriving it here means the value cannot disagree with
    the certificate an agent actually presents: a carried fingerprint that drifted would register a parentID no
    agent ever attests as, and the entry would simply never be matched.
    """
    path = os.path.join(stack_dir, "spire", "agent-attestation.crt")
    if not os.path.exists(path):
        return ""
    import hashlib as _hl
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    with open(path, "rb") as fh:
        cert = x509.load_pem_x509_certificate(fh.read())
    return _hl.sha1(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _db_tls_steps(spec: Dict[str, Any], stack_dir: str, safe: str, notes: List[str]) -> Dict[str, Any]:
    """Materialise the db-TLS override from the live templates, and register the data entry it waits for.

    Both halves or neither. A stack dir carrying the override without an entry is a database that waits forever
    for a certificate nobody issued — so the entry is registered BEFORE `up`, and a failure to register refuses
    rather than starting a stack that cannot finish.
    """
    tmpl = str(spec.get("nginx_templates_dir") or os.getenv("NGINX_TEMPLATES_DIR", "/app/nginx-templates"))
    _ovr_src = os.path.join(tmpl, DB_TLS_OVERRIDE)
    if not os.path.exists(_ovr_src) and not os.path.exists(os.path.join(stack_dir, DB_TLS_OVERRIDE)):
        notes.append("db tls: no override in the templates, so the database keeps the base compose (no data entry)")
        return {"db_tls": False}
    _ovr_text = _read_text(_ovr_src) if os.path.exists(_ovr_src) else _read_text(os.path.join(stack_dir,
                                                                                              DB_TLS_OVERRIDE))
    copied = []
    _missing = []
    for name in [DB_TLS_OVERRIDE] + _db_tls_companions(_ovr_text):
        src = os.path.join(tmpl, name)
        if not os.path.exists(src):
            # ⚠ A COMPANION THE OVERRIDE NAMES AND THE TEMPLATES LACK IS NOT A SKIP. Missing, Docker mounts a
            # root-owned directory in its place and the database starts with no hba, or no TLS script at all.
            if not os.path.exists(os.path.join(stack_dir, name)):
                _missing.append(name)
            continue
        dst = os.path.join(stack_dir, name)
        # ⚠ FROM THE LIVE TEMPLATES, NOT FROM THE BUNDLE. An application activated before these files existed has
        # a tar without them (beacon's jelgava), and its stack must still come up with a TLS database rather than
        # requiring a re-bundle to gain one.
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())
        os.chmod(dst, 0o755 if name.endswith(".sh") else 0o644)
        copied.append(name)
    if _missing:
        raise _failure_class()(
            f"the db-TLS override names {_missing}, which neither the templates nor the stack dir carry. The "
            f"database would start without them. Nothing was brought up.")
    fingerprint = _fingerprint_from_attestation(stack_dir)
    if not fingerprint:
        raise _failure_class()(
            f"the db-TLS override is in play and spire/agent-attestation.crt is not in {stack_dir}, so the data "
            f"entry cannot be registered under a parentID any agent attests as. Nothing was brought up.")
    registered = _load_provisioner().register_operator_data_entry(safe, fingerprint, f"cloud-op-{safe}-db")
    if registered != 1:
        raise _failure_class()(
            f"the db-TLS override is in play and the operator's data entry was NOT registered. Its database would "
            f"wait forever for a certificate nobody issued, and compose would block on it. Nothing was brought up.")
    notes.append(f"db tls: {copied} carried, data entry registered (dns cloud-op-{safe}-db, never federated)")
    return {"db_tls": True, "db_tls_files": copied}


# §OPA (2026-10-06, agentvault2-09; his words "please roll out and enable opa for the whole production cluster", then
# "we need this whole ... provisioner fix"): the operator's own OPA, which its registry asks in SHADOW. The frames have
# carried one since §SOVKIT; no operator did, so every operator registry's OPA code stayed dark. An OVERRIDE for the
# db-TLS override's reason: a frame whose image registers no opa entry must never meet an opa-cert-writer in the base.
# The policies are the stack's identity-fabric set, carried in the templates under opa/policies (the stack's hygiene
# workflow holds the copy equal to its source), plus the operator's own authorization module rendered from
# opa/system_authz.rego.tmpl.
OPA_OVERRIDE = "docker-compose.operator.opa.yml"
OPA_POLICY_FLOOR = 5
OPA_IMAGE = "openpolicyagent/opa:1.21.0"     # the frame template's FT_OPA_IMAGE, the image Frame A's OPA runs


def opa_env_values(safe: str) -> Dict[str, str]:
    """The operator's OPA settings, under the names the registry and the override read.

    SHADOW: OPA_ENABLED=true asks OPA every decision and OPA_ENFORCE=false keeps Python authoritative (enforcing is a
    separate word of his). They live in .env.operator itself, the registry's env_file, and not in the override, so a
    later recreate keeps them whichever compose files the roll driver passes."""
    return {
        "OPA_ENABLED": "true",
        "OPA_ENFORCE": "false",
        "OPA_URL": f"https://cloud-op-{safe}-opa:8181",
        "OPERATOR_OPA_IMAGE": OPA_IMAGE,
        "OPERATOR_OPA_LOG_LEVEL": "info",
        "OPERATOR_OPA_TLS_REFRESH": "5m",
    }


def _fill_env(env_path: str, values: Dict[str, str], header: str, label: str, notes: List[str]) -> List[str]:
    """Append the values .env.operator does not set yet; return the names written. A value already there (the registry's
    spec, or a person) wins: these steps fill, they never override. Values are never printed."""
    have = set()
    if os.path.exists(env_path):
        for ln in _read_text(env_path).splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                have.add(ln.split("=", 1)[0].strip())
    add = [(k, v) for k, v in values.items() if k not in have]
    if add:
        with open(env_path, "a") as fh:
            fh.write(f"\n# {header}\n")
            for k, v in add:
                fh.write(f"{k}={v}\n")
        os.chmod(env_path, 0o600)
    notes.append(f"{label} env: wrote {[k for k, _ in add]}" if add else f"{label} env: every value already set")
    return [k for k, _ in add]


def append_opa_env(env_path: str, safe: str, notes: List[str], extra: Optional[Dict[str, str]] = None) -> List[str]:
    """Append the OPA values .env.operator does not set yet; return the names written (fill-only, see _fill_env)."""
    values = dict(opa_env_values(safe))
    values.update(extra or {})
    return _fill_env(env_path, values, "§OPA: the operator's OPA, in shadow (the registry asks, Python decides)", "opa", notes)


def render_opa_policies(tmpl: str, stack_dir: str, trust_domain: str, safe: str) -> List[str]:
    """<stack>/opa/policies: the templates' policy set, and the operator's authorization module bound to its frame's
    trust domain and its own name. Refuses a set below the floor and a placeholder left unfilled: an OPA with an
    empty directory answers `undefined` to every question, which reads as allow in shadow and as deny in enforce."""
    import glob as _glob
    files = sorted(_glob.glob(os.path.join(tmpl, "opa", "policies", "*.rego")))
    if len(files) < OPA_POLICY_FLOOR:
        raise _failure_class()(
            f"the templates carry {len(files)} OPA policies under opa/policies, want >= {OPA_POLICY_FLOOR}; an OPA "
            f"with too few answers `undefined`. Nothing was brought up.")
    authz_src = os.path.join(tmpl, "opa", "system_authz.rego.tmpl")
    if not os.path.exists(authz_src):
        raise _failure_class()("the templates carry no opa/system_authz.rego.tmpl, so the operator's OPA could not "
                               "authorize its registry. Nothing was brought up.")
    if not trust_domain or not safe:
        raise _failure_class()("the operator's OPA module needs the frame's trust domain and the operator's name; "
                               "neither has a default here (every default in the provisioner names Frame A)")
    authz = _read_text(authz_src).replace("{{TRUST_DOMAIN}}", trust_domain).replace("{{OPERATOR}}", safe)
    if "{{" in authz:
        raise _failure_class()("opa/system_authz.rego.tmpl carries a placeholder this step does not fill")
    dest = os.path.join(stack_dir, "opa", "policies")
    os.makedirs(dest, exist_ok=True)
    written = []
    for f in files:
        with open(f, "rb") as a, open(os.path.join(dest, os.path.basename(f)), "wb") as b:
            b.write(a.read())
        written.append(os.path.basename(f))
    with open(os.path.join(dest, "system_authz.rego"), "w") as fh:
        fh.write(authz)
    written.append("system_authz.rego")
    # OPA runs as uid 1000 and reads the directory through a read-only bind; this tree's umask writes 750/640
    for d in (os.path.join(stack_dir, "opa"), dest):
        os.chmod(d, 0o755)
    for name in written:
        os.chmod(os.path.join(dest, name), 0o644)
    return written


# §PUSH (2026-10-06, agentvault2-09; his words "afterwards we do the same with push", "provisioner should also provision
# them"): the operator's own push relay, an OVERRIDE for the same reason as OPA's and the database's TLS (a frame whose
# image does not know it must never meet it in the base). Every operator had push switched off: PUSH_NOTIFY_ENABLED was
# unset, so Web Push and Pocket's phone pairing both stayed dark. The relay is ntfy on the operator's own network
# (the registry publishes to it there), its loopback port at the block's fixed push offset, behind a SUBSCRIBE-ONLY
# public vhost (core/operator_compose.operator_push_vhost) that the runner writes beside the console's.
PUSH_OVERRIDE = "docker-compose.operator.push.yml"
NTFY_IMAGE = "binwiederhier/ntfy:v2.28.0"      # the frames' relay image (the template's)


def push_env_values(safe: str, domain: str, reg_port: int) -> Dict[str, str]:
    """The operator's push settings. PUSH_APP_BASE_URL is the operator's own console: notification links open there,
    and it is the first WebAuthn rp-id candidate (an operator ran with no BASE_URL, so both fell to the baked
    localhost default). PUSH_NTFY_URL is the INTERNAL publish path (the operator network only)."""
    from agentvault_registry.core.operator_compose import operator_push_host, operator_push_port
    return {
        "PUSH_NOTIFY_ENABLED": "true",
        "PUSH_NTFY_URL": f"http://cloud-op-{safe}-ntfy",
        "PUSH_NTFY_PUBLIC_URL": f"https://{operator_push_host(domain)}",
        "PUSH_APP_BASE_URL": f"https://{domain}",
        "OPERATOR_PUSH_PORT": str(operator_push_port(reg_port)),
        "OPERATOR_NTFY_IMAGE": NTFY_IMAGE,
    }


def append_push_env(env_path: str, safe: str, domain: str, reg_port: int, notes: List[str],
                    extra: Optional[Dict[str, str]] = None) -> List[str]:
    values = dict(push_env_values(safe, domain, reg_port))
    values.update(extra or {})
    return _fill_env(env_path, values, "§PUSH: the operator's push relay (Web Push + Pocket pairing)", "push", notes)


def _push_steps(spec: Dict[str, Any], stack_dir: str, safe: str, notes: List[str]) -> Dict[str, Any]:
    """The operator's push relay: the override from the live templates. Its values follow in _write_operator_env and its
    public vhost travels to the runner in the result; templates without the override leave the operator without push."""
    tmpl = str(spec.get("nginx_templates_dir") or os.getenv("NGINX_TEMPLATES_DIR", "/app/nginx-templates"))
    src = os.path.join(tmpl, PUSH_OVERRIDE)
    if not os.path.exists(src):
        notes.append("push: no override in the templates, so the operator runs no push relay")
        return {"push": False}
    dst = os.path.join(stack_dir, PUSH_OVERRIDE)
    with open(src, "rb") as a, open(dst, "wb") as b:
        b.write(a.read())
    os.chmod(dst, 0o644)
    _side_effect(f"push override in {stack_dir}")
    notes.append("push: override carried (the operator's ntfy relay)")
    return {"push": True}


def _opa_steps(spec: Dict[str, Any], stack_dir: str, safe: str, notes: List[str]) -> Dict[str, Any]:
    """The operator's OPA: the override from the live templates, its policies, and the entry its writer waits for.

    Both halves or neither, as in _db_tls_steps: the entry is registered BEFORE `up`, and a failure refuses rather
    than starting a writer that waits forever. Templates without the override leave the operator without OPA and
    say so. The trust domain is the one the entry is registered under (the frame's SPIRE_TRUST_DOMAIN, which the
    runner hands the one-shot), so the module and the identity it authorizes cannot name two different domains."""
    tmpl = str(spec.get("nginx_templates_dir") or os.getenv("NGINX_TEMPLATES_DIR", "/app/nginx-templates"))
    src = os.path.join(tmpl, OPA_OVERRIDE)
    if not os.path.exists(src):
        notes.append("opa: no override in the templates, so the operator runs no OPA (no opa entry)")
        return {"opa": False}
    trust_domain = os.getenv("SPIRE_TRUST_DOMAIN") or ""
    _spec_td = str((spec.get("compose") or {}).get("spire_trust_domain") or "")
    if trust_domain and _spec_td and _spec_td != trust_domain:
        raise HostWorkRefused(
            f"the spec's trust domain ({_spec_td}) is not the one this one-shot registers entries under "
            f"({trust_domain}); the OPA module would authorize an identity the entry does not carry. Nothing was done.")
    policies = render_opa_policies(tmpl, stack_dir, trust_domain, safe)
    _side_effect(f"opa policies in {stack_dir}/opa/policies")
    with open(src, "rb") as a, open(os.path.join(stack_dir, OPA_OVERRIDE), "wb") as b:
        b.write(a.read())
    os.chmod(os.path.join(stack_dir, OPA_OVERRIDE), 0o644)
    fingerprint = _fingerprint_from_attestation(stack_dir)
    if not fingerprint:
        raise _failure_class()(
            f"the OPA override is in play and spire/agent-attestation.crt is not in {stack_dir}, so the opa entry "
            f"cannot be registered under a parentID any agent attests as. Nothing was brought up.")
    registered = _load_provisioner().register_operator_opa_entry(safe, fingerprint, f"cloud-op-{safe}-opa")
    if registered != 1:
        raise _failure_class()(
            "the OPA override is in play and the operator's opa entry was NOT registered. Its writer would wait "
            "forever for a certificate nobody issued, and compose would block on it. Nothing was brought up.")
    notes.append(f"opa: override carried, {len(policies)} policies rendered for {trust_domain}, opa entry registered "
                 f"(dns cloud-op-{safe}-opa, never federated)")
    return {"opa": True, "opa_policies": len(policies)}


def _compose_interpolations(text: str) -> set:
    """Every `${VAR}` with NO default that a compose actually interpolates.

    ⚠ A `${VAR}` INSIDE A COMMENT IS NOT AN INTERPOLATION. The db-TLS override's only regex hit is
    `${REGISTRY_NAME}` in its own header comment (agentvault2-6a measured it), and a raw-text gate would have
    demanded a variable nothing substitutes — a gate refusing a correct stack is as expensive as one that passes a
    broken one. Comments are stripped first. `${VAR:-default}` is excluded by construction: the pattern requires
    the closing brace immediately, so a variable with a default never reaches this set.

    §OPA (2026-10-06): a REQUIRED variable (`${VAR:?message}`, `${VAR?message}`) is one with no default by
    definition, and it is counted too. The OPA override is the first template to use the form; read only as
    `${VAR}`, its three values would have reached `up` unchecked, and compose would refuse the whole project there,
    after the stack dir was written, instead of here before anything was.
    """
    lines = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line.split(" #", 1)[0] if " #" in line else line)
    return set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)(?::?\?[^}]*)?\}", "\n".join(lines)))


def _take_live_base(stack_dir: str, tmpl_dir: str, notes: List[str]) -> None:
    """The base compose from the live templates, BEFORE anything reads it.

    ⚠ IT USED TO HAPPEN AFTER THE ENV STEP, which is where V0393 put it and where it was wrong: the env step's
    derived ${VAR} coverage gate read the stack dir's compose, and the live base then replaced that file, so the
    gate checked the BUNDLE's generation while `up` ran the live one. A no-default variable that only the live
    base interpolates would have reached `up` blank — precisely the failure the gate exists to stop, reintroduced
    by the fix for a different staleness. A gate must read the artifact the command reads, and it must read it
    after every step that can change it.
    """
    live = os.path.join(tmpl_dir, "docker-compose.operator.yml")
    dst = os.path.join(stack_dir, "docker-compose.operator.yml")
    if not os.path.exists(live):
        notes.append("compose: the templates carry no base, so the bundle's own copy is used")
        return
    was = len(_read_text(dst).splitlines()) if os.path.exists(dst) else 0
    with open(live, "rb") as a, open(dst, "wb") as b:
        b.write(a.read())
    notes.append(f"compose: base taken from the live templates "
                 f"({len(_read_text(dst).splitlines())} lines; the bundle's copy had {was})")
    # ⚠ AND THE GENERATOR COMES WITH IT (§SECFIX 2026-09-25). The compose and the generator are one pair: the compose
    # mounts files only the generator writes (userlist.txt, since the operator's pooler checks passwords). Taking the
    # compose from the live templates and the generator from the bundle packed at ACTIVATION mixed two generations:
    # re-provisioning an operator activated before the pooler change was refused with "the compose binds
    # ['userlist.txt'], which the bundle did not carry" (secfixop on the test frame secfixt, measured). Only when the
    # live base was taken, so the pair is always one generation, whichever it is.
    gen_live = os.path.join(tmpl_dir, "generate-operator-env.sh")
    if os.path.exists(gen_live):
        gen_dst = os.path.join(stack_dir, "generate-operator-env.sh")
        with open(gen_live, "rb") as a, open(gen_dst, "wb") as b:
            b.write(a.read())
        notes.append("generator: taken from the live templates with the compose (one generation)")


def _write_operator_env(spec: Dict[str, Any], stack_dir: str, safe: str, notes: List[str]) -> str:
    """Step 3 as its own function, so a test can run the REAL generator against a REAL stack dir.

    It was inline until 2026-09-16, and the defect it hid needed no docker to reproduce: the generator
    writes to stdout, this side captured that and dropped it, and the nine values the compose cannot start
    without were simply absent. Nothing in the suite could reach the code without bringing a stack up.
    """
    env_script = os.path.join(stack_dir, "generate-operator-env.sh")
    env_path = os.path.join(stack_dir, ".env.operator")
    if os.path.exists(env_script):
        # ⚠ THE SCRIPT IS A GENERATOR: it writes every value to STDOUT and writes no file at all — its own usage
        # line is `./generate-operator-env.sh [operator-name] > .env.operator`, so the CALLER owns the
        # redirection. `_run` captures stdout, and until 2026-09-16 it then threw it away: the file below was
        # created by the append alone, carrying the registry's 98 values and NONE of the nine the generator mints
        # (API_KEY_SECRET, JWT_SECRET_KEY, PG_PASS_REGISTRY, PG_PASS_TEG, SECRET_KEY, TEG_ADMIN_API_KEY,
        # TEG_AVTP_SYSTEM_API_KEY, TEG_REGISTRY_JWT_SECRET, TEG_TOKEN_SIGNING_KEY). The compose interpolates
        # those with no default, so both Postgres containers came up with a BLANK password and crash-looped
        # while seven services sat Created (beacon/jelgava, job 743d3afefe944696). Nothing errored: compose
        # warned about a blank string and carried on.
        # ⚠ TWO DIFFERENT SCRIPTS SHARE THIS ONE NAME, and which is present depends on where the bundle came
        # from. scripts/distribution/generate-operator-env.sh (2953 B) is a pure STDOUT generator whose usage line
        # is `> .env.operator`. scripts/distribution/nginx-templates/generate-operator-env.sh (3293 B) is a FILE
        # WRITER: `cat > .env.operator` and `cat > pgbouncer.ini`, relative to the CURRENT DIRECTORY, printing
        # two "[generate] Created" lines and nothing else. The bundle carries the SECOND one, because
        # operator_provisioner adds it from NGINX_TEMPLATES_DIR — so V0387, which captured stdout and set no cwd,
        # wrote two echo lines into .env.operator and dropped the real file in the one-shot's own /app.
        # ⚠ I got this wrong by reading the copy that was easier to find and correcting a peer with it, and the
        # test fixture I wrote used that same copy, so the suite agreed with me for the same reason I was wrong.
        # Run it IN the stack dir and accept whichever shape actually produced an environment; the converging of
        # the two scripts is a stack-side change, and until then this must not care which one it got.
        _gen = _run(["bash", env_script, f"cloud-op-{safe}"], "generate-operator-env.sh", notes, timeout=120,
                    cwd=stack_dir)
        _n_out = _assignment_count(_gen.stdout)
        if _n_out >= 20:
            with open(env_path, "w") as fh:
                fh.write(_gen.stdout)
            _shape = f"stdout generator, {_n_out} values"
        else:
            _n_file = _assignment_count(_read_text(env_path)) if os.path.exists(env_path) else 0
            if _n_file < 20:
                raise HostWorkRefused(
                    f"generate-operator-env.sh produced neither an environment on stdout ({_n_out} assignments) "
                    f"nor one in {stack_dir} ({_n_file}). Neither shape of this script did its job, so the compose "
                    f"would read a file of blanks. Nothing was brought up.")
            _shape = f"file-writing generator in the stack dir, {_n_file} values"
        os.chmod(env_path, 0o600)
        notes.append(f"env: {_shape}")
    _excluded = env_excluded_secrets()
    with open(env_path, "a") as fh:
        fh.write("\n# §OPDIST: written by the host one-shot from the registry's spec (never printed)\n")
        for key, value in (spec.get("env") or {}).items():
            fh.write(f"{key}={value}\n")
        for key, value in spec["operator_secrets"].items():
            # ⚠ NOT the auditor's read-only credential: the operator's own apps never read it, and a secret
            # written where nothing reads it is a secret with only downside. It is used two steps below to CREATE
            # the role, and the frame's auditor is given the DSN by the runner.
            if key in _excluded:
                continue
            fh.write(f"{key}={value}\n")
    os.chmod(env_path, 0o600)
    if os.path.exists(os.path.join(stack_dir, OPA_OVERRIDE)):
        # §OPA: the override is in this stack (only _opa_steps puts it there), so its values go with it
        append_opa_env(env_path, safe, notes)
    if os.path.exists(os.path.join(stack_dir, PUSH_OVERRIDE)):
        # §PUSH: likewise; the domain and the block's base port are the registry's, from the spec it built
        _c = dict(spec.get("compose") or {})
        append_push_env(env_path, safe, str(_c.get("domain") or ""), int(_c.get("reg_port") or 0), notes)
    # ⚠ DERIVED, NEVER A LIST. The nine names above are what ONE run happened to be missing; the property is
    # "every ${VAR} the compose interpolates without a default is assigned here". A hardcoded list would rot the
    # first time the template gains a variable, and the failure it guards is silent by construction — compose
    # substitutes a blank string, warns, and brings up a database with no password.
    _compose_files = [os.path.join(stack_dir, "docker-compose.operator.yml")]
    for _ovr_path in (os.path.join(stack_dir, DB_TLS_OVERRIDE), os.path.join(stack_dir, OPA_OVERRIDE),
                      os.path.join(stack_dir, PUSH_OVERRIDE)):
        if os.path.exists(_ovr_path):
            # `up` passes every override, so the coverage gate reads them all. The same rule as
            # _ensure_bind_sources, one step earlier: a gate that looks at fewer files than the command it guards
            # is not guarding it.
            _compose_files.append(_ovr_path)
    if any(os.path.exists(p) for p in _compose_files):
        _needed = set()
        for _p in _compose_files:
            if os.path.exists(_p):
                _needed |= _compose_interpolations(_read_text(_p))
        with open(env_path) as fh:
            _have = {ln.split("=", 1)[0].strip() for ln in fh if "=" in ln and not ln.lstrip().startswith("#")}
        _blank = sorted(n for n in _needed - _have)
        if _blank:
            raise HostWorkRefused(
                f"the compose interpolates {len(_blank)} variables with no default that .env.operator does not "
                f"set: {_blank[:12]}{'...' if len(_blank) > 12 else ''}. Compose would substitute blanks and bring "
                f"up a database with no password, which is what happened on 2026-09-16. Nothing was brought up.")
        notes.append(f"env: {len(_needed)} interpolated names, all set")
    # ⚠ THE POOLER IS THE OTHER HALF AND FAILS AFTER "up" SUCCEEDS. pgbouncer.ini carries the registry's and the
    # TEG's database passwords inline; the bundle's copy is placeholder-shaped, and only the file-writing
    # generator, run IN the stack dir, replaces it with one holding the same values as .env.operator. A pooler
    # still holding placeholders lets every container start and then fails every database call behind it, which
    # is the worst shape a defect can take. Compared in memory; no value is ever written to a note or a log.
    _pgb = os.path.join(stack_dir, "pgbouncer.ini")
    if os.path.exists(_pgb):
        _env_map = {}
        for ln in _read_text(env_path).splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                _k, _v = ln.split("=", 1)
                _env_map[_k.strip()] = _v.strip()
        _pgb_text = _read_text(_pgb)
        _mismatched = []
        for _db, _var in (("agentvault_registry", "PG_PASS_REGISTRY"), ("teg_layer", "PG_PASS_TEG")):
            _line = next((l for l in _pgb_text.splitlines() if l.strip().startswith(f"{_db} =")), "")
            _m = re.search(r"password=(\S+)", _line)
            if not _m or not _env_map.get(_var) or _m.group(1) != _env_map[_var]:
                _mismatched.append(f"{_db}/{_var}")
        if _mismatched:
            raise HostWorkRefused(
                f"pgbouncer.ini does not carry the database passwords .env.operator sets for {_mismatched}. The "
                f"pooler would start and then fail every query behind a healthy-looking stack. Nothing was "
                f"brought up. (Compared in memory; no value was read out.)")
        notes.append("env: pgbouncer.ini agrees with .env.operator on both database passwords")
    _written = [k for k in spec["operator_secrets"] if k not in _excluded]
    notes.append(f"env: {len(spec.get('env') or {})} values + {len(_written)} secrets, 600 "
                 f"({len(spec['operator_secrets']) - len(_written)} minted for this operator but not handed to it)")
    return env_path


def _stack_steps(spec: Dict[str, Any], bundle_path: str, notes: List[str]) -> Dict[str, Any]:
    """Steps 2 to 6: the stack dir, the env, the markers, the compose edits, and up."""
    safe = spec["safe_name"]
    stack_dir = spec.get("stack_dir") or os.path.join(spec["stack_root"], f"cloud-op-{safe}")

    # 2. the stack dir and the bundle in it. Read the status: an extract that fails silently leaves everything after
    #    it working against nothing (§OPDIST, measured 2026-09-16).
    os.makedirs(stack_dir, exist_ok=True)
    _side_effect(f"stack dir {stack_dir}")
    _run(["tar", "xzf", bundle_path, "-C", stack_dir], "bundle extract", notes)

    # 2b. the svid-writer SVID's hostname SANs, before anything dials this operator by name. It also hands back the
    #     operator's own SPIFFE ID, which the runner needs for the frame's directory readers list.
    identity = _update_spire_svid_sans(spec, notes)

    # 3. the operator's environment. The VALUES are the registry's (it holds the licence, the ports, the parent's
    #    addresses); writing them is this side's, because this side owns the filesystem.
    out_dbtls = _db_tls_steps(spec, stack_dir, safe, notes)
    out_opa = _opa_steps(spec, stack_dir, safe, notes)
    out_push = _push_steps(spec, stack_dir, safe, notes)
    _take_live_base(stack_dir, str(spec.get("nginx_templates_dir")
                                   or os.getenv("NGINX_TEMPLATES_DIR", "/app/nginx-templates")), notes)
    env_path = _write_operator_env(spec, stack_dir, safe, notes)

    # 4. the compose edits, through the ONE function the socket path also calls, so a frame provisioned here and a
    #    frame provisioned by a registry that holds its own socket cannot drift into two different operators.
    from agentvault_registry.core.operator_compose import (adapt_federation_conf, adapt_operator_compose,
                                                           docker_auth_config)
    c = dict(spec["compose"])
    compose_path = os.path.join(stack_dir, "docker-compose.operator.yml")
    with open(compose_path) as fh:
        compose = fh.read()
    compose, adapt_notes = adapt_operator_compose(
        compose, safe=safe, domain=c["domain"], reg_port=int(c["reg_port"]), fed_port=int(c["fed_port"]),
        teg_port=int(c["teg_port"]), worker_count=int(c.get("worker_count") or 4),
        identity_network=spec.get("frame_identity_network") or c["identity_network"],
        partner_identity_network=c.get("partner_identity_network") or "",
        partner_domain_suffix=c.get("partner_domain_suffix") or "",
        spire_addr=c.get("spire_addr") or "", spire_trust_domain=c.get("spire_trust_domain") or "",
        bind_address=str(c.get("bind_address") or ""),
        es_url=c.get("es_url") or "",
    )
    with open(compose_path, "w") as fh:
        fh.write(compose)
    notes.extend(f"compose: {n}" for n in adapt_notes)

    # 5. the federation sidecar's own config, named for the operator it fronts. BEFORE the markers, because the
    #    marker step is the last writer of this file and the one that proves no placeholder survived it.
    nginx_path = os.path.join(stack_dir, "nginx", "nginx-federation.conf")
    if os.path.exists(nginx_path):
        with open(nginx_path) as fh:
            nginx = fh.read()
        nginx, nginx_notes = adapt_federation_conf(nginx, safe=safe, domain=c["domain"])
        with open(nginx_path, "w") as fh:
            fh.write(nginx)
        notes.extend(nginx_notes)
    else:
        notes.append("nginx-federation.conf: absent from the bundle, nothing adapted")

    # 5b. the markers and the ACL file, the same renderer the registry used to call, with the same refusals: it
    #     raises rather than provisioning an operator whose terminators forward certificates its apps refuse.
    _load_provisioner().apply_operator_secrets(stack_dir, spec["operator_secrets"], spec["operator_name"])
    notes.append("markers rendered and the Redis ACL written")
    # ⚠ THE ONE STEP THAT NEEDS ROOT, DONE THROUGH THE SOCKET RATHER THAN BY BECOMING ROOT. `write_redis_acl`
    # chowns the ACL to uid 999 so the operator's Redis can read a 0600 file, and it degrades to a WARNING when it
    # cannot — so a one-shot running as uid 1000 would leave a file Redis cannot read.
    #
    # ⚠ AND THE TIMING RULES OUT "the runner fixes it after the job", measured rather than assumed: Redis starts
    # with `--aclfile`, a Redis that cannot read that file EXITS at startup, `restart: unless-stopped` turns that
    # into a crash loop, its healthcheck never passes, and `compose up -d` WAITS on `condition: service_healthy`.
    # The job would block to this module's 900 s ceiling and fail. There is no afterwards: it happens here, between
    # the ACL write and the up.
    acl_path = os.path.join(stack_dir, "redis-users.acl")
    out_acl = _fix_redis_acl_owner(acl_path, notes)

    # 6.5. the per-stack docker config. Without it `compose up` cannot pull the operator's images at all: the
    #      client that runs compose looks for auth in its own config, and the host's is not inherited (§pass65).
    username = str(spec.get("docker_username") or "")
    if spec.get("images_local") is True:
        # §HELLOFRAME lane 6 (2026-09-18): the images are LOCAL tags on this host (the export's own step loaded them
        # under IMAGES_PREFIX), so there is nothing to pull and no credential to write. A missing image then fails at
        # `up` in docker's own words, which is the honest failure; a config for a registry nobody dials is not.
        notes.append("images are local tags on this host (images_local): no docker config written, nothing to pull")
    elif username and spec.get("docker_pull_token"):
        cfg_dir = os.path.join(stack_dir, ".docker")
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_path = os.path.join(cfg_dir, "config.json")
        with open(cfg_path, "w") as fh:
            fh.write(docker_auth_config(username=username, token=spec["docker_pull_token"]))
        os.chmod(cfg_path, 0o600)
        notes.append(f"docker config written for {username}, 600")
        # DOCKER_CONFIG points at the config written here, which is what makes the pull below authenticate.
        os.environ["DOCKER_CONFIG"] = cfg_dir
    else:
        raise HostWorkRefused(
            "the spec carries no docker_username, so the stack would be brought up with no way to pull its images "
            "and would fail at the first 401. Nothing was brought up.")

    # 6. up. --no-build and no --pull: the images this operator runs are named by the tag its env carries.
    _files = ["-f", compose_path]
    _extra = []
    if out_dbtls.get("db_tls"):
        _extra = [os.path.join(stack_dir, DB_TLS_OVERRIDE)]
    if out_opa.get("opa"):
        _extra.append(os.path.join(stack_dir, OPA_OVERRIDE))
    if out_push.get("push"):
        _extra.append(os.path.join(stack_dir, PUSH_OVERRIDE))
    _ensure_bind_sources(compose_path, stack_dir, notes, extra_composes=_extra)
    # An image that does not know about an override never passes it, so the base file stays byte-identical for every
    # frame still running an older one.
    for _ovr in _extra:
        _files += ["-f", _ovr]
    _run(["docker", "compose"] + _files + ["--env-file", env_path, "up", "-d"], "compose up", notes,
         timeout=900)
    ps = subprocess.run(["docker", "compose"] + _files + ["--env-file", env_path, "ps", "-q"],
                        capture_output=True, text=True, timeout=120)
    count = len([l for l in (ps.stdout or "").splitlines() if l.strip()])
    notes.append(f"containers up: {count}")

    out: Dict[str, Any] = {"stack_dir": stack_dir, "container_count": count}
    out.update(out_dbtls)
    out.update(out_opa)
    out.update(out_push)
    out.update(out_acl)
    out.update(identity)
    # The edge, carried through UNCHANGED for the runner to write: it holds the /etc/nginx this frame's registry
    # deliberately does not have, and it reads these from the job RESULT (frame_runner.py:1061), so a job that
    # succeeds hands the edge over in the same breath. Rendered by the registry, from the one definition in
    # core/operator_compose, never by this container and never a second time.
    for _key in ("host_vhost", "sni_entry"):
        if spec.get(_key):
            out[_key] = spec[_key]
    # §PUSH: the public push vhost only with the relay it fronts (both halves or neither); the runner writes it beside
    # the console's, checked against spec.edge's push_host and push_port
    if out_push.get("push") and spec.get("push_vhost"):
        out["push_vhost"] = spec["push_vhost"]
    notes.append("edge: host_vhost and sni_entry carried through" if out.get("host_vhost")
                 else "edge: the spec carried no host_vhost, so the runner has nothing to write")
    out.update(_await_registry(f"cloud-op-{safe}-registry", notes))
    out.update(_await_schema(safe, notes))
    out.update(_first_boot_admin(f"cloud-op-{safe}-registry", notes))
    out.update(_stamp_operator_identity(safe, dict(spec.get("identity_stamps") or {}), notes))
    out.update(_create_auditor_role(safe, str(spec["operator_secrets"].get("AUDITOR_RO_PASSWORD") or ""), notes))
    if spec.get("parent_peer"):
        out.update(_register_parent_peer(safe, spec["parent_peer"], notes))
    else:
        notes.append("parent peer row: not asked for (the spec carries no parent_peer)")
    return out


def _await_schema(safe: str, notes: List[str], deadline_s: int = 180) -> Dict[str, Any]:
    """The operator's database must carry its own image's schema before anything here writes to it.

    ⚠ A HEALTHY REGISTRY IS NOT A MIGRATED DATABASE. The operator's compose runs
    `migration_bridge && alembic upgrade head 2>/dev/null; operator_seed; gunicorn` — stderr discarded, and `;`
    carrying on past a failure — so a migration that died left gunicorn serving 200 on a database with ZERO
    tables, and every step below reported "relation does not exist" one at a time, none of them naming the cause
    (beacon/jelgava, 2026-09-16). `/health` answering is the weakest possible evidence here: it is exactly the
    thing that stayed true while nothing else was.

    Three outcomes, never two. The head is read from the operator's OWN image rather than assumed, so this cannot
    go stale against a newer migration; if the head cannot be read the wait still requires a stamped
    alembic_version and SAYS it could not compare, which is a different answer from "the schema is right".
    """
    reg, db = f"cloud-op-{safe}-registry", f"cloud-op-{safe}-db"
    head = ""
    try:
        proc = subprocess.run(["docker", "exec", reg, "sh", "-c", "cd /app && alembic heads 2>/dev/null"],
                              capture_output=True, text=True, timeout=120)
        m = re.search(r"([0-9a-z][0-9a-z_]{3,})", (proc.stdout or "").strip())
        head = m.group(1) if m else ""
    except Exception:  # noqa: BLE001 — an unreadable head is reported, never fatal on its own
        head = ""
    deadline = time.monotonic() + deadline_s
    stamped = ""
    while time.monotonic() < deadline:
        proc = subprocess.run(
            ["docker", "exec", db, "psql", "-U", "registry", "-d", "agentvault_registry", "-tAc",
             "SELECT version_num FROM alembic_version LIMIT 1"], capture_output=True, text=True, timeout=60)
        stamped = (proc.stdout or "").strip()
        if stamped and (not head or stamped == head):
            notes.append(f"schema: alembic_version {stamped}"
                         + ("" if head else " (the image's head could not be read, so it was not compared)"))
            return {"schema_head": stamped, "schema_head_verified": bool(head)}
        time.sleep(3)
    tail = ""
    try:
        lp = subprocess.run(["docker", "logs", "--tail", "40", reg], capture_output=True, text=True, timeout=60)
        tail = ((lp.stdout or "") + (lp.stderr or "")).strip()[-800:]
    except Exception:  # noqa: BLE001
        tail = "<the registry container's log could not be read>"
    raise _failure_class()(
        f"the operator's database never reached its schema: alembic_version is {stamped or 'absent'} and the "
        f"image's head is {head or 'unreadable'}. The registry answers health on an unmigrated database, so every "
        f"step after this one would fail with \"relation does not exist\" and none of them would say why. "
        f"Registry log tail: {tail}")


def _await_registry(container: str, notes: List[str], deadline_s: int = 240) -> Dict[str, Any]:
    """Did the operator's own registry come up? Asked THROUGH the socket this container already holds.

    Three outcomes and never a guess: healthy with the seconds it took, not healthy within the deadline, or could
    not ask (no such container). "Up" is a count of containers, which a crash-looping registry satisfies.
    """
    started = time.time()
    last = ""
    while time.time() - started < deadline_s:
        probe = subprocess.run(["docker", "exec", container, "curl", "-sf", "-o", "/dev/null",
                                "-w", "%{http_code}", "http://localhost:8000/health"],
                               capture_output=True, text=True, timeout=30)
        last = (probe.stdout or probe.stderr or "").strip()[:120]
        if probe.returncode == 0 and last.endswith("200"):
            took = int(time.time() - started)
            notes.append(f"registry health: 200 after {took}s")
            return {"registry_healthy": True, "registry_health_seconds": took}
        if "No such container" in last or "is not running" in last:
            notes.append(f"registry health: could not ask ({last})")
            return {"registry_healthy": None, "registry_health_note": last}
        time.sleep(5)
    notes.append(f"registry health: not 200 within {deadline_s}s (last: {last})")
    return {"registry_healthy": False, "registry_health_note": last}



def _fix_redis_acl_owner(acl_path: str, notes: List[str], host_dir: Optional[str] = None) -> Dict[str, Any]:
    """Give the ACL file to uid 999 through the docker socket this container already holds.

    Not by running the whole one-shot as root: every other step here works as uid 1000 with the docker group, and
    a root one-shot would make this the only root-owned operator stack on the box — a difference nobody chose.
    The socket is root-equivalent by construction, so a throwaway container does the one privileged file operation
    and says so, which keeps the privilege visible instead of ambient.

    `host_dir` is the file's directory as the DOCKER DAEMON sees it, when that differs from where this process sees
    it: the one-shot mounts the stack root at the host's own path, but a frame registry on the socket route sees it
    at /host-stack, and a bind source is resolved on the host. Measured 2026-09-27 on sbx-beta (wp62opb): the socket
    route never called this at all, so every operator it provisioned got an ACL its Redis could not open.

    Reported either way: the result carries the path, the owner and whether anything still needs doing, so a
    caller that wants to check finds a fact rather than a promise.
    """
    def _uid():
        try:
            return os.stat(acl_path).st_uid
        except OSError:
            return None

    before = _uid()
    if before is None:
        notes.append("redis ACL: absent, so nothing to own (this bundle rendered none)")
        return {"redis_acl_path": acl_path, "redis_acl_uid": None, "redis_acl_chown_needed": False}
    if before == 999:
        notes.append("redis ACL: already owned by the redis uid")
        return {"redis_acl_path": acl_path, "redis_acl_uid": 999, "redis_acl_chown_needed": False}
    proc = subprocess.run(["docker", "run", "--rm", "-u", "0",
                           "-v", f"{host_dir or os.path.dirname(acl_path)}:/w", "alpine:3",
                           "chown", "999:1000", f"/w/{os.path.basename(acl_path)}"],
                          capture_output=True, text=True, timeout=180)
    after = _uid()
    if proc.returncode != 0 or after != 999:
        notes.append(f"redis ACL: STILL owned by uid {after} (chown exit {proc.returncode}: "
                     f"{(proc.stderr or '').strip()[:120]}) — Redis cannot start until this is fixed")
        return {"redis_acl_path": acl_path, "redis_acl_uid": after, "redis_acl_chown_needed": True}
    notes.append(f"redis ACL: chowned {before} -> 999 through the socket, so Redis can read it")
    return {"redis_acl_path": acl_path, "redis_acl_uid": 999, "redis_acl_chown_needed": False}

def _first_boot_admin(container: str, notes: List[str]) -> Dict[str, Any]:
    """The operator's own first-boot admin password, read from its log where it is printed once.

    It crosses back in the result for the same reason the pull token crossed forward: it is the OPERATOR'S
    credential, useless anywhere else, and the human who owns that operator has to receive it. The registry stores
    it; this container never keeps it. tail is generous because the banner is printed very early in boot and the
    registry produces thousands of lines before it is healthy (§pass65 learned that at tail=200).
    """
    proc = subprocess.run(["docker", "logs", "--tail", "5000", container], capture_output=True, text=True,
                          timeout=120)
    match = re.search(r"FIRST-BOOT ADMIN PASSWORD:\s*(\S+)", (proc.stdout or "") + (proc.stderr or ""))
    if not match:
        notes.append("first-boot admin password: not in the log (the operator may already have been booted)")
        return {"admin_password": ""}
    notes.append("first-boot admin password: captured")
    return {"admin_password": match.group(1)}


_SQL_SAFE = re.compile(r"^[A-Za-z0-9 ._:/@+-]{1,200}$")

def env_excluded_secrets(op_module=None) -> tuple:
    """Which minted secrets the operator is NOT handed, derived from the two lists that define them.

    ⚠ ONE HOME, and the build gate is what forced it: this was a local literal here while
    `OPERATOR_ENV_SECRET_NAMES` sat in the provisioner DEFINED AND NEVER READ. Two statements of the same rule,
    one of them inert — exactly the shape this route has been removing all day, and it shipped past review because
    both halves looked right in isolation. The subset is now computed from the provisioner's own lists, so adding a
    sixth secret decides its own fate in the place it is declared.
    """
    module = op_module if op_module is not None else _load_provisioner()
    names = tuple(getattr(module, "OPERATOR_SECRET_NAMES", ()) or ())
    handed = tuple(getattr(module, "OPERATOR_ENV_SECRET_NAMES", ()) or ())
    if not names or not handed:
        # An older provisioner has neither list; the operator then gets what it always got.
        return ()
    return tuple(n for n in names if n not in handed)

# The frame's auditor reads this operator's share register with these two tables and nothing else. Written as
# statements rather than a script so each one's failure is its own sentence.
_AUDITOR_RO_SQL = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'auditor_ro') THEN "
    "CREATE ROLE auditor_ro LOGIN PASSWORD '{pw}'; ELSE ALTER ROLE auditor_ro LOGIN PASSWORD '{pw}'; END IF; END $$;",
    "GRANT CONNECT ON DATABASE agentvault_registry TO auditor_ro;",
    "GRANT USAGE ON SCHEMA public TO auditor_ro;",
    # ⚠ EXACTLY THE TABLES THE AUDITOR'S VENUE PATH READS, AND NOT ONE MORE. The five queries it runs against a
    # venue (SHARE_LISTINGS, SHARE_TOP_HOLDERS, SHARE_LAST_PRICE, SHARE_ACTIVITY, SHARE_SPARK) read
    # org_share_positions, exchange_listings and exchange_trades. This grant named the first two, so three of the
    # five answered `permission denied for table exchange_trades` and the venue read as unreachable
    # (beacon/jelgava, agentvault2-6a, 2026-09-16). The frame's own standup driver grants ALL TABLES plus default
    # privileges; matching that would be copying a weakness. An auditor's whole value is that it cannot be the
    # thing it checks, and every table it cannot read is a table it cannot be accused of having written.
    # tests/test_operator_runner_branch.py DERIVES this set from the auditor's own source, so the two cannot drift.
    "GRANT SELECT ON org_share_positions, exchange_listings, exchange_trades TO auditor_ro;",
)

# The venue queries the frame's auditor runs, by NAME, so the test below reads the same five the product runs
# rather than every SQL constant in that file (the supply-audit ones read tables no venue role should touch).
AUDITOR_VENUE_QUERIES = ("SHARE_LISTINGS_SQL", "SHARE_TOP_HOLDERS_SQL", "SHARE_LAST_PRICE_SQL",
                         "SHARE_ACTIVITY_SQL", "SHARE_SPARK_SQL")


def _create_auditor_role(safe: str, password: str, notes: List[str]) -> Dict[str, Any]:
    """A read-only role for the frame's auditor, in the operator's own database.

    §OPDIST (2026-09-16), agentvault2-6a's finding: all 13 fleet venue DSNs use `registry`, the database OWNER, so
    every auditor holds a credential that can REWRITE the share register it audits. That is an integrity flaw
    rather than a style point — an auditor's whole value is that it cannot be the thing it checks. This role can
    SELECT two tables and do nothing else.

    The password is minted by the registry with the operator's other secrets and never written into the operator's
    env; the runner puts the DSN in the frame's venue carrier.
    """
    if not password:
        notes.append("auditor_ro: no password in the spec, so no read-only role was created")
        return {"auditor_ro_created": False}
    if "'" in password or "\\" in password:
        raise HostWorkRefused("the auditor_ro password carries a quote or backslash; refused rather than escaped")
    for sql in _AUDITOR_RO_SQL:
        proc = subprocess.run(["docker", "exec", f"cloud-op-{safe}-db", "psql", "-U", "registry",
                               "-d", "agentvault_registry", "-v", "ON_ERROR_STOP=1", "-c", sql.format(pw=password)],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            # Named, never swallowed: without the role the frame's auditor either cannot read this venue at all or
            # falls back to the owner credential, and the second is worse than the first.
            notes.append(f"auditor_ro: FAILED ({(proc.stderr or '').strip()[:140]})")
            return {"auditor_ro_created": False}
    notes.append("auditor_ro: role created with SELECT on org_share_positions and exchange_listings")
    return {"auditor_ro_created": True}

# The parent's row in the OPERATOR's own database. The TEXT lives here and the VALUES come from the spec: the
# registry supplies values, the one-shot supplies structure, and that is the line this whole seam is drawn along.
# Fields and their reasons are §pass73.3.5 and §BATCH5 — an approved terminal state (the parent spawned this
# operator, so a downstream approval is ceremony), `peer_type='frame'` written at creation because the reclassify
# pass only runs at boot, and the parent's trust_domain seeded so cross-frame resolution does not fall back to BFS.
_BILATERAL_PEER_SQL = (
    "INSERT INTO peer_registries (name, base_url, status, owner_developer_id, "
    "admin_contact_email, registered_at, approved_at, approved_by_developer_id, "
    "discovery_auth_info, health_check_failure_count, total_interactions, "
    "disputes_lost_with, bayesian_discount, trust_domain, peer_type) "
    "VALUES ('{name}', '{url}', 'ACTIVE', 1, '{email}', NOW(), NOW(), 1, '{{}}'::jsonb, 0, 0, 0, 1.0, "
    "'{trust_domain}', 'frame') "
    "ON CONFLICT (name) DO UPDATE SET base_url = '{url}', status = 'ACTIVE', peer_type = 'frame', "
    "trust_domain = COALESCE(peer_registries.trust_domain, EXCLUDED.trust_domain), "
    "approved_at = COALESCE(peer_registries.approved_at, NOW()), "
    "approved_by_developer_id = COALESCE(peer_registries.approved_by_developer_id, 1);"
)


def _register_parent_peer(safe: str, peer: Dict[str, Any], notes: List[str]) -> Dict[str, Any]:
    """Bilateral federation's other half: the parent, in the operator's database.

    Without it the operator does not know the frame that made it, so nothing federates back and the operator is
    half a peer. Every value is checked against a conservative shape first — these go into SQL text, and a value
    that cannot be checked is refused rather than escaped by hand.
    """
    values = {"name": str(peer.get("name") or ""), "url": str(peer.get("base_url") or ""),
              "email": str(peer.get("admin_contact_email") or ""), "trust_domain": str(peer.get("trust_domain") or "")}
    bad = [k for k, v in values.items() if not _SQL_SAFE.match(v)]
    if bad:
        raise HostWorkRefused(f"the parent peer row has values this module will not put in SQL text: {bad}")
    proc = subprocess.run(
        ["docker", "exec", f"cloud-op-{safe}-db", "psql", "-U", "registry", "-d", "agentvault_registry",
         "-v", "ON_ERROR_STOP=1", "-c", _BILATERAL_PEER_SQL.format(**values)],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        # Not fatal, and SAID rather than swallowed: the operator runs, it is simply not yet bilateral, and that is
        # a sentence a human can act on. A silent failure here is how an operator ends up half federated.
        notes.append(f"parent peer row: FAILED (psql exit {proc.returncode}: {(proc.stderr or '').strip()[:160]})")
        return {"parent_peer_registered": False}
    notes.append(f"parent peer row: {values['name']} -> {values['url']}")
    return {"parent_peer_registered": True}


def _update_spire_svid_sans(spec: Dict[str, Any], notes: List[str]) -> Dict[str, Any]:
    """Step 2b: give the operator's svid-writer SVID the hostnames it will actually be dialled by.

    The SAN LIST is built by core.operator_compose.svid_dns_sans, which carries the three findings that make it
    non-obvious (SPIRE's UNIQUE(entry, dns), the missing `nginx-teg` that killed every treasury call from birth,
    and the partner-suffix alias). What is here is only the exec, because the container it talks to differs: the
    registry uses the Docker SDK, this uses the CLI against the socket the runner mounted.
    """
    fingerprint = str(spec.get("spire_fingerprint") or "")
    container = str(spec.get("spire_container") or "")
    trust_domain = str(spec.get("spire_trust_domain") or "")
    if not (fingerprint and container and trust_domain):
        notes.append("SPIRE DNS SANs: not asked for (the spec carries no fingerprint, container or trust domain)")
        return {}
    safe = spec["safe_name"]
    svid_spiffe = f"spiffe://{trust_domain}/operator/{safe}/svid-writer"
    show = subprocess.run(["docker", "exec", container, "/opt/spire/bin/spire-server", "entry", "show",
                           "-spiffeID", svid_spiffe], capture_output=True, text=True, timeout=120)
    entry_id = ""
    spiffe_from_entry = ""
    for line in (show.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Entry ID") and not entry_id:
            entry_id = stripped.split(":")[-1].strip()
        elif stripped.startswith("SPIFFE ID") and not spiffe_from_entry:
            spiffe_from_entry = stripped.split(":", 1)[-1].strip()
    if not entry_id:
        notes.append(f"SPIRE DNS SANs: no entry for {svid_spiffe} (nothing updated)")
        return {}
    federates = [l.split(":", 1)[-1].strip() for l in (show.stdout or "").splitlines()
                 if l.strip().startswith("FederatesWith")]
    from agentvault_registry.core.operator_compose import svid_dns_sans
    c = dict(spec.get("compose") or {})
    sans = svid_dns_sans(domain=c.get("domain") or "", safe=safe,
                         partner_identity_network=c.get("partner_identity_network") or "",
                         partner_domain_suffix=c.get("partner_domain_suffix") or "")
    cmd = ["docker", "exec", container, "/opt/spire/bin/spire-server", "entry", "update",
           "-entryID", entry_id, "-spiffeID", svid_spiffe,
           "-parentID", f"spiffe://{trust_domain}/spire/agent/x509pop/{fingerprint}",
           "-selector", "docker:label:com.agentvault.service:svid-writer-operator",
           "-x509SVIDTTL", "14400"]
    for host in sans:
        cmd += ["-dns", host]
    for td in federates:
        cmd += ["-federatesWith", td]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        # SAID, not swallowed: an SVID without its hostname SANs fails every mTLS dial by hostname mismatch, and
        # nothing else in the provision notices (§MONEY-R48 stayed invisible for months for exactly this reason).
        notes.append(f"SPIRE DNS SANs: FAILED (exit {proc.returncode}: {(proc.stderr or '').strip()[:160]})")
        return {"operator_spiffe_id": spiffe_from_entry or svid_spiffe}
    notes.append(f"SPIRE DNS SANs: {sans} (federatesWith preserved: {federates or 'none'})")
    # The identity ITSELF, read back from the entry that mints it rather than composed by whoever needs it next
    # (agentvault2-6a's ask, and the right instinct): the runner writes this into the frame's directory readers
    # file, and a composed `spiffe://<td>/operator/<safe>/svid-writer` would be a second place for that shape to
    # rot. What SPIRE says the entry IS beats what anyone spells.
    return {"operator_spiffe_id": spiffe_from_entry or svid_spiffe}


_STAMP_SQL_SELF = ("INSERT INTO registry_self (id, federation_name) VALUES (1, '{federation_name}') "
                   "ON CONFLICT (id) DO UPDATE SET federation_name = EXCLUDED.federation_name, updated_at = NOW();")


def _stamp_operator_identity(safe: str, stamps: Dict[str, Any], notes: List[str]) -> Dict[str, Any]:
    """The operator's own federation identity, in its own database.

    `registry_self.federation_name` is the AUTHORITATIVE source for _get_display_name(); the developer's
    display_name stamp stays beside it for the transition. ⚠ §LOCTRUTH: a latitude and longitude are stamped ONLY
    when the caller says the location was DECLARED, because the developer row's coordinates are what
    federation_sync publishes onto every exported agent card, and a curated globe position written there became a
    geographic claim on a signed card ("the location of the agent is made up").
    """
    done = {}
    name = str(stamps.get("display_name") or safe)
    if not _SQL_SAFE.match(name):
        raise HostWorkRefused(f"display_name {name!r} is not a value this module will put in SQL text")
    parts = [f"display_name='{name}'"]
    if stamps.get("location_is_declared") and stamps.get("latitude") is not None \
            and stamps.get("longitude") is not None:
        parts.append(f"latitude={float(stamps['latitude'])}")
        parts.append(f"longitude={float(stamps['longitude'])}")
        label = str(stamps.get("location_label") or "").replace("$", "")  # dollar-quote hygiene, as the registry does
        if label:
            parts.append(f"location_label=$tag${label}$tag$")
    for what, sql in (("developer display_name", f"UPDATE developers SET {', '.join(parts)} WHERE is_admin = true;"),
                      ("registry_self", _STAMP_SQL_SELF.format(federation_name=name))):
        proc = subprocess.run(["docker", "exec", f"cloud-op-{safe}-db", "psql", "-U", "registry",
                               "-d", "agentvault_registry", "-v", "ON_ERROR_STOP=1", "-c", sql],
                              capture_output=True, text=True, timeout=120)
        ok = proc.returncode == 0
        done[what] = ok
        notes.append(f"{what}: {'stamped' if ok else 'FAILED ' + (proc.stderr or '').strip()[:120]}")
    return {"identity_stamped": all(done.values())}


def do_host_work(spec: Dict[str, Any]) -> Dict[str, Any]:
    notes: List[str] = []
    phase = str(spec.get("phase") or "full").lower()
    if phase not in PHASES:
        raise HostWorkRefused(f"phase {phase!r} is not one this module serves ({', '.join(PHASES)}). Nothing was done.")
    notes.append(f"phase: {phase}")
    result: Dict[str, Any] = {"phase": phase, "notes": notes}

    if phase in ("bundle", "full"):
        result.update(_bundle_step(spec, notes))
    if phase == "bundle":
        return result

    bundle_path = result.get("bundle_path") or _existing_bundle(spec, notes)
    result.update(_stack_steps(spec, bundle_path, notes))
    return result


def main() -> int:
    spec_path = os.getenv("OPERATOR_SPEC")
    result_path = os.getenv("OPERATOR_RESULT")
    if not spec_path or not result_path:
        print("OPERATOR_SPEC and OPERATOR_RESULT must both be set", file=sys.stderr)
        return 2
    try:
        spec = read_spec(spec_path)
        result = do_host_work(spec)
    except HostWorkRefused as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except HostWorkFailed as exc:
        # Exit 4, never 3: the runner records a refusal as "nothing was done", and by here something was.
        print(f"{exc} · ALREADY WRITTEN: {', '.join(_SIDE_EFFECTS) or 'unknown'}", file=sys.stderr)
        return 4
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 4
    # The result must carry what its OWN phase promises. Checked here as well as in the caller because a result
    # that is short a key is a row the registry cannot write, and the cheapest place to learn that is before this
    # container exits (its filesystem, and every note in it, goes away on return).
    want = RESULT_KEYS_BY_PHASE[str(result.get("phase") or "full")]
    short = [k for k in want if k not in result]
    if short:
        print(f"the {result.get('phase')} phase finished without {short}", file=sys.stderr)
        return 4
    with open(result_path, "w") as fh:
        json.dump(result, fh, indent=1)
    # ⚠ 0600 HERE, NOT ONLY AT THE RUNNER. This file carries the operator's first-boot admin password back across
    # the seam, and it was written 0644 — world-readable on the frame's filesystem for as long as it sits there.
    # The runner chmods it, but the runner runs whatever image the allowlist names, so an older one-shot keeps
    # writing 0644 and only the writer can close that. (agentvault2-6a, 2026-09-16.)
    os.chmod(result_path, 0o600)
    # One line for the runner's log: what this job did, in the words of the phase it was asked for.
    # ⚠ THIS LINE CRASHED A SUCCESSFUL JOB. It named bundle keys unconditionally, so a STACK result — which has
    # no bundle_filename, by the contract two lines above — raised KeyError AFTER result.json was written: exit 1,
    # the runner marked the job failed, the registry answered 500, and an operator that was up with ten healthy
    # containers had no edge, no ACL net and no links (beacon/jelgava, job 7db049e854644bff, 2026-09-14). The one
    # table that already knows which keys a phase has is RESULT_KEYS_BY_PHASE; asking anything else is a second
    # copy of the answer, and this is what the second copy cost.
    _summary = {"phase": result.get("phase")}
    for _k in RESULT_KEYS_BY_PHASE.get(str(result.get("phase") or "full"), ()):
        if _k in result and _k != "notes":
            _summary[_k] = result[_k]
    print(json.dumps(_summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
