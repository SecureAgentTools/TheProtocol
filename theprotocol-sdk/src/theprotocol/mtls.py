"""
IRONHAND enrollment client — get an mTLS identity, wherever your agent runs.

`POST /agent/enable-mtls` adapts to where the caller is deployed. On the
registry's own host it hands back instructions for the SPIFFE Workload API
socket; anywhere else it issues a short-lived X509-SVID and returns it inline.
This client handles both, writes the inline case to disk in the layout
``MtlsAgentClient`` already reads, and keeps it fresh:

    from theprotocol.mtls import IronhandClient
    from theprotocol.payment import MtlsAgentClient

    iron = IronhandClient("https://api.theprotocol.cloud", cert_dir="/run/svid")
    enrollment = await iron.enroll(agent_jwt)

    if enrollment.delivery == "inline":
        client = MtlsAgentClient(cert_dir=iron.cert_dir)   # files are on disk
    elif enrollment.delivery == "workload_api":
        ...  # co-located: fetch via the Workload API socket instead

An inline SVID is short-lived ON PURPOSE — an issued key cannot be recalled, so
expiry IS the revocation mechanism. Re-enrolling is how you rotate:

    await iron.ensure_fresh(agent_jwt)          # no-op until the margin is hit
    task = iron.start_auto_rotate(agent_jwt)    # or let a background task do it
    ...
    task.cancel()

The private key is written ``0600`` and the directory ``0700``. Nothing here
logs key material.
"""
import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "IronhandClient",
    "Enrollment",
    "IronhandError",
    "IronhandUnavailableError",
    "IronhandPermissionError",
]


class IronhandError(RuntimeError):
    """Raised on a non-2xx enrollment response. Carries the HTTP status and the
    structured detail the registry returned."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"IRONHAND enrollment failed (HTTP {status_code}): {detail}")


class IronhandPermissionError(IronhandError):
    """The agent lacks the ``identity.mtls`` permission.

    Registries running IRONKEY in enforce mode gate enrollment on it. It rides
    the ``client`` and ``service-provider`` roles; an agent holding neither must
    be granted it by its owner via ``PUT /api/v1/agents/{did}/authz``.
    """


class IronhandUnavailableError(RuntimeError):
    """The registry could not issue a certificate, and said so honestly.

    Raised for ``delivery`` of ``unavailable`` (this registry does not hand out
    inline certificates and the agent is not on its host) or ``mint_failed``.
    NOTHING was enrolled — no identity is claimed anywhere. Agent-JWT and
    payment-token authentication continue to work; this only means mTLS is not
    available to this agent on this registry.
    """

    def __init__(self, delivery: str, message: str, instructions: str = ""):
        self.delivery = delivery
        self.instructions = instructions
        super().__init__(f"{message} {instructions}".strip())


@dataclass
class Enrollment:
    """Result of one enrollment call.

    ``delivery`` is the thing to branch on:
      ``inline``       — a certificate was issued and written to ``cert_dir``
      ``workload_api`` — co-located; fetch the SVID from the Workload API socket
    """

    delivery: str
    status: str
    spiffe_id: Optional[str] = None
    deployment: Optional[str] = None
    deployment_signal: Optional[str] = None
    expires_at: Optional[datetime] = None
    ttl_seconds: Optional[int] = None
    cert_dir: Optional[str] = None
    docker_label: Optional[str] = None
    instructions: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_files(self) -> bool:
        """True when this enrollment wrote svid/key/bundle to disk."""
        return self.delivery == "inline" and self.cert_dir is not None

    def seconds_remaining(self, now: Optional[datetime] = None) -> Optional[float]:
        if self.expires_at is None:
            return None
        return (self.expires_at - (now or datetime.now(timezone.utc))).total_seconds()


def _parse_expiry(value: Any) -> Optional[datetime]:
    """Parse the certificate's expiry. Returns None rather than raising: a
    certificate that arrived is still usable even if we cannot read its clock."""
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        logger.debug("IRONHAND: unparseable expires_at %r", value)
        return None


class IronhandClient:
    """Enroll an agent for mTLS against one registry and keep the SVID fresh."""

    #: refresh once this fraction of the certificate's lifetime remains
    DEFAULT_REFRESH_FRACTION = 0.5
    #: never let it get closer to expiry than this, whatever the fraction says
    DEFAULT_MIN_MARGIN_SECONDS = 120.0

    def __init__(
        self,
        registry_url: str,
        cert_dir: str = "/tmp/svid",
        *,
        refresh_fraction: float = DEFAULT_REFRESH_FRACTION,
        min_margin_seconds: float = DEFAULT_MIN_MARGIN_SECONDS,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.registry_url = registry_url.rstrip("/")
        self.cert_dir = cert_dir
        self.refresh_fraction = min(max(refresh_fraction, 0.05), 0.95)
        self.min_margin_seconds = max(min_margin_seconds, 0.0)
        self.timeout = timeout
        self._transport = transport
        self.last_enrollment: Optional[Enrollment] = None

    # ── paths, matching what MtlsAgentClient reads ──────────────────────────
    @property
    def svid_path(self) -> str:
        return os.path.join(self.cert_dir, "svid.pem")

    @property
    def key_path(self) -> str:
        return os.path.join(self.cert_dir, "key.pem")

    @property
    def bundle_path(self) -> str:
        return os.path.join(self.cert_dir, "bundle.pem")

    # ── enrollment ──────────────────────────────────────────────────────────
    async def enroll(self, agent_jwt: str) -> Enrollment:
        """Enroll (or rotate). Writes the three PEM files when the registry
        delivers an inline certificate.

        Raises:
            IronhandPermissionError: agent lacks ``identity.mtls``.
            IronhandError: any other non-2xx response.
            IronhandUnavailableError: the registry honestly declined to issue —
                nothing was enrolled and nothing claims an identity.
        """
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as http:
            resp = await http.post(
                f"{self.registry_url}/api/v1/agent/enable-mtls",
                headers={"Authorization": f"Bearer {agent_jwt}"},
                json={},
            )

        if resp.status_code not in (200, 201):
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:  # noqa: BLE001 — a non-JSON error body is still an error
                detail = resp.text
            if resp.status_code == 403 and "identity.mtls" in str(detail):
                raise IronhandPermissionError(resp.status_code, detail)
            # findings row 198 — a registry that CANNOT issue now says so with a 503 and a
            # reason, instead of the 200 "enrolled" it used to answer while creating a SPIRE
            # entry no agent could ever attest. That is the same condition `unavailable`
            # describes (nothing was enrolled, nothing claims an identity), so it gets the same
            # exception type rather than the generic one — a caller already branching on
            # IronhandUnavailableError should not have to learn a second shape for it. The
            # detail is passed through WHOLE: it names the cause, the fix and the doc link.
            if resp.status_code == 503:
                raise IronhandUnavailableError("unavailable", str(detail))
            raise IronhandError(resp.status_code, detail)

        body = resp.json()
        delivery = body.get("delivery", "")

        if delivery in ("unavailable", "mint_failed"):
            raise IronhandUnavailableError(
                delivery,
                body.get("message") or body.get("error") or "No certificate was issued.",
                body.get("instructions", ""),
            )

        enrollment = Enrollment(
            delivery=delivery or "unknown",
            status=body.get("status", ""),
            spiffe_id=body.get("spiffe_id"),
            deployment=body.get("deployment"),
            deployment_signal=body.get("deployment_signal"),
            docker_label=body.get("docker_label"),
            instructions=body.get("instructions", ""),
            raw=body,
        )

        svid = body.get("svid")
        if delivery == "inline" and isinstance(svid, dict):
            self._write_pems(svid)
            enrollment.cert_dir = self.cert_dir
            enrollment.ttl_seconds = svid.get("ttl_seconds")
            enrollment.expires_at = _parse_expiry(svid.get("expires_at"))
            enrollment.spiffe_id = svid.get("spiffe_id") or enrollment.spiffe_id
            logger.info(
                "IRONHAND: SVID written to %s for %s (expires %s)",
                self.cert_dir, enrollment.spiffe_id, enrollment.expires_at,
            )

        self.last_enrollment = enrollment
        return enrollment

    def _write_pems(self, svid: Dict[str, Any]) -> None:
        """Write svid/key/bundle. The key lands 0600 and is written via a
        temp file + rename, so a reader never observes a half-written key and
        never sees it at a permissive mode.
        """
        missing = [k for k in ("svid_pem", "key_pem", "bundle_pem") if not svid.get(k)]
        if missing:
            raise IronhandError(200, f"Inline delivery missing fields: {missing}")

        os.makedirs(self.cert_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(self.cert_dir, 0o700)
        except OSError:  # pragma: no cover — pre-existing dir owned elsewhere
            logger.debug("IRONHAND: could not tighten mode on %s", self.cert_dir)

        for content, path, mode in (
            (svid["svid_pem"], self.svid_path, 0o644),
            (svid["key_pem"], self.key_path, 0o600),
            (svid["bundle_pem"], self.bundle_path, 0o644),
        ):
            fd, tmp = tempfile.mkstemp(dir=self.cert_dir)
            try:
                os.write(fd, content.encode())
                os.close(fd)
                os.chmod(tmp, mode)
                os.replace(tmp, path)
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise

    # ── rotation ────────────────────────────────────────────────────────────
    def needs_refresh(self, now: Optional[datetime] = None) -> bool:
        """True when there is no certificate yet, or it is inside the margin.

        Never returns True for a ``workload_api`` enrollment: co-located agents
        hold no files and the socket rotates for them.
        """
        last = self.last_enrollment
        if last is None:
            return True
        if last.delivery != "inline":
            return False
        remaining = last.seconds_remaining(now)
        if remaining is None:
            return True  # unknown expiry: refresh rather than run a stale key
        margin = max(
            (last.ttl_seconds or 0) * self.refresh_fraction,
            self.min_margin_seconds,
        )
        return remaining <= margin

    async def ensure_fresh(self, agent_jwt: str) -> Optional[Enrollment]:
        """Re-enroll only if the certificate is missing or inside the margin.
        Returns the new Enrollment, or None when nothing needed doing."""
        if not self.needs_refresh():
            return None
        return await self.enroll(agent_jwt)

    def start_auto_rotate(
        self,
        agent_jwt: str,
        *,
        check_interval: float = 60.0,
        on_error=None,
    ) -> "asyncio.Task":
        """Background task that keeps the SVID fresh until cancelled.

        Transient failures are reported to ``on_error`` (or logged) and retried
        on the next tick rather than killing the loop — a registry hiccup should
        not permanently strand an agent whose certificate is still valid.
        ``IronhandUnavailableError`` and permission errors DO stop it: those are
        settled answers, not hiccups, and retrying cannot change them.
        """
        async def _loop() -> None:
            while True:
                try:
                    await self.ensure_fresh(agent_jwt)
                except (IronhandUnavailableError, IronhandPermissionError) as exc:
                    logger.error("IRONHAND auto-rotate stopping: %s", exc)
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — keep the loop alive
                    if on_error is not None:
                        on_error(exc)
                    else:
                        logger.warning("IRONHAND auto-rotate error (will retry): %s", exc)
                await asyncio.sleep(check_interval)

        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError(
                "start_auto_rotate() must be called from inside a running event "
                "loop (e.g. within async def main). Use ensure_fresh() otherwise."
            ) from exc
        return asyncio.create_task(_loop())
