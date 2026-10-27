"""FrameTrustManager — programmatic SPIRE bundle exchange for sovereign frames.

Wraps the existing `spire-server` CLI (reached via `docker exec`) so the frame
federation handshake can add/remove peer trust bundles at runtime WITHOUT a
SPIRE server restart. The pattern mirrors `services/diagnostics/actions.py:
spire_bundle_refresh` (which manually injects Frame-B's bundle into Frame-A
today) — we lift that pattern into a reusable service.

Why a dedicated class (not inline in the router):
  - SPIRE CLI shelling has known failure modes (container not running, CLI
    missing, bundle format mismatch, network unreachable). Centralizing the
    try/except surface keeps the router readable.
  - Testable — the probe + subprocess can be mocked.
  - Environment-driven — SPIRE_CONTAINER + SPIRE_TRUST_DOMAIN env vars, matching
    IRONHAND (agent_spire.py) and cloud_provisioner.py conventions.

Canonical paths:
  - SPIFFE bundle endpoint: https://<trust_domain>:<port>/.well-known/spiffe/bundle
    Returns a JWK set (application/json). The running spire-server's CLI
    `bundle set -format spiffe` accepts this format directly. So the conversion
    step just hands the raw JSON payload to the CLI — no pre-parsing needed.
  - CLI: /opt/spire/bin/spire-server inside the SPIRE container.
"""
from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import logging
import os
import re
import socket
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)


# SPIRE federation refresh cadence: default ca_ttl=168h (7d) with refresh-hint
# defaulting to half the TTL → 84h between refreshes. A bundle that hasn't
# been re-imported in >120h (5d) is overdue and federation is silently broken.
# This is the threshold §pass53 root-caused — a 4d drift went unnoticed
# because the existing drift detector only checks bundle presence, not age.
BUNDLE_AGE_OVERDUE_SECONDS = 120 * 3600   # 5d (warn)
BUNDLE_AGE_CRITICAL_SECONDS = 144 * 3600  # 6d (alert — 24h before expiry)



# ---------------------------------------------------------------------------
# §FINDINGS-A4 3d (2026-09-27, his "fix 1-4 approved"): an outbound-request guard for the bundle dials.
# `POST /federation/frame-invitations` is PUBLIC and dials the `bundle_endpoint_url` a caller names; it followed redirects
# (the https check covered only the first URL) and echoed the probe's error back, a status oracle from inside the
# registry's network. An anonymous caller may now reach only PUBLIC https hosts, on every hop, and gets a generic refusal;
# a federation admin may name an internal host (same-host frames federate over the compose network: the standup's
# federate step sends the approver's token). At approve time a PUBLIC bundle URL is never followed inward.
# Residual, named: a name can resolve differently between this check and the dial (DNS rebinding); the refusal carries no
# oracle and the route is rate-limited, which is what bounds it.
# ---------------------------------------------------------------------------
_BUNDLE_MAX_REDIRECTS = 3


def _address_is_internal(addr: str) -> bool:
    """True for any address that is not globally routable (loopback, private, link-local, shared/CGNAT, reserved,
    unspecified, documentation) and for multicast; an IPv4-mapped IPv6 address is judged as its IPv4 address."""
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool((not ip.is_global) or ip.is_multicast or ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_unspecified)


async def _resolve(host: str, port: int) -> List[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


async def _host_is_internal(host: str, port: int) -> Tuple[bool, str]:
    """(internal, why) for a literal address or EVERY address a name resolves to; a name that does not resolve counts as
    internal (refused: nothing can be said about where it leads)."""
    literal = host.strip("[]")
    try:
        ipaddress.ip_address(literal.split("%", 1)[0])
        addrs = [literal]
    except ValueError:
        try:
            addrs = await _resolve(host, port)
        except Exception as exc:  # noqa: BLE001 — named in the refusal
            return True, f"the bundle host does not resolve ({type(exc).__name__})"
    if not addrs or any(_address_is_internal(a) for a in addrs):
        return True, "the bundle host is (or resolves to) an internal address"
    return False, ""


def _bundle_client(timeout: float) -> httpx.AsyncClient:
    """The one place the bundle dials build their client (tests substitute a transport). verify=False because remote
    frames may use self-signed certs during bootstrap (the SPIRE bundle, not the TLS certificate, is the trust anchor);
    redirects are followed by hand, one checked hop at a time."""
    return httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=False)


async def _dial_checked(client: httpx.AsyncClient, method: str, url: str, allow_internal: bool, headers=None):
    """(response, refusal): every hop https, and public unless allow_internal; at most _BUNDLE_MAX_REDIRECTS redirects."""
    for _hop in range(_BUNDLE_MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            return None, "every hop must be an https URL"
        if not allow_internal:
            internal, why = await _host_is_internal(parts.hostname, parts.port or 443)
            if internal:
                return None, why
        r = await client.request(method, url, headers=headers)
        location = r.headers.get("location")
        if r.is_redirect and location:
            url = urljoin(url, location)
            continue
        return r, None
    return None, f"more than {_BUNDLE_MAX_REDIRECTS} redirects"

@dataclass
class BundleFreshness:
    """Snapshot of a federated bundle's cert lifetime + computed age fields.

    not_before / not_after are extracted from the leaf x509 cert in the bundle
    PEM. age_seconds is wall-clock seconds since not_before. expires_in_seconds
    is signed wall-clock seconds until not_after (negative = already expired).
    """
    trust_domain: str
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    age_seconds: Optional[float] = None
    expires_in_seconds: Optional[float] = None
    refresh_overdue: bool = False
    refresh_critical: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "trust_domain": self.trust_domain,
            "not_before": self.not_before.isoformat() if self.not_before else None,
            "not_after": self.not_after.isoformat() if self.not_after else None,
            "age_seconds": self.age_seconds,
            "expires_in_seconds": self.expires_in_seconds,
            "refresh_overdue": self.refresh_overdue,
            "refresh_critical": self.refresh_critical,
            "error": self.error,
        }


SPIRE_CONTAINER_DEFAULT = "agentvault-spire-server"
SPIRE_TRUST_DOMAIN_DEFAULT = "agentvault.com"
SPIRE_BIN_PATH = "/opt/spire/bin/spire-server"
DOCKER_EXEC_TIMEOUT_SECONDS = 10
HTTP_PROBE_TIMEOUT_SECONDS = 6.0

# SPIFFE standard well-known path (RFC). Tried as a fallback if the given
# bundle_endpoint_url doesn't return a bundle itself.
SPIFFE_WELL_KNOWN_PATH = "/.well-known/spiffe/bundle"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docker_client():
    """Return a docker-py client bound to the mounted socket.

    The registry container has /var/run/docker.sock mounted (confirmed at
    build time via the docker-compose volume spec) and the `docker>=7.0.0`
    Python package installed. We do NOT install the docker CLI binary; all
    container-level admin goes through docker-py.
    """
    import docker  # lazy import to avoid startup cost when unused
    return docker.DockerClient(base_url="unix://var/run/docker.sock")


async def _run_docker_exec(
    container: str,
    cmd: List[str],
    *,
    timeout: int = DOCKER_EXEC_TIMEOUT_SECONDS,
    stdin_data: Optional[bytes] = None,
) -> Tuple[int, str, str]:
    """Execute `cmd` inside <container> via the docker-py SDK.

    Wraps a blocking SDK call with asyncio.to_thread. stdin_data, when
    provided, is written to the exec process via a shell redirection (we
    rewrite the command to `sh -c "echo <payload> | <original>"` — docker-py's
    exec_run doesn't expose stdin attachment on the one-shot API, so this is
    the pragmatic alternative). For our case (bundle JSON/PEM input), we
    instead stage the payload to a tempfile in the container first, then run
    `spire-server bundle set -path <tempfile>` — same two-step pattern as
    the original shell implementation.
    """
    def _blocking() -> Tuple[int, str, str]:
        try:
            client = _docker_client()
            cnt = client.containers.get(container)
            if stdin_data is not None:
                # Two-step: write stdin_data to a scratch file via `tee`, then
                # run the target command with that file. Mirrors the prior
                # `cat > /tmp/x.pem` + `bundle set -path /tmp/x.pem` pattern.
                # Callers of _run_docker_exec with stdin_data are expected to
                # use the higher-level add_peer_bundle helper which stages its
                # own files, so this path is rarely hit; keep it defensively.
                import base64, shlex
                b64 = base64.b64encode(stdin_data).decode("ascii")
                inner = " ".join(shlex.quote(a) for a in cmd)
                wrapped = [
                    "sh", "-c",
                    f"echo {b64} | base64 -d | {inner}",
                ]
                exec_result = cnt.exec_run(wrapped, demux=True, tty=False)
            else:
                exec_result = cnt.exec_run(cmd, demux=True, tty=False)
            rc = exec_result.exit_code or 0
            stdout_b, stderr_b = exec_result.output or (b"", b"")
            stdout = (stdout_b or b"").decode("utf-8", errors="replace")
            stderr = (stderr_b or b"").decode("utf-8", errors="replace")
            return rc, stdout, stderr
        except Exception as exc:
            # docker.errors.NotFound / APIError / SocketError / etc.
            return 1, "", f"docker SDK exec failed: {type(exc).__name__}: {exc}"

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_blocking),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return 124, "", f"docker exec timed out after {timeout}s"


async def _put_file_into_spire_container(
    container_name: str, dest_path: str, content: bytes
) -> Tuple[bool, str]:
    """Stage `content` at `dest_path` inside <container_name> via Docker SDK
    `put_archive` (tarfile streaming, daemon-side).

    This is the only file-staging path that works against distroless SPIRE
    images (ghcr.io/spiffe/spire-server:1.10+). The previous `sh -c "cat > tmp"`
    pattern fails because the container has no shell. put_archive is handled
    entirely by the Docker daemon — no in-container commands required.

    Mirrors the proven pattern in
    the retired dual-frame lifecycle test's _put_file_to_container.
    """
    def _blocking() -> Tuple[bool, str]:
        try:
            client = _docker_client()
            cnt = client.containers.get(container_name)
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo(name=os.path.basename(dest_path))
                info.size = len(content)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(content))
            buf.seek(0)
            target_dir = os.path.dirname(dest_path) or "/"
            ok = cnt.put_archive(target_dir, buf.read())
            return bool(ok), "" if ok else "put_archive returned False"
        except Exception as exc:
            return False, f"put_archive exception: {type(exc).__name__}: {exc}"

    return await asyncio.to_thread(_blocking)


def _normalize_trust_domain(td: str) -> str:
    """Strip any `spiffe://` prefix + trailing slash; lowercase.

    spire-server CLI expects `-id spiffe://<trust_domain>` — we keep the raw
    trust_domain (no scheme) in the DB and prefix at call time.
    """
    td = td.strip().lower()
    if td.startswith("spiffe://"):
        td = td[len("spiffe://"):]
    return td.rstrip("/")


# ── §MONEY-R52 (2026-09-04, his word "r52 approved too") — the SPIRE federation RELATIONSHIP ──────
# Federation has three layers: the bundle IMPORT (add_peer_bundle), the workload entries'
# -federatesWith (§FRAMEFED), and the RELATIONSHIP — `spire-server federation create`, which is what
# makes SPIRE re-fetch the peer's bundle from the peer's bundle endpoint before it expires. Nothing
# in the product created it: an imported bundle sat still until the drift monitor called it stale
# (HANDOVER_2026-09-03_SANDBOX_STANDUP §7.1 finding 2). The rules here:
#   · the SPIRE endpoint is the peer's SPIRE SERVER (https_spiffe, presenting spiffe://<td>/spire/server),
#     derived from the bundle-endpoint URL the invitation carries: scheme + host[:port], never the
#     https_web well-known path or a trailing slash (three stored shapes measured 2026-09-04:
#     `https://frame-b…:8443/.well-known/spiffe/bundle`, `https://spire-c…`, `https://sbx-beta-spire-server:8443/`);
#   · an EXISTING relationship is never touched — prod's were hand-pointed at docker-internal names
#     (`https://spire-server-b:8443`) that an invitation URL would clobber; `already` is reported with
#     what it holds, and changing it stays a hand step (`federation update`);
#   · FRAME_SPIRE_FEDERATION_OVERRIDES (JSON, td -> {url, profile, endpoint_spiffe_id}) wins for a
#     deployment whose SPIRE endpoint is not where the invitation says.
FEDERATION_PROFILE_DEFAULT = "https_spiffe"
FEDERATION_OVERRIDES_ENV = "FRAME_SPIRE_FEDERATION_OVERRIDES"


def parse_federation_list(text: str) -> dict:
    """`spire-server federation list|show` text → {trust_domain: {url, profile, endpoint_spiffe_id}}."""
    out: dict = {}
    cur: Optional[str] = None
    for raw in (text or "").splitlines():
        key, sep, val = raw.partition(":")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if key == "Trust domain":
            cur = _normalize_trust_domain(val)
            out[cur] = {"url": "", "profile": "", "endpoint_spiffe_id": ""}
        elif cur and key == "Bundle endpoint URL":
            out[cur]["url"] = val
        elif cur and key == "Bundle endpoint profile":
            out[cur]["profile"] = val
        elif cur and key == "Endpoint SPIFFE ID":
            out[cur]["endpoint_spiffe_id"] = val
    return out


def spire_bundle_endpoint_from_url(url: str) -> str:
    """The SPIRE server endpoint a relationship dials: scheme + host[:port] of the invitation's
    bundle-endpoint URL. The https_web well-known path and any trailing slash are dropped —
    SPIRE 1.10+ serves its bundle at `/` and the https_spiffe profile expects the server itself."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    scheme, _, rest = u.partition("://")
    host = rest.split("/", 1)[0].strip()
    return f"{scheme}://{host}" if host else ""


def federation_overrides(raw: Optional[str] = None) -> dict:
    """FRAME_SPIRE_FEDERATION_OVERRIDES parsed; malformed JSON is an empty map (logged), never a crash."""
    src = raw if raw is not None else os.getenv(FEDERATION_OVERRIDES_ENV, "")
    if not (src or "").strip():
        return {}
    try:
        data = json.loads(src)
        return {_normalize_trust_domain(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FRAMEFED] %s is not valid JSON (%s) — ignored", FEDERATION_OVERRIDES_ENV, exc)
        return {}


def federation_relationship_argv(action: str, trust_domain: str, url: str, profile: str,
                                 endpoint_spiffe_id: str) -> List[str]:
    assert action in ("create", "update"), action
    return [SPIRE_BIN_PATH, "federation", action,
            "-trustDomain", trust_domain,
            "-bundleEndpointURL", url,
            "-bundleEndpointProfile", profile,
            "-endpointSpiffeID", endpoint_spiffe_id]


def plan_federation_relationship(existing: dict, trust_domain: str, bundle_endpoint_url: str,
                                 overrides: Optional[dict] = None) -> Tuple[str, Optional[List[str]], dict]:
    """Decide what to do for one peer. Returns (decision, argv, detail):
    `already` (a relationship exists — left alone, its current values in detail),
    `create` (argv to run), or `skip` (no endpoint could be derived)."""
    td = _normalize_trust_domain(trust_domain)
    ov = (overrides or {}).get(td, {})
    url = (ov.get("url") or spire_bundle_endpoint_from_url(bundle_endpoint_url)).rstrip("/")
    profile = ov.get("profile") or FEDERATION_PROFILE_DEFAULT
    spiffe_id = ov.get("endpoint_spiffe_id") or f"spiffe://{td}/spire/server"
    if td in existing:
        return "already", None, {"trust_domain": td, **existing[td], "overridden": bool(ov)}
    if not url:
        return "skip", None, {"trust_domain": td, "reason": "no bundle endpoint URL to derive from"}
    argv = federation_relationship_argv("create", td, url, profile, spiffe_id)
    return "create", argv, {"trust_domain": td, "url": url, "profile": profile,
                            "endpoint_spiffe_id": spiffe_id, "overridden": bool(ov)}


async def ensure_federation_relationship(run, spire_container: str, trust_domain: str,
                                         bundle_endpoint_url: str, overrides: Optional[dict] = None) -> Tuple[bool, dict]:
    """Create the SPIRE federation relationship for `trust_domain` on `spire_container` if it does
    not exist. `run(container, cmd) -> (rc, out, err)` is awaitable (the docker exec transport).
    Returns (ok, detail); a failed create is reported, never raised."""
    rc, out, err = await run(spire_container, [SPIRE_BIN_PATH, "federation", "list"])
    if rc != 0:
        return False, {"trust_domain": _normalize_trust_domain(trust_domain), "decision": "error",
                       "error": f"federation list rc={rc}: {(err or out).strip()[:200]}"}
    decision, argv, detail = plan_federation_relationship(parse_federation_list(out), trust_domain,
                                                          bundle_endpoint_url, overrides)
    detail["decision"] = decision
    if decision != "create":
        return decision == "already", detail
    rc, out, err = await run(spire_container, argv)
    if rc != 0:
        detail["decision"] = "failed"
        detail["error"] = f"federation create rc={rc}: {(err or out).strip()[:200]}"
        logger.warning("[FRAMEFED] federation create for %s FAILED on %s: %s", detail["trust_domain"],
                       spire_container, detail["error"])
        return False, detail
    logger.info("[FRAMEFED] federation relationship created on %s: %s", spire_container, detail)
    return True, detail


# ---------------------------------------------------------------------------
# FrameTrustManager
# ---------------------------------------------------------------------------

class FrameTrustResult:
    """Structured result from a SPIRE operation. Used by the router to surface
    error detail without leaking raw CLI output to end users."""
    __slots__ = ("ok", "message", "transcript")

    def __init__(self, ok: bool, message: str, transcript: str = ""):
        self.ok = ok
        self.message = message
        self.transcript = transcript

    def __bool__(self) -> bool:
        return self.ok


class FrameTrustManager:
    def __init__(
        self,
        spire_container: Optional[str] = None,
        local_trust_domain: Optional[str] = None,
    ):
        self.spire_container = spire_container or os.getenv(
            "SPIRE_CONTAINER", SPIRE_CONTAINER_DEFAULT
        )
        self.local_trust_domain = _normalize_trust_domain(
            local_trust_domain or os.getenv("SPIRE_TRUST_DOMAIN", SPIRE_TRUST_DOMAIN_DEFAULT)
        )

    async def _spire(self, argv: List[str]) -> Tuple[int, str, str]:
        """One spire-server call on this frame's SPIRE server, by the route FRAME_TRUST_SPIRE_VIA names: the docker
        socket ("local", today's) or the frame runner's identity ops ("runner", §F6 WP6.1). The runner route fails
        closed: a refusal comes back as rc 1 with the runner's own sentence, and nothing falls back to the socket."""
        from agentvault_registry.services import spire_ops_client as _soc
        try:
            if _soc.trust_via() == "runner":
                return await _soc.arun_argv(argv)
        except _soc.SpireOpsUnavailable as exc:
            return 1, "", f"through the frame runner: {exc}"
        return await _run_docker_exec(self.spire_container, argv, timeout=DOCKER_EXEC_TIMEOUT_SECONDS)

    async def read_own_bundle(self, fmt: str = "spiffe") -> Tuple[Optional[str], str]:
        """(this frame's own trust bundle, "") or (None, why), by the same route as every other call here. The approve
        and finalize-retry legs send it to the peer; it was read through `docker exec` alone until the §F6 WP6.1 proof,
        so a socket-less approver would have answered its own callback with "Local bundle unreadable"."""
        rc, out, err = await self._spire([SPIRE_BIN_PATH, "bundle", "show", "-format", fmt])
        if rc != 0 or not out.strip():
            return None, f"rc={rc} stderr={err.strip()[:200]}"
        return out, ""

    # ------------------------------------------------------------------
    # Remote bundle fetching
    # ------------------------------------------------------------------

    async def probe_bundle_endpoint(
        self, url: str, timeout: float = HTTP_PROBE_TIMEOUT_SECONDS, allow_internal: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """Best-effort HEAD (falling back to GET) to confirm the URL is reachable.

        Does not validate the bundle format — just that there's something live.
        verify=False because remote frames may be using self-signed certs during
        bootstrap (SPIRE itself is the trust anchor, not the TLS cert).
        """
        if not url or not url.startswith("https://"):
            return False, "Bundle endpoint URL must start with https://"
        try:
            async with _bundle_client(timeout) as client:
                try:
                    r, refusal = await _dial_checked(client, "HEAD", url, allow_internal)
                    if refusal:
                        return False, refusal
                    if 200 <= r.status_code < 500:
                        return True, None
                except Exception:
                    pass
                r, refusal = await _dial_checked(client, "GET", url, allow_internal)
                if refusal:
                    return False, refusal
                if 200 <= r.status_code < 400:
                    return True, None
                return False, f"HTTP {r.status_code} from {url}"
        except httpx.TimeoutException:
            return False, f"Timed out connecting to {url}"
        except Exception as exc:
            return False, f"Connection failed: {exc}"

    async def fetch_remote_bundle(
        self, bundle_endpoint_url: str, trust_domain: str, timeout: float = HTTP_PROBE_TIMEOUT_SECONDS
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetch the remote frame's SPIRE trust bundle.

        Tries the URL as-given first (assumes caller knows the path); falls back
        to the standard `/.well-known/spiffe/bundle` path on the root if the
        given URL doesn't carry a path.

        Returns (bundle_body, content_type, error). On success, error is None
        and bundle_body is the raw response text (JWK set JSON). On failure,
        bundle_body is None and error describes the failure.
        """
        if not bundle_endpoint_url or not bundle_endpoint_url.startswith("https://"):
            return None, None, "Bundle endpoint URL must start with https://"

        candidates = [bundle_endpoint_url]
        # If caller gave just the base (no path or only trailing /), also try well-known
        if (
            "/.well-known/spiffe/bundle" not in bundle_endpoint_url
            and bundle_endpoint_url.rstrip("/").count("/") == 2  # "https://host:port"
        ):
            candidates.append(bundle_endpoint_url.rstrip("/") + SPIFFE_WELL_KNOWN_PATH)

        last_error = None
        # §FINDINGS-A4 3d: an internal ORIGINAL (a federation admin named it, or an admin reviewed it before this rule)
        # may stay internal; a public one is never followed into an internal address.
        _orig = urlsplit(bundle_endpoint_url)
        allow_internal, _ = await _host_is_internal(_orig.hostname or "", _orig.port or 443)
        try:
            async with _bundle_client(timeout) as client:
                for url in candidates:
                    try:
                        r, refusal = await _dial_checked(client, "GET", url, allow_internal,
                                                         headers={"Accept": "application/json"})
                        if refusal:
                            last_error = f"{refusal} ({url})"
                            continue
                        if 200 <= r.status_code < 300:
                            body = r.text
                            ct = r.headers.get("content-type", "application/json")
                            if len(body) < 16:
                                last_error = f"Bundle body from {url} is too small ({len(body)} bytes)"
                                continue
                            return body, ct, None
                        last_error = f"HTTP {r.status_code} from {url}"
                    except Exception as exc:
                        last_error = f"{type(exc).__name__} on {url}: {exc}"
                        continue
        except Exception as exc:
            return None, None, f"Bundle fetch outer failure: {exc}"

        return None, None, last_error or "Bundle fetch exhausted candidates"

    # ------------------------------------------------------------------
    # SPIRE CLI wrappers
    # ------------------------------------------------------------------

    async def add_peer_bundle(
        self, trust_domain: str, bundle_body: str, format_hint: str = "spiffe"
    ) -> FrameTrustResult:
        """Import a peer frame's trust bundle into our SPIRE server.

        `format_hint` is passed to `spire-server bundle set -format <...>`.
        Defaults to "spiffe" (JWK set) since that's what remote `/.well-known/
        spiffe/bundle` endpoints return. Pass "pem" for raw PEM input.

        Idempotent — `bundle set` overwrites any existing entry for the same
        trust domain.
        """
        td = _normalize_trust_domain(trust_domain)
        if not td:
            return FrameTrustResult(False, "Empty trust domain")
        if td == self.local_trust_domain:
            return FrameTrustResult(False, f"Refusing to add our own trust domain ({td}) as a peer")
        if format_hint not in ("spiffe", "pem"):
            return FrameTrustResult(False, f"Unsupported format: {format_hint}")

        from agentvault_registry.services import spire_ops_client as _soc
        try:
            _via = _soc.trust_via()
        except _soc.SpireOpsUnavailable as exc:
            return FrameTrustResult(False, str(exc))
        if _via == "runner":
            # §F6 WP6.1: the runner reads the bundle on the CLI's stdin (spire_bundle_set), so nothing is staged here
            try:
                rc, out, err = await asyncio.to_thread(_soc.bundle_set, td, bundle_body, format_hint)
            except _soc.SpireOpsUnavailable as exc:
                return FrameTrustResult(False, f"spire-server bundle set through the frame runner failed: {exc}")
            line = f"$ runner spire_bundle_set spiffe://{td} format={format_hint} (rc={rc}) stderr={err.strip()[:200]}"
            if rc != 0:
                return FrameTrustResult(False, f"spire-server bundle set failed: {(err or out).strip()[:300]}", line)
            return FrameTrustResult(True, f"Bundle imported for spiffe://{td} (through the frame runner)", line)

        transcript: List[str] = []
        safe_td = re.sub(r"[^a-zA-Z0-9.-]", "_", td)
        tmp_path = f"/tmp/frame_bundle_{safe_td}.{format_hint}"

        # 1. Stage the bundle body inside the SPIRE container via put_archive.
        #    Distroless SPIRE images (1.10+) have no shell, so `sh -c "cat > tmp"`
        #    fails. put_archive is daemon-side tarfile streaming — works without
        #    any in-container commands.
        ok, stage_err = await _put_file_into_spire_container(
            self.spire_container, tmp_path, bundle_body.encode("utf-8"),
        )
        transcript.append(f"$ put_archive {tmp_path} (ok={ok}) detail={stage_err[:200]}")
        if not ok:
            return FrameTrustResult(False, f"Failed to stage bundle file: {stage_err[:200]}", "\n".join(transcript))

        # 2. spire-server bundle set -id spiffe://<td> -path <file> -format <spiffe|pem>
        rc, out, err = await _run_docker_exec(
            self.spire_container,
            [
                SPIRE_BIN_PATH, "bundle", "set",
                "-id", f"spiffe://{td}",
                "-path", tmp_path,
                "-format", format_hint,
            ],
            timeout=DOCKER_EXEC_TIMEOUT_SECONDS,
        )
        transcript.append(f"$ bundle set -id spiffe://{td} (rc={rc}) stdout={out.strip()[:200]} stderr={err.strip()[:200]}")
        if rc != 0:
            return FrameTrustResult(
                False,
                f"spire-server bundle set failed: {(err or out).strip()[:300]}",
                "\n".join(transcript),
            )

        # 3. Cleanup skipped (distroless container has no `rm`). The tempfile
        #    lives in the container's tmpfs and disappears on next restart.
        transcript.append(f"$ cleanup {tmp_path} skipped (distroless)")

        return FrameTrustResult(True, f"Bundle imported for spiffe://{td}", "\n".join(transcript))

    async def remove_peer_bundle(self, trust_domain: str) -> FrameTrustResult:
        """Delete a peer trust bundle. No-op if not present."""
        td = _normalize_trust_domain(trust_domain)
        if not td or td == self.local_trust_domain:
            return FrameTrustResult(False, f"Invalid trust domain for remove: {td!r}")

        # -mode dissociate: the default (restrict) refuses to delete a bundle that registration entries federate with,
        # which is EVERY bundle an approve ever wired (the approve federates the frame's workload entries with the peer),
        # so a revoke left the peer's root in SPIRE and in every proxy's bundle and "revoke bites mTLS" was a sentence
        # (measured 2026-09-18 on sbx-alpha: `cannot delete bundle; federated with 7 registration entries`). dissociate
        # strips the FederatesWith from those entries and deletes the bundle; a later approve federates them again.
        rc, out, err = await self._spire([SPIRE_BIN_PATH, "bundle", "delete", "-mode", "dissociate", "-id", f"spiffe://{td}"])
        transcript = f"$ bundle delete -mode dissociate -id spiffe://{td} (rc={rc}) out={out.strip()[:200]} err={err.strip()[:200]}"
        # rc=1 with "not found" in stderr is treated as success (idempotent).
        if rc != 0 and "not found" not in (err + out).lower():
            return FrameTrustResult(False, f"Bundle delete failed: {(err or out).strip()[:300]}", transcript)
        return FrameTrustResult(True, f"Bundle removed for spiffe://{td}", transcript)

    async def delete_federation_relationship(self, trust_domain: str) -> FrameTrustResult:
        """§F6 WP6.2 — end the SPIRE federation RELATIONSHIP with a peer (`federation delete`). A revoke that deleted only
        the bundle left the relationship on both sides (measured by the WP6.1 proof on the throwaway f6proof and
        sbx-beta: `federation list` still named each other after the revoke, and the teardown had to delete sbx-beta's
        host-side), and while a relationship stands the server's refresher keeps asking the peer's bundle endpoint for a
        bundle it may import again. No-op if absent: SPIRE's "federation relationship not found" is success."""
        td = _normalize_trust_domain(trust_domain)
        if not td or td == self.local_trust_domain:
            return FrameTrustResult(False, f"Invalid trust domain for relationship delete: {td!r}")
        rc, out, err = await self._spire([SPIRE_BIN_PATH, "federation", "delete", "-id", f"spiffe://{td}"])
        transcript = f"$ federation delete -id spiffe://{td} (rc={rc}) out={out.strip()[:200]} err={err.strip()[:200]}"
        # SPIRE's own words only: a runner refusal or a missing socket must never read as "already gone"
        if rc != 0 and "federation relationship not found" not in (err + out).lower():
            return FrameTrustResult(False, f"Federation relationship delete failed: {(err or out).strip()[:300]}", transcript)
        return FrameTrustResult(True, f"Federation relationship removed for spiffe://{td}", transcript)

    async def list_federated_trust_domains(self) -> Tuple[List[str], Optional[str]]:
        """Call `spire-server bundle list` and parse the federated trust domain IDs.

        Returns (domains, error). Domains do NOT include our own trust domain.
        On CLI failure, returns ([], error_message).

        SPIRE's `bundle list` output is the canonical SPIFFE PEM format:
        each entry has a `Trust domain: <td>` line followed by the PEM bundle.
        (Some newer SPIRE versions support `-format pem|spiffe` but not `json` —
        plain-text parsing is the portable path.)
        """
        rc, out, err = await self._spire([SPIRE_BIN_PATH, "bundle", "list"])
        if rc != 0:
            return [], f"bundle list failed: {(err or out).strip()[:300]}"

        # SPIRE `bundle list` output uses asterisk-delimited headers:
        #   ****************************************
        #   * <trust_domain>
        #   ****************************************
        #   -----BEGIN CERTIFICATE-----
        #   ...
        # Parse the `* <td>` lines (between the asterisk banners).
        # Also supports the older `Trust domain: <td>` format for robustness.
        domains: List[str] = []
        for line in (out or "").splitlines():
            stripped = line.strip()
            # Asterisk-header format: "* <trust_domain>" (no colons, no CERT content)
            if stripped.startswith("* ") and "-----" not in stripped:
                candidate = stripped[2:].strip()
                # skip the banner lines themselves (all asterisks)
                if candidate and not set(candidate) == {"*"}:
                    if candidate.startswith("spiffe://"):
                        candidate = candidate[len("spiffe://"):]
                    td = _normalize_trust_domain(candidate)
                    if td and td != self.local_trust_domain:
                        domains.append(td)
                    continue
            # Legacy "Trust domain: X" format
            m = re.match(
                r"^\s*Trust domain\s*:\s*(?:spiffe://)?([a-zA-Z0-9.\-]+)",
                line,
                re.IGNORECASE,
            )
            if m:
                td = _normalize_trust_domain(m.group(1))
                if td and td != self.local_trust_domain:
                    domains.append(td)

        return sorted(set(domains)), None

    async def list_federation_relationships(self) -> Tuple[List[str], Optional[str]]:
        """Call `spire-server federation list` and parse the federated trust domain IDs.

        Returns (domains, error). Unlike `list_federated_trust_domains()` — which
        reads the local *trust bundles* imported into SPIRE — this reads the
        configured *federation relationships*. The difference matters: a bundle
        can be stuck in place without an active relationship (e.g., after a
        `spire-server federation delete`), and a relationship can exist without
        a bundle (e.g., first boot before the `https_spiffe` endpoint returns).

        Both signals together = SPIRE is actively federating this trust domain.
        The drift rule uses this for `frame_bundle_stale` detection
        (`background_tasks/license_drift_monitor.py:detect_drift_for_frame`).

        Output format (plain text, no JSON support on this SPIRE version):
            Found N federation relationship
            Trust domain              : <td>
            Bundle endpoint URL       : https://...
            Bundle endpoint profile   : https_spiffe
            Endpoint SPIFFE ID        : spiffe://<td>/spire/server
        """
        rc, out, err = await self._spire([SPIRE_BIN_PATH, "federation", "list"])
        if rc != 0:
            return [], f"federation list failed: {(err or out).strip()[:300]}"

        domains: List[str] = []
        for line in (out or "").splitlines():
            m = re.match(
                r"^\s*Trust domain\s*:\s*(?:spiffe://)?([a-zA-Z0-9.\-]+)",
                line,
                re.IGNORECASE,
            )
            if m:
                td = _normalize_trust_domain(m.group(1))
                if td and td != self.local_trust_domain:
                    domains.append(td)

        return sorted(set(domains)), None

    async def ensure_federation_relationship(self, trust_domain: str, bundle_endpoint_url: str) -> Tuple[bool, dict]:
        """§MONEY-R52 — the third federation layer's RELATIONSHIP: `federation create` for a peer
        whose bundle was just imported, on this frame's SPIRE server. Idempotent (an existing
        relationship is reported, never rewritten); see plan_federation_relationship()."""
        async def _run(container: str, cmd: List[str]):
            return await self._spire(cmd)      # §F6 WP6.1: FRAME_TRUST_SPIRE_VIA decides the route
        return await ensure_federation_relationship(_run, self.spire_container, trust_domain,
                                                    bundle_endpoint_url, federation_overrides())

    async def get_bundle_freshness(self, trust_domain: str) -> BundleFreshness:
        """Fetch the imported PEM bundle for `trust_domain` and parse cert dates.

        Calls `spire-server bundle show -id spiffe://<td> -format pem`, loads
        the leaf cert via Python's cryptography lib, and returns:
          - not_before / not_after (UTC)
          - age_seconds since not_before
          - expires_in_seconds until not_after (negative = expired)
          - refresh_overdue / refresh_critical booleans against the thresholds

        On any CLI / parse failure, returns a BundleFreshness with .error set.
        Caller surfaces this on the UI ("freshness unknown").

        This closes the gap §pass53 root-caused: the existing detector only
        checks bundle PRESENCE, not AGE — so a SPIRE federation that stops
        refreshing leaves a stale-but-present bundle in place for days.
        """
        td = _normalize_trust_domain(trust_domain)
        if not td:
            return BundleFreshness(trust_domain=trust_domain, error="empty trust domain")
        if td == self.local_trust_domain:
            return BundleFreshness(trust_domain=td, error="own trust domain")

        # NB: `bundle show` is local-only; federated peer bundles are read via
        # `bundle list -id spiffe://<td>` (the `-id` filter is on `list`, not
        # `show`). The list output contains only the cert chain — no trust
        # domain banner — when -id is supplied, simplifying parse.
        rc, out, err = await self._spire([SPIRE_BIN_PATH, "bundle", "list", "-id", f"spiffe://{td}", "-format", "pem"])
        if rc != 0:
            return BundleFreshness(
                trust_domain=td,
                error=f"spire-server bundle list failed (rc={rc}): {(err or out).strip()[:200]}",
            )

        pem_text = (out or "").strip()
        if "-----BEGIN CERTIFICATE-----" not in pem_text:
            return BundleFreshness(
                trust_domain=td,
                error=f"bundle show returned no PEM cert (output={pem_text[:120]!r})",
            )

        try:
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend
            # If the bundle contains multiple certs (rotation overlap),
            # pick the LATEST not_before — that's the active issuance.
            cert_pems = re.findall(
                r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                pem_text, flags=re.DOTALL,
            )
            if not cert_pems:
                return BundleFreshness(trust_domain=td, error="no CERTIFICATE blocks parsed")
            picked = None
            for pem in cert_pems:
                cert = x509.load_pem_x509_certificate(pem.encode("utf-8"), default_backend())
                nb = cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before.replace(tzinfo=timezone.utc)
                if picked is None or nb > picked[1]:
                    na = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
                    picked = (cert, nb, na)
            cert, nb, na = picked
        except Exception as exc:
            return BundleFreshness(
                trust_domain=td,
                error=f"cert parse failed: {type(exc).__name__}: {exc}",
            )

        now = datetime.now(timezone.utc)
        age = (now - nb).total_seconds()
        exp_in = (na - now).total_seconds()
        return BundleFreshness(
            trust_domain=td,
            not_before=nb,
            not_after=na,
            age_seconds=age,
            expires_in_seconds=exp_in,
            refresh_overdue=age > BUNDLE_AGE_OVERDUE_SECONDS,
            refresh_critical=age > BUNDLE_AGE_CRITICAL_SECONDS or exp_in < 24 * 3600,
        )


# ---------------------------------------------------------------------------
# Module-level singleton (optional — router constructs its own for testability)
# ---------------------------------------------------------------------------

_default_manager: Optional[FrameTrustManager] = None


def get_frame_trust_manager() -> FrameTrustManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = FrameTrustManager()
    return _default_manager
