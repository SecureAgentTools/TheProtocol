"""
f052: Agent SPIRE Identity Service (IRONHAND)

Manages SPIRE workload entries for individual agents. Agents opt-in to mTLS
via POST /api/v1/agent/enable-mtls, which creates a SPIRE entry here.

Each agent gets:
  SPIFFE ID:  spiffe://<trust_domain>/agent/{sanitized_did}
  Selector:   docker:label:com.theprotocol.agent-did:{sanitized_did}
  Parent:     SPIRE agent fingerprint (mainframe on central, operator-local elsewhere)
  TTL:        1800 seconds (30 minutes)

Two execution paths:
  Local  — docker.sock is mounted (central registry) → exec spire-server CLI.
  Proxy  — operator registries have no docker.sock → POST to central registry's
           /admin/ironhand/register-agent-proxy using federation-internal auth.
"""
import json
import logging
import os
import re
from typing import Optional

import docker
import httpx

logger = logging.getLogger(__name__)

# --- Constants (shared with operator_provisioner.py) ---
SPIRE_CONTAINER = os.getenv("SPIRE_CONTAINER", "agentvault-spire-server")
SPIRE_BINARY = "/opt/spire/bin/spire-server"
TRUST_DOMAIN = os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")

# §pass32 Phase 6 — trust-domain-aware SPIRE routing.
# Maps trust domain → SPIRE server container name. The local TRUST_DOMAIN
# always resolves to SPIRE_CONTAINER. Additional entries via env let a
# central registry that has docker.sock access to multiple SPIRE servers
# (e.g., agentvault-spire-server AND frame-b-spire-server on the same host)
# route register/delete proxy calls to the correct one based on the
# requesting peer's trust domain.
#
# Env format (JSON object): {"agentvault.com":"agentvault-spire-server","frame-b.theprotocol.cloud":"frame-b-spire-server"}
_SPIRE_TD_MAP_RAW = os.getenv("SPIRE_CONTAINERS_BY_TRUST_DOMAIN", "")
try:
    SPIRE_CONTAINERS_BY_TRUST_DOMAIN: dict[str, str] = (
        json.loads(_SPIRE_TD_MAP_RAW) if _SPIRE_TD_MAP_RAW else {}
    )
    if not isinstance(SPIRE_CONTAINERS_BY_TRUST_DOMAIN, dict):
        raise ValueError("SPIRE_CONTAINERS_BY_TRUST_DOMAIN must be a JSON object")
except (json.JSONDecodeError, ValueError) as _e:
    logger.warning(
        f"[IRONHAND] Invalid SPIRE_CONTAINERS_BY_TRUST_DOMAIN env (using empty): {_e}"
    )
    SPIRE_CONTAINERS_BY_TRUST_DOMAIN = {}
# Always include our own trust domain → own SPIRE container.
SPIRE_CONTAINERS_BY_TRUST_DOMAIN.setdefault(TRUST_DOMAIN, SPIRE_CONTAINER)


def _container_for_trust_domain(trust_domain: Optional[str]) -> str:
    """Resolve the SPIRE server container for a given trust domain.

    Falls back to the local SPIRE_CONTAINER if trust_domain is None or not
    present in the map — preserves single-trust-domain behavior unchanged.
    """
    if not trust_domain:
        return SPIRE_CONTAINER
    return SPIRE_CONTAINERS_BY_TRUST_DOMAIN.get(trust_domain, SPIRE_CONTAINER)


def _extract_trust_domain(spiffe_id: str) -> Optional[str]:
    """Extract the trust domain from a SPIFFE ID.

    spiffe://<trust_domain>/<path> → <trust_domain>
    Returns None if the input is not a valid SPIFFE URL.
    """
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        return None
    rest = spiffe_id[len("spiffe://"):]
    return rest.split("/", 1)[0] or None

# Mainframe SPIRE agent fingerprint (from `spire-server agent list`)
# This is the parent ID for agent entries when this registry IS the central
# (i.e., has docker.sock). Operator registries override via
# OPERATOR_SPIRE_AGENT_FINGERPRINT env.
MAINFRAME_AGENT_FINGERPRINT = "4605f28668400214f85bba13ba375b226f907007"


class SpireParentUnresolved(RuntimeError):
    """No SPIRE agent node on THIS frame can parent a new agent identity (findings row 198).

    Raised rather than falling back to another frame's node: the entry such a fallback creates
    is syntactically fine and permanently unusable, and every signal downstream reads healthy.
    The message is written to be read by whoever hit the endpoint, and carries the doc link.
    """

SVID_TTL = "1800"  # 30 minutes (reduced from 4h for faster hard revocation)

# --- Mode detection (module load time) ---
# Central registries mount /var/run/docker.sock for SPIRE CLI access.
# Operator registries intentionally don't mount it (security boundary). When
# absent, register/delete are proxied over federation auth to the central
# registry which owns the SPIRE server.
_LOCAL_SPIRE_AVAILABLE = os.path.exists("/var/run/docker.sock")

IRONHAND_MODE_ENV = "IRONHAND_SPIRE_MODE"


def ironhand_mode() -> str:
    """How IRONHAND reaches SPIRE: "local" (docker exec into this frame's server), "proxy" (the central registry's
    IRONHAND proxy), or "runner" (§F6 WP6.1, 2026-09-26: the frame runner's identity ops, on this frame's OWN server,
    which is what a frame without the docker socket has). Unset or "auto" keeps the import-time choice byte for byte
    (local where the docker socket is mounted, proxy elsewhere); a value this code does not know raises, so a typo never
    lands on another path."""
    v = (os.getenv(IRONHAND_MODE_ENV) or "").strip().lower()
    if v in ("", "auto"):
        return "local" if _LOCAL_SPIRE_AVAILABLE else "proxy"
    if v in ("local", "proxy", "runner"):
        return v
    raise RuntimeError(f"{IRONHAND_MODE_ENV}={v!r} is not local, proxy, runner or auto")


def _runner_own_frame(trust_domain: Optional[str]) -> None:
    """The runner acts on the CALLING frame's server only, so another trust domain is a refusal, said here first."""
    if trust_domain and trust_domain != TRUST_DOMAIN:
        raise RuntimeError(f"IRONHAND runner mode acts on this frame's own SPIRE server ({TRUST_DOMAIN}); "
                           f"{trust_domain} is another frame's")


def _spire_text(argv_tail: list) -> tuple:
    """(rc, stdout) of one READ-ONLY spire-server call on this frame's server, by the IRONHAND mode: the runner's op
    ("runner") or docker exec ("local"). Raises when neither answers; never called in proxy mode."""
    if ironhand_mode() == "runner":
        from agentvault_registry.services import spire_ops_client as _soc
        rc, out, _err = _soc.run_argv([SPIRE_BINARY] + list(argv_tail))
        return rc, out
    container = _get_docker_client().containers.get(SPIRE_CONTAINER)
    exit_code, output = container.exec_run([SPIRE_BINARY] + list(argv_tail), demux=True)
    return exit_code, (output[0] or b"").decode("utf-8", errors="replace")


def _get_docker_client() -> docker.DockerClient:
    return docker.DockerClient(base_url="unix:///var/run/docker.sock")


# Module-level cache for the auto-detected local SPIRE agent fingerprint.
# Populated on first lookup, never invalidated (fingerprint is stable for the
# lifetime of the SPIRE agent's x509pop cert; cert rotation requires registry
# restart anyway).
_cached_local_fingerprint: Optional[str] = None


def _autodetect_local_fingerprint() -> Optional[str]:
    """Auto-detect the local SPIRE agent fingerprint by querying SPIRE for
    this registry's own service entry and extracting its parentID.

    The registry registers a service identity at `spiffe://<td>/service/registry-<safe>`
    whose parent is the local spire-agent — so the parent fingerprint of OUR
    OWN entry IS the local agent fingerprint we need to use for agent entries.

    Returns the 40-char SHA1 fingerprint, or None if detection fails (e.g.,
    no docker.sock, registry's own entry doesn't exist yet, etc.).

    §pass31 Phase 4 fix — replaces the hardcoded MAINFRAME_AGENT_FINGERPRINT
    fallback which was wrong on sandbox-A + Frame B.
    """
    global _cached_local_fingerprint
    if _cached_local_fingerprint:
        return _cached_local_fingerprint

    if ironhand_mode() == "proxy":
        return None  # operator registry → proxy path, no docker.sock

    candidates = own_entry_candidates()
    if not candidates:
        return None

    # §F6 WP6.1 (2026-09-26): each candidate answers for itself. The single try around the whole loop let the FIRST
    # candidate's failure end the search: through the frame runner a malformed id is refused, the refusal raised, and
    # the valid /service/registry was never asked (every enrollment 503 on a runner-mode frame, logged at DEBUG only).
    tried = []
    for cand in candidates:
        try:
            exit_code, stdout = _spire_text(["entry", "show", "-spiffeID", cand])
        except Exception as e:  # noqa: BLE001 — this candidate's failure, never the search's
            tried.append(f"{cand}: {type(e).__name__}: {str(e)[:160]}")
            continue
        if exit_code != 0:
            tried.append(f"{cand}: rc {exit_code}")
            continue
        # Match: "Parent ID         : spiffe://<td>/spire/agent/x509pop/<40-hex>"
        match = re.search(r"x509pop/([a-f0-9]{40})", stdout)
        if not match:
            tried.append(f"{cand}: no entry with an x509pop parent")
            continue
        fp = match.group(1)
        _cached_local_fingerprint = fp
        logger.info(
            f"[IRONHAND] Auto-detected local SPIRE agent fingerprint: {fp[:8]}... "
            f"(via own service entry {cand})"
        )
        return fp
    logger.warning(
        "[IRONHAND] no own service entry found, so the local SPIRE agent cannot be auto-detected: "
        + "; ".join(tried)
    )
    return None


_SPIFFE_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


def own_entry_candidates() -> list:
    """The SPIFFE ids this registry's own service entry may be registered under, each a VALID id.

    🔴 findings row 198 — LOOK FOR EVERY NAME THIS SERVICE IS ACTUALLY REGISTERED UNDER. The frame template registers the
    service as plain `/service/registry` and, since §F5, `/service/<slug>-registry` beside it; a legacy registry that sets
    REGISTRY_SAFE_NAME is `/service/registry-<safe>` (the name `_proxy_spiffe_id()` composes, and the more specific one,
    so it is asked first). §F6 WP6.1 (2026-09-26): `_derive_safe_name()` falls back to lowercasing REGISTRY_NAME, the
    DISPLAY name, so "Sandbox Beta" composed `/service/registry-sandbox beta`, an id no SPIRE server can hold; such a
    candidate is not composed at all. The derived name is kept where it IS a valid id, because Frame A depends on it
    (REGISTRY_NAME "Registry-A", no REGISTRY_SAFE_NAME, its entry registered as `/service/registry-a`: measured
    2026-09-26). The frame template's two names follow, the second from the frame's SLUG (core.frame_slug, the prefix
    its containers carry; this module reads no in-frame URL itself), never from a label."""
    from ..core.frame_slug import frame_slug
    out = []
    legacy = _proxy_spiffe_id()
    if "/service/registry-unknown" not in legacy:      # neither REGISTRY_SAFE_NAME nor REGISTRY_NAME: nothing to compose
        out.append(legacy)
    out.append(f"spiffe://{TRUST_DOMAIN}/service/registry")
    slug = frame_slug()
    if slug:
        out.append(f"spiffe://{TRUST_DOMAIN}/service/{slug}-registry")
    valid = []
    for cand in out:
        path = cand.split("://", 1)[-1].partition("/")[2]
        if cand not in valid and path and all(_SPIFFE_SEGMENT.fullmatch(seg) for seg in path.split("/")):
            valid.append(cand)
    return valid


def live_agent_fingerprints() -> Optional[set]:
    """The fingerprints of SPIRE agent nodes that ACTUALLY EXIST on this frame.

    findings row 198 — the durable half. Resolving a parent is a guess until it is checked
    against the nodes that can attest a workload: an entry parented to a node this frame has
    never seen is not a slow failure, it is a permanent one, and nothing downstream reports it.

    Returns None when the list cannot be read (no docker socket, proxy path, server down) —
    UNKNOWN, which the caller must not treat as "empty" and must not treat as "fine".
    """
    if ironhand_mode() == "proxy":
        return None
    try:
        exit_code, stdout = _spire_text(["agent", "list"])
        if exit_code != 0:
            return None
        found = set(re.findall(r"x509pop/([a-f0-9]{40})", stdout))
        return found or None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[IRONHAND] could not list SPIRE agent nodes: {e}")
        return None


def _parent_fingerprint_for_self() -> str:
    """Fingerprint of THIS registry's parent SPIRE agent.

    Resolution order (most specific wins):
      1. OPERATOR_SPIRE_AGENT_FINGERPRINT env — explicit override (testing, edge cases)
      2. Auto-detect via SPIRE query on registry's OWN service entry — preferred
      3. MAINFRAME_AGENT_FINGERPRINT — legacy fallback for mainframe registry

    §pass31 Phase 4 fix (2026-05-17): added auto-detect step (2). Before this,
    sandbox-A + Frame B registries fell through to mainframe fingerprint,
    producing SPIRE entries with wrong parentID → PERMISSION_DENIED on workload
    attestation. Auto-detect removes the need for the OPERATOR_SPIRE_AGENT_FINGERPRINT
    env var workaround on those frames.
    """
    explicit = os.getenv("OPERATOR_SPIRE_AGENT_FINGERPRINT")
    if explicit:
        return explicit
    auto = _autodetect_local_fingerprint()
    if auto:
        return auto
    # 🔴 findings row 198 — DO NOT HAND BACK ANOTHER FRAME'S NODE. `MAINFRAME_AGENT_FINGERPRINT`
    # is Frame A's, hardcoded. On any other frame it names a node that does not exist, so the
    # entry it produces can never be attested — a 200 that means "never". §pass31 cured the
    # instance of this on sandbox-A and Frame B and left the fallback in place, so it returned
    # the moment a frame named its registry service differently. It is kept ONLY when it is
    # genuinely one of this frame's live nodes; otherwise the caller is told, in words.
    live = live_agent_fingerprints()
    if live is not None and MAINFRAME_AGENT_FINGERPRINT not in live:
        raise SpireParentUnresolved(
            "This registry cannot determine which SPIRE agent should parent the new identity: "
            "auto-detection found no service entry for this registry, and the built-in fallback "
            f"({MAINFRAME_AGENT_FINGERPRINT[:8]}…) is not one of this frame's "
            f"{len(live)} live agent node(s). Issuing anyway would create a SPIRE entry that no "
            "agent can ever attest, and the workload would receive PERMISSION_DENIED forever. "
            "Fix: set OPERATOR_SPIRE_AGENT_FINGERPRINT to this frame's spire-agent node, or "
            "register this registry's own /service/registry entry so it can be auto-detected. "
            "How mTLS identities are issued: https://docs.theprotocol.cloud/learn/security"
        )
    return MAINFRAME_AGENT_FINGERPRINT


def _derive_safe_name() -> Optional[str]:
    """Determine this registry's SAFE_NAME slug for SPIFFE/federation paths.

    Operator registries explicitly set REGISTRY_SAFE_NAME (via cloud_provisioner).
    Mainframe / sandbox-A / Frame-B registries don't — derive from REGISTRY_NAME:

      REGISTRY_NAME           → REGISTRY_SAFE_NAME derived
      "Registry-A"            → "a"
      "Registry-Test"         → "test"
      "Frame-B"               → "frame-b"
      "Registry-Sandbox-Beta" → "sandbox-beta"

    Returns None if neither env var is set.
    """
    explicit = os.getenv("REGISTRY_SAFE_NAME")
    if explicit:
        return explicit
    name = os.getenv("REGISTRY_NAME", "")
    if not name:
        return None
    safe = name.lower()
    if safe.startswith("registry-"):
        safe = safe[len("registry-"):]
    return safe


def _proxy_spiffe_id() -> str:
    """SPIFFE ID this registry claims when calling the central proxy endpoint.

    Used in the X-Federation-SPIFFE-ID header; validated by
    `require_peer_registry_identity`. Format must contain `/service/registry-`.
    """
    safe = _derive_safe_name() or "unknown"
    return f"spiffe://{TRUST_DOMAIN}/service/registry-{safe}"


def _central_registry_url() -> str:
    """URL of the central registry that owns our SPIRE server."""
    return os.getenv("CENTRAL_REGISTRY_URL", "").rstrip("/")


def _proxy_headers() -> dict:
    """Headers for proxying SPIRE admin calls to central registry.

    Uses the canonical federation-auth pattern (X-Federation-Secret +
    X-Federation-SPIFFE-ID) consumed by core/federation_auth.py:get_federation_identity.
    """
    h = {
        "X-Federation-Secret": os.getenv("FEDERATION_INTERNAL_SECRET", ""),
        "X-Federation-SPIFFE-ID": _proxy_spiffe_id(),
        "Content-Type": "application/json",
    }
    # §2026-06-07: cloud-ops authenticate to their parent frame's central via the
    # Mode-3 federation LICENSE (the internal secret is empty cluster-wide, and
    # frames do not share licenses — each op uses its own frame's license against
    # its own frame's central). The license is a REGISTRY credential; agents never
    # see it. Without this header the proxy enrol call 401s. See get_federation_identity.
    _lic = os.getenv("FEDERATION_LICENSE_KEY", "")
    if _lic:
        h["X-Federation-License"] = _lic
    return h


def _proxy_post(name: str, body: dict) -> httpx.Response:
    """§OPLANE (V0614): one IRONHAND proxy call to the frame that owns the SPIRE server. Its federation lane first (the
    parent's mTLS address kept by core/parent_lane, this node's SVID, the /api/v1/federation/ironhand alias); the console
    path (CENTRAL_REGISTRY_URL + /api/v1/admin/ironhand) when the lane is unknown here, cannot be dialled, or the parent
    predates the alias. EU's and ASIA's public console vhosts clear every federation credential (the licence too), so on
    that path an operator's agent could enrol nowhere on production. A lane that was reached is never retried."""
    from agentvault_registry.core import parent_lane
    origin = parent_lane.cached_origin()
    verify = parent_lane.client_verify(origin) if origin else None
    if origin and verify is not None:
        try:
            with httpx.Client(timeout=20.0, verify=verify) as client:
                resp = client.post(f"{origin}/api/v1/federation/ironhand/{name}", json=body, headers=_proxy_headers())
            if not parent_lane.route_missing(resp.status_code, resp.text):
                return resp
            logger.info("[IRONHAND] the parent serves no federation alias for %s yet: the console path", name)
        except httpx.ConnectError as e:
            logger.warning("[IRONHAND] the parent's federation lane cannot be dialled (%s): the console path",
                           type(e).__name__)
    with httpx.Client(timeout=20.0) as client:
        return client.post(f"{_central_registry_url()}/api/v1/admin/ironhand/{name}", json=body,
                           headers=_proxy_headers())


def sanitize_did_for_spiffe(did: str) -> str:
    """Sanitize a DID for use in SPIFFE paths and Docker label selectors.

    SPIFFE paths cannot contain colons, and SPIRE's CLI selector format
    `docker:label:KEY:VALUE` uses colons as delimiters. Replacing colons
    with hyphens avoids parsing ambiguity while keeping the mapping reversible.

    Example: did:theprotocol:4c783710-64d5-f8c3-3f6c
           → did-theprotocol-4c783710-64d5-f8c3-3f6c
    """
    return did.replace(":", "-")


def unsanitize_did(sanitized: str) -> str:
    """Reverse sanitize_did_for_spiffe: first two hyphens back to colons.

    Example: did-theprotocol-4c783710-64d5-f8c3-3f6c
           → did:theprotocol:4c783710-64d5-f8c3-3f6c
    """
    # DID format: method:scheme:identifier — replace first two hyphens
    parts = sanitized.split("-", 2)
    if len(parts) >= 3:
        rest = parts[2]
        # §DIDWIDEN item 1: did:theprotocol:<issuer>:<uuid4> sanitizes to did-theprotocol-<issuer>-<uuid4>.
        # The uuid tail is fixed-length (36) and the issuer is DNS-shaped, so the third colon is
        # unambiguous: restore it when the tail is a uuid4 and the head is a valid issuer.
        if len(rest) > 37 and rest[-37] == "-":
            head, tail = rest[:-37], rest[-36:]
            try:
                from ..identifiers import UUID4_DID_SUFFIX_RE, valid_issuer
                if UUID4_DID_SUFFIX_RE.match(tail) and valid_issuer(head):
                    rest = f"{head}:{tail}"
            except Exception:  # pragma: no cover — never let a helper import break the mapping
                pass
        return f"{parts[0]}:{parts[1]}:{rest}"
    return sanitized.replace("-", ":")


def _build_spiffe_id(agent_did: str, trust_domain: Optional[str] = None) -> str:
    """Build the SPIFFE ID for an agent.

    trust_domain defaults to the registry's own TRUST_DOMAIN env. Pass an
    override when registering an entry on behalf of a peer in a different
    trust domain (§pass32 Phase 6 trust-domain-aware proxy receiver).
    """
    sanitized = sanitize_did_for_spiffe(agent_did)
    td = trust_domain or TRUST_DOMAIN
    return f"spiffe://{td}/agent/{sanitized}"


def _build_parent_id(fingerprint: str | None = None, trust_domain: Optional[str] = None) -> str:
    """Build the parent ID for agent entries."""
    fp = fingerprint or _parent_fingerprint_for_self()
    td = trust_domain or TRUST_DOMAIN
    return f"spiffe://{td}/spire/agent/x509pop/{fp}"


def _build_selector(agent_did: str) -> str:
    """Build the Docker label selector for an agent."""
    sanitized = sanitize_did_for_spiffe(agent_did)
    return f"docker:label:com.theprotocol.agent-did:{sanitized}"


def local_container_exists_for_agent(agent_did: str) -> bool:
    """True when a container ON THIS HOST carries the agent's IRONHAND label.

    This is the strongest available evidence that the agent is co-located with
    our spire-agent and can therefore satisfy the `docker:label:` selector via
    the SPIFFE Workload API. Used by enable-mtls to decide whether an enrolling
    agent is on-box or on somebody else's infrastructure.

    Never raises: no docker.sock (operator registries) or a docker error both
    mean "cannot prove on-box", which the caller treats as one negative signal
    among several — not as proof of the opposite.
    """
    if not _LOCAL_SPIRE_AVAILABLE:
        return False
    sanitized = sanitize_did_for_spiffe(agent_did)
    try:
        client = _get_docker_client()
        found = client.containers.list(
            filters={"label": f"com.theprotocol.agent-did={sanitized}"},
            ignore_removed=True,
        )
        return len(found) > 0
    except Exception as e:  # docker unreachable, permissions, API drift
        logger.debug(f"[IRONHAND] container-label probe failed for {agent_did}: {e}")
        return False


def _der_b64_to_pem(b64_der: str, label: str) -> str:
    """Wrap a base64 DER blob (as `spire-server x509 mint -output json` emits)
    into PEM. The CLI returns unwrapped base64 of the DER bytes, so this is a
    pure re-encoding — no parsing, no crypto dependency.
    """
    body = "\n".join(b64_der[i:i + 64] for i in range(0, len(b64_der), 64))
    return f"-----BEGIN {label}-----\n{body}\n-----END {label}-----\n"


def _mint_local(
    agent_did: str,
    ttl_seconds: int,
    trust_domain: Optional[str] = None,
    dns_sans: list[str] | None = None,
) -> dict:
    """Mint an X509-SVID directly from the SPIRE CA via docker exec.

    `x509 mint` signs a SVID for any SPIFFE ID in our trust domain WITHOUT
    consulting registration entries — that is precisely why it works for an
    agent we cannot node-attest. Authorization is therefore entirely the
    caller's responsibility (enable-mtls has already proven agent identity,
    active status and the identity.mtls permission before reaching here).
    """
    spiffe_id = _build_spiffe_id(agent_did, trust_domain=trust_domain)
    container_name = _container_for_trust_domain(trust_domain)

    client = _get_docker_client()
    try:
        container = client.containers.get(container_name)
    except Exception as e:
        raise RuntimeError(f"Cannot find SPIRE server container '{container_name}': {e}")

    cmd = [
        SPIRE_BINARY, "x509", "mint",
        "-spiffeID", spiffe_id,
        "-ttl", f"{int(ttl_seconds)}s",
        "-output", "json",
    ]
    for dns in (dns_sans or []):
        cmd.extend(["-dns", dns])

    exit_code, output = container.exec_run(cmd, demux=True)
    stdout = (output[0] or b"").decode(errors="replace").strip()
    stderr = (output[1] or b"").decode(errors="replace").strip()
    if exit_code != 0:
        raise RuntimeError(f"SVID mint failed for {agent_did} (exit={exit_code}): {stderr[:200]}")
    return _mint_result(agent_did, spiffe_id, ttl_seconds, stdout)


def _mint_via_runner(
    agent_did: str,
    ttl_seconds: int,
    trust_domain: Optional[str] = None,
    dns_sans: list[str] | None = None,
) -> dict:
    """§F6 WP6.1: the same mint through the frame runner's spire_x509_mint (an /agent/ id of this frame only)."""
    _runner_own_frame(trust_domain)
    from agentvault_registry.services import spire_ops_client as _soc
    spiffe_id = _build_spiffe_id(agent_did)
    rc, stdout, stderr = _soc.x509_mint(spiffe_id=spiffe_id, ttl=int(ttl_seconds), dns=dns_sans or [])
    if rc != 0:
        raise RuntimeError(f"SVID mint through the frame runner failed for {agent_did} (exit={rc}): {stderr.strip()[:200]}")
    return _mint_result(agent_did, spiffe_id, ttl_seconds, stdout.strip())


def _mint_result(agent_did: str, spiffe_id: str, ttl_seconds: int, stdout: str) -> dict:
    """`spire-server x509 mint -output json` output -> the PEMs and the expiry the caller hands on."""
    # The CLI prints a JSON ARRAY (one element per minted SVID), not an object.
    # A dict-shaped parser silently breaks here, so pin the shape explicitly.
    try:
        parsed = json.loads(stdout)
        item = parsed[0] if isinstance(parsed, list) else parsed
        chain_b64 = item["x509_svid"]
        key_b64 = item["private_key"]
        roots_b64 = item.get("root_cas") or []
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unparseable x509 mint output for {agent_did}: {e}")

    if isinstance(chain_b64, str):
        chain_b64 = [chain_b64]

    svid_pem = "".join(_der_b64_to_pem(c, "CERTIFICATE") for c in chain_b64)
    key_pem = _der_b64_to_pem(key_b64, "PRIVATE KEY")
    bundle_pem = "".join(_der_b64_to_pem(r, "CERTIFICATE") for r in roots_b64)

    # Expiry comes from the CERTIFICATE, never from arithmetic on what we asked
    # for. SPIRE backdates notBefore and will shorten a SVID to fit the CA's own
    # remaining lifetime, and it emits a "capped" notice even when it granted the
    # full request — so trusting that log line reports a cap that did not happen.
    # The certificate is the only thing the client's TLS stack will actually obey.
    not_after = None
    capped = False
    try:
        from cryptography import x509 as _x509

        leaf = _x509.load_pem_x509_certificate(svid_pem.encode())
        na = getattr(leaf, "not_valid_after_utc", None) or leaf.not_valid_after
        if na.tzinfo is None:
            from datetime import timezone as _tz

            na = na.replace(tzinfo=_tz.utc)
        not_after = na.isoformat()
        from datetime import datetime as _dt, timezone as _tz2

        remaining = (na - _dt.now(_tz2.utc)).total_seconds()
        # 60s of slack absorbs backdating and clock skew; a real cap is minutes short.
        capped = remaining < (int(ttl_seconds) - 60)
    except Exception as e:  # never fail an issued credential over metadata
        logger.debug(f"[IRONHAND] could not read notAfter from minted SVID: {e}")

    logger.info(
        f"[IRONHAND] Minted inline SVID: {spiffe_id} ttl={ttl_seconds}s "
        f"expires={not_after} capped={capped} chain_len={len(chain_b64)}"
    )
    return {
        "spiffe_id": spiffe_id,
        "svid_pem": svid_pem,
        "key_pem": key_pem,
        "bundle_pem": bundle_pem,
        "ttl_seconds": int(ttl_seconds),
        "expires_at": not_after,
        "ttl_capped_by_ca": capped,
    }


def _mint_via_proxy(
    agent_did: str,
    ttl_seconds: int,
    trust_domain: Optional[str] = None,
    dns_sans: list[str] | None = None,
) -> dict:
    """Proxy an inline mint to the central registry (operator-side path).

    Mirrors _register_via_proxy: operator registries hold no docker.sock, so the
    frame that owns the SPIRE server does the signing.
    """
    base = _central_registry_url()
    if not base:
        raise RuntimeError(
            "IRONHAND inline SVID requires CENTRAL_REGISTRY_URL on operator registries."
        )
    body = {
        "agent_did": agent_did,
        "ttl_seconds": int(ttl_seconds),
        "trust_domain": trust_domain or TRUST_DOMAIN,
        "dns_sans": dns_sans or [],
    }
    try:
        resp = _proxy_post("mint-agent-proxy", body)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Central SVID mint rejected ({resp.status_code}): {resp.text[:200]}"
            )
        data = resp.json()
        if not data.get("svid_pem"):
            raise RuntimeError("Central returned no svid_pem")
        return data
    except httpx.RequestError as e:
        raise RuntimeError(f"Central registry unreachable for SVID mint proxy: {e}")


def mint_agent_svid(
    agent_did: str,
    ttl_seconds: int = 1800,
    trust_domain: Optional[str] = None,
    dns_sans: list[str] | None = None,
) -> dict:
    """Mint a short-lived X509-SVID for an agent and return it as PEM.

    For agents that CANNOT reach our SPIFFE Workload API — i.e. anything not
    running as a labelled container on this host. The returned material is the
    same shape the SDK's MtlsAgentClient already reads from disk
    (svid.pem / key.pem / bundle.pem).

    This hands a private key over the response body, so it is deliberately
    short-lived and gated by the caller. Revocation is by expiry: there is no
    way to recall a minted key, which is exactly why the TTL is minutes.

    Returns dict: spiffe_id, svid_pem, key_pem, bundle_pem, ttl_seconds,
    ttl_capped_by_ca.
    """
    mode = ironhand_mode()
    if mode == "local":
        return _mint_local(agent_did, ttl_seconds, trust_domain=trust_domain, dns_sans=dns_sans)
    if mode == "runner":
        return _mint_via_runner(agent_did, ttl_seconds, trust_domain=trust_domain, dns_sans=dns_sans)
    return _mint_via_proxy(agent_did, ttl_seconds, trust_domain=trust_domain, dns_sans=dns_sans)


def _register_local(
    agent_did: str,
    dns_sans: list[str] | None,
    fingerprint: str,
    trust_domain: Optional[str] = None,
) -> str:
    """Local SPIRE registration via docker exec. Requires /var/run/docker.sock.

    trust_domain selects which SPIRE container to target (via
    SPIRE_CONTAINERS_BY_TRUST_DOMAIN). None → local TRUST_DOMAIN's container.
    """
    spiffe_id = _build_spiffe_id(agent_did, trust_domain=trust_domain)
    parent_id = _build_parent_id(fingerprint, trust_domain=trust_domain)
    selector = _build_selector(agent_did)
    container_name = _container_for_trust_domain(trust_domain)

    logger.info(
        f"[IRONHAND] Registering SPIRE entry (local): did={agent_did}, "
        f"spiffeID={spiffe_id}, selector={selector}, container={container_name}"
    )

    client = _get_docker_client()
    try:
        container = client.containers.get(container_name)
    except Exception as e:
        raise RuntimeError(f"Cannot find SPIRE server container '{container_name}': {e}")

    cmd = [
        SPIRE_BINARY, "entry", "create",
        "-parentID", parent_id,
        "-spiffeID", spiffe_id,
        "-selector", selector,
        "-x509SVIDTTL", SVID_TTL,
    ]
    if dns_sans:
        for dns in dns_sans:
            cmd.extend(["-dns", dns])

    exit_code, output = container.exec_run(cmd, demux=True)
    stdout = (output[0] or b"").decode(errors="replace").strip()
    stderr = (output[1] or b"").decode(errors="replace").strip()

    if exit_code != 0:
        if "AlreadyExists" in stderr or "already exists" in stderr:
            logger.info(f"[IRONHAND] Entry already exists for {agent_did}: {spiffe_id}")
        else:
            raise RuntimeError(
                f"SPIRE entry creation failed for {agent_did} "
                f"(exit={exit_code}): {stderr}"
            )
    else:
        logger.info(f"[IRONHAND] Entry registered: {spiffe_id} — {stdout}")
    return spiffe_id


def _register_via_proxy(
    agent_did: str,
    dns_sans: list[str] | None,
    fingerprint: str,
    trust_domain: Optional[str] = None,
) -> str:
    """Proxy SPIRE registration to central registry (for operator-side)."""
    base = _central_registry_url()
    if not base:
        raise RuntimeError(
            "IRONHAND proxy mode requires CENTRAL_REGISTRY_URL. "
            "Set it in the operator's .env.operator."
        )
    body = {
        "agent_did": agent_did,
        "dns_sans": dns_sans or [],
        "parent_fingerprint": fingerprint,
        # §pass32 Phase 6 — tell the central which trust domain this entry
        # belongs to. None = central uses its default TRUST_DOMAIN env.
        "trust_domain": trust_domain or TRUST_DOMAIN,
    }
    logger.info(
        f"[IRONHAND] Registering SPIRE entry (proxy): did={agent_did}, "
        f"central={base}, parent_fp={fingerprint[:8]}..."
    )
    try:
        resp = _proxy_post("register-agent-proxy", body)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Central SPIRE registration rejected ({resp.status_code}): "
                f"{resp.text[:200]}"
            )
        data = resp.json()
        spiffe_id = data.get("spiffe_id", "")
        if not spiffe_id:
            raise RuntimeError(f"Central returned no spiffe_id: {data}")
        logger.info(f"[IRONHAND] Entry registered via proxy: {spiffe_id}")
        return spiffe_id
    except httpx.RequestError as e:
        raise RuntimeError(f"Central registry unreachable for SPIRE proxy: {e}")


def _register_via_runner(
    agent_did: str,
    dns_sans: list[str] | None,
    fingerprint: str,
    trust_domain: Optional[str] = None,
) -> str:
    """§F6 WP6.1: the entry through the frame runner's spire_entry_create (the runner checks the parent is a live node
    of this frame and the selector is the agent label)."""
    _runner_own_frame(trust_domain)
    from agentvault_registry.services import spire_ops_client as _soc
    spiffe_id = _build_spiffe_id(agent_did)
    parent_id = _build_parent_id(fingerprint)
    logger.info(f"[IRONHAND] Registering SPIRE entry (runner): did={agent_did}, spiffeID={spiffe_id}")
    rc, out, err = _soc.entry_create(spiffe_id=spiffe_id, parent_id=parent_id, selectors=[_build_selector(agent_did)],
                                     ttl=int(SVID_TTL), dns=dns_sans or [])
    if rc != 0:
        if "AlreadyExists" in err or "already exists" in err:
            logger.info(f"[IRONHAND] Entry already exists for {agent_did}: {spiffe_id}")
        else:
            raise RuntimeError(f"SPIRE entry creation through the frame runner failed for {agent_did} (exit={rc}): {err.strip()[:300]}")
    else:
        logger.info(f"[IRONHAND] Entry registered (runner): {spiffe_id}")
    return spiffe_id


def register_agent_spire_entry(
    agent_did: str,
    dns_sans: list[str] | None = None,
    fingerprint: str | None = None,
    trust_domain: Optional[str] = None,
) -> str:
    """Register a SPIRE workload entry for an agent.

    Uses local docker exec when /var/run/docker.sock is mounted; otherwise
    proxies to the central registry's ironhand admin proxy endpoint.

    Args:
        agent_did: Agent's DID (e.g., did:theprotocol:4c783710-...)
        dns_sans: Optional DNS SANs for the SVID
        fingerprint: Override parent SPIRE agent fingerprint. Defaults to
                     OPERATOR_SPIRE_AGENT_FINGERPRINT env (operator) or
                     MAINFRAME_AGENT_FINGERPRINT constant (central).
        trust_domain: Target trust domain (§pass32 Phase 6). None → use the
                     registry's own TRUST_DOMAIN env. When set to a different
                     domain (e.g., during cross-frame proxy delegation), the
                     entry is created on the SPIRE container mapped to that
                     domain via SPIRE_CONTAINERS_BY_TRUST_DOMAIN.

    Returns:
        The SPIFFE ID of the registered entry.

    Raises:
        RuntimeError: If SPIRE container not found, proxy unreachable, or
                      entry creation fails.
    """
    effective_fp = fingerprint or _parent_fingerprint_for_self()
    # findings row 198 — check the parent against the nodes that can actually attest, whatever
    # produced it (env override, auto-detect, or an explicit argument). A parent is a guess until
    # it is checked, and this is the ONE place every path passes through.
    _live = live_agent_fingerprints()
    if _live is not None and effective_fp not in _live:
        raise SpireParentUnresolved(
            f"The SPIRE agent node chosen to parent this identity ({effective_fp[:8]}…) is not "
            f"one of this frame's {len(_live)} live agent node(s), so the entry could never be "
            "attested and the workload would receive PERMISSION_DENIED forever. Nothing was "
            "created. Fix: set OPERATOR_SPIRE_AGENT_FINGERPRINT to this frame's spire-agent "
            "node, or register this registry's own /service/registry entry so it can be "
            "auto-detected. How mTLS identities are issued: "
            "https://docs.theprotocol.cloud/learn/security"
        )
    mode = ironhand_mode()
    if mode == "local":
        return _register_local(agent_did, dns_sans, effective_fp, trust_domain=trust_domain)
    if mode == "runner":
        return _register_via_runner(agent_did, dns_sans, effective_fp, trust_domain=trust_domain)
    return _register_via_proxy(agent_did, dns_sans, effective_fp, trust_domain=trust_domain)


def _delete_local(agent_did: str, trust_domain: Optional[str] = None) -> bool:
    """Local SPIRE deletion via docker exec."""
    spiffe_id = _build_spiffe_id(agent_did, trust_domain=trust_domain)
    container_name = _container_for_trust_domain(trust_domain)
    logger.info(f"[IRONHAND] Deleting SPIRE entry (local): {spiffe_id}, container={container_name}")

    client = _get_docker_client()
    try:
        container = client.containers.get(container_name)
    except Exception as e:
        raise RuntimeError(f"Cannot find SPIRE server container '{container_name}': {e}")

    show_cmd = [SPIRE_BINARY, "entry", "show", "-spiffeID", spiffe_id]
    exit_code, output = container.exec_run(show_cmd, demux=True)
    stdout = (output[0] or b"").decode(errors="replace")

    if exit_code != 0 or "Found 0 entries" in stdout or not stdout.strip():
        logger.warning(f"[IRONHAND] No entry found for {spiffe_id}")
        return False

    entry_ids = re.findall(r"Entry ID\s*:\s*(\S+)", stdout)
    if not entry_ids:
        logger.warning(f"[IRONHAND] Could not parse entry ID from output: {stdout[:200]}")
        return False

    deleted = False
    for entry_id in entry_ids:
        del_cmd = [SPIRE_BINARY, "entry", "delete", "-entryID", entry_id]
        exit_code, output = container.exec_run(del_cmd, demux=True)
        del_stdout = (output[0] or b"").decode(errors="replace").strip()
        if exit_code == 0:
            logger.info(f"[IRONHAND] Deleted entry {entry_id}: {del_stdout}")
            deleted = True
        else:
            del_stderr = (output[1] or b"").decode(errors="replace").strip()
            logger.error(f"[IRONHAND] Failed to delete entry {entry_id}: {del_stderr}")

    return deleted


def _delete_via_proxy(agent_did: str, trust_domain: Optional[str] = None) -> bool:
    """Proxy SPIRE deletion to central registry."""
    base = _central_registry_url()
    if not base:
        logger.warning(
            "[IRONHAND] delete proxy skipped: CENTRAL_REGISTRY_URL not set"
        )
        return False
    body = {"agent_did": agent_did, "trust_domain": trust_domain or TRUST_DOMAIN}
    logger.info(f"[IRONHAND] Deleting SPIRE entry (proxy): did={agent_did}, central={base}")
    try:
        resp = _proxy_post("delete-agent-proxy", body)
        if resp.status_code != 200:
            logger.error(
                f"[IRONHAND] Central proxy delete rejected ({resp.status_code}): "
                f"{resp.text[:200]}"
            )
            return False
        return bool(resp.json().get("deleted", False))
    except httpx.RequestError as e:
        logger.error(f"[IRONHAND] Central registry unreachable for delete proxy: {e}")
        return False


def _delete_via_runner(agent_did: str, trust_domain: Optional[str] = None) -> bool:
    """§F6 WP6.1: find the entry by SPIFFE ID and delete it by entry ID, both through the frame runner."""
    _runner_own_frame(trust_domain)
    from agentvault_registry.services import spire_ops_client as _soc
    spiffe_id = _build_spiffe_id(agent_did)
    rc, stdout = _spire_text(["entry", "show", "-spiffeID", spiffe_id])
    if rc != 0 or "Found 0 entries" in stdout or not stdout.strip():
        logger.warning(f"[IRONHAND] No entry found for {spiffe_id} (runner)")
        return False
    deleted = False
    for entry_id in re.findall(r"Entry ID\s*:\s*(\S+)", stdout):
        rc, _out, err = _soc.entry_delete(entry_id)
        if rc == 0:
            logger.info(f"[IRONHAND] Deleted entry {entry_id} (runner)")
            deleted = True
        else:
            logger.error(f"[IRONHAND] Failed to delete entry {entry_id} (runner): {err.strip()[:200]}")
    return deleted


def delete_agent_spire_entry(
    agent_did: str,
    trust_domain: Optional[str] = None,
) -> bool:
    """Delete the SPIRE entry for an agent.

    Finds the entry by SPIFFE ID, then deletes by entry ID.

    trust_domain selects the target SPIRE container via
    SPIRE_CONTAINERS_BY_TRUST_DOMAIN (§pass32 Phase 6). None → local
    TRUST_DOMAIN's container.

    Returns True if deleted, False if not found or proxy unavailable.
    """
    mode = ironhand_mode()
    if mode == "local":
        return _delete_local(agent_did, trust_domain=trust_domain)
    if mode == "runner":
        return _delete_via_runner(agent_did, trust_domain=trust_domain)
    return _delete_via_proxy(agent_did, trust_domain=trust_domain)


def check_agent_spire_entry(agent_did: str) -> Optional[str]:
    """Check if a SPIRE entry exists for the agent.

    Returns the entry ID if found, None otherwise. On operator-side (no local
    docker.sock), returns None unconditionally — enable_mtls's drift-detection
    path handles "not found" by conservative re-register (idempotent via the
    AlreadyExists branch of _register_local). Avoids one unnecessary proxy hop
    per enrollment.
    """
    if ironhand_mode() == "proxy":
        return None

    spiffe_id = _build_spiffe_id(agent_did)
    try:
        exit_code, stdout = _spire_text(["entry", "show", "-spiffeID", spiffe_id])
    except Exception:  # noqa: BLE001 — unknown reads as "not found": the caller re-registers idempotently
        return None

    if exit_code != 0 or "Found 0 entries" in stdout:
        return None

    entry_ids = re.findall(r"Entry ID\s*:\s*(\S+)", stdout)
    return entry_ids[0] if entry_ids else None


def get_spire_entry_count() -> int:
    """Get the total number of SPIRE entries (for benchmarking).

    Returns -1 on operator-side (no local SPIRE access) — callers already
    handle -1 as unavailable.
    """
    if ironhand_mode() == "proxy":
        return -1
    try:
        exit_code, stdout = _spire_text(["entry", "count"])
    except Exception:  # noqa: BLE001
        return -1

    match = re.search(r"(\d+)", stdout)
    return int(match.group(1)) if match else -1
