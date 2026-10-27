"""LocalDockerProbe — runs diagnostic primitives against containers on the
same host as the registry. Wraps blocking docker SDK calls in asyncio.to_thread.

Phase 2 will add RemoteSpiffeProbe over SPIFFE mTLS for off-host operators.
Both implementations satisfy the same surface so checks stay transport-agnostic.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


_DURATION_RE = re.compile(r"^(\d+)([smhd])$")


def _parse_since(since: str) -> int:
    """Parse a docker-style duration ('10m', '2h', '30s') to seconds."""
    m = _DURATION_RE.match(since.strip())
    if not m:
        return 600
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


# §CCFIX (2026-07-28) — rc values that mean THE PROBE failed, not that the subject is broken.
# 124 = our own asyncio timeout, 127 = docker SDK/daemon error. A check that cannot tell these
# apart from a real negative (e.g. `stat` rc=1 "no such file") will assert false facts about a
# healthy target whenever the box is busy — which is precisely what made six checks flap.
PROBE_FAILURE_CODES = frozenset({124, 127})


def probe_failed(rc: int) -> bool:
    """True when a non-zero rc reflects the PROBE failing rather than the subject's state."""
    return rc in PROBE_FAILURE_CODES


class LocalDockerProbe:
    """Per-process docker SDK wrapper. All calls go through to_thread."""

    def __init__(self):
        self._client = None

    def _client_sync(self):
        if self._client is None:
            import docker
            self._client = docker.from_env()
        return self._client

    async def container_exists(self, name: str) -> bool:
        def _sync():
            try:
                self._client_sync().containers.get(name)
                return True
            except Exception:
                return False
        return await asyncio.to_thread(_sync)

    async def container_status(self, name: str) -> str:
        def _sync():
            try:
                return self._client_sync().containers.get(name).status
            except Exception:
                return "missing"
        return await asyncio.to_thread(_sync)

    async def exec_in(
        self, container_name: str, cmd: list[str], timeout: int = 8, _retry: bool = True
    ) -> tuple[int, str]:
        """Run a command inside a container. Returns (exit_code, stdout+stderr).

        §CCFIX (2026-07-28) — ONE RETRY ON PROBE-INFRASTRUCTURE FAILURE.
        `docker exec` on this box normally answers in ~200-400ms, but under load (fleet rolls,
        image builds, sim bursts) it can blow past the caller's short timeout. Callers treat any
        non-zero rc as a statement ABOUT THE SUBJECT — e.g. spire-cert-rotation reported
        "no SVID found at known paths" when the file demonstrably existed. That is how six
        different checks came to flap ok<->unknown across runs and made the whole Command
        Center untrustworthy.
        124 (our timeout) and 127 (SDK/daemon error) mean THE PROBE failed, not that the
        subject is unhealthy, so they get one cheap retry before we report anything.
        """
        def _sync():
            try:
                container = self._client_sync().containers.get(container_name)
                exit_code, output = container.exec_run(cmd, demux=False)
                if isinstance(output, (bytes, bytearray)):
                    output = output.decode("utf-8", errors="replace")
                return exit_code, output or ""
            except Exception as e:
                return 127, f"exec failed: {e}"
        try:
            rc, out = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=timeout)
        except asyncio.TimeoutError:
            rc, out = 124, f"timeout after {timeout}s"
        if rc in PROBE_FAILURE_CODES and _retry:
            await asyncio.sleep(0.35)
            return await self.exec_in(container_name, cmd, timeout=timeout, _retry=False)
        return rc, out

    async def logs(
        self,
        container_name: str,
        since: Optional[str] = None,
        tail: int = 5000,
        grep_pattern: Optional[str] = None,
        max_bytes: int = 65536,
    ) -> str:
        """Read logs from a container.

        If ``tail`` is given (default), uses the SDK's ``tail`` argument so we
        don't blow the event loop up fetching hours of history. ``since`` is
        only honoured when explicitly set."""
        def _sync():
            try:
                container = self._client_sync().containers.get(container_name)
                kwargs: dict = {"tail": tail}
                if since:
                    seconds = _parse_since(since)
                    kwargs["since"] = datetime.now(timezone.utc) - timedelta(seconds=seconds)
                raw = container.logs(**kwargs)
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="replace")
                if grep_pattern:
                    pat = re.compile(grep_pattern)
                    raw = "\n".join(line for line in raw.splitlines() if pat.search(line))
                if len(raw) > max_bytes:
                    raw = raw[-max_bytes:]
                return raw
            except Exception as e:
                return f"log read failed: {e}"
        return await asyncio.to_thread(_sync)

    async def network_inspect(self, network_name: str) -> dict[str, Any]:
        def _sync():
            try:
                return self._client_sync().networks.get(network_name).attrs
            except Exception as e:
                return {"error": str(e)}
        return await asyncio.to_thread(_sync)

    async def container_inspect(self, container_name: str) -> dict[str, Any]:
        def _sync():
            try:
                return self._client_sync().containers.get(container_name).attrs
            except Exception as e:
                return {"error": str(e)}
        return await asyncio.to_thread(_sync)

    async def container_on_network(self, container_name: str, network_name: str) -> bool:
        """Check if a container is currently attached to the given Docker network.

        Used as an idempotent pre-check before `connect_to_network` to avoid the
        log-noise of catching a 403 Forbidden from the docker API when the
        connection already exists.
        """
        def _sync() -> bool:
            try:
                container = self._client_sync().containers.get(container_name)
                networks = (container.attrs or {}).get("NetworkSettings", {}).get("Networks", {}) or {}
                return network_name in networks
            except Exception:
                return False
        return await asyncio.to_thread(_sync)

    async def connect_to_network(
        self,
        container_name: str,
        network_name: str,
        aliases: list[str],
    ) -> tuple[int, str]:
        """Connect a container to a Docker network with the given alias(es).

        Idempotent: if the container is already on the network, returns rc=0
        without re-connecting (checked both proactively via container_on_network
        and reactively by catching docker's 403 APIError for endpoint-exists).

        Returns (rc, evidence):
          - rc=0: connected successfully OR already-connected (evidence indicates which)
          - rc=1: SDK / docker error (evidence has the reason)
          - rc=124: wait-for timeout (shouldn't happen in normal operation)
        """
        # Pre-check — short-circuit to avoid noisy 403.
        if await self.container_on_network(container_name, network_name):
            return 0, f"already on {network_name} (skip)"

        def _sync() -> tuple[int, str]:
            try:
                net = self._client_sync().networks.get(network_name)
                net.connect(container_name, aliases=list(aliases))
                return 0, f"connected {container_name} to {network_name} aliases={list(aliases)}"
            except Exception as e:
                msg = str(e)
                # Catch the docker-py idempotency race: "endpoint already exists"
                if "already exists" in msg.lower() or "403" in msg:
                    return 0, f"already on {network_name} (race, caught 403)"
                return 1, f"connect failed: {msg}"
        try:
            return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=15)
        except asyncio.TimeoutError:
            return 124, "connect wait timed out after 15s"

    async def container_restart(self, container_name: str, timeout: int = 10) -> tuple[int, str]:
        """Restart a container via docker-py SDK (NOT the `docker` CLI — that
        binary is not installed in the registry image; only the SDK + the
        mounted docker.sock). Matches the existing `exec_in` pattern.

        `timeout` is the graceful shutdown window: docker sends SIGTERM, then
        SIGKILL after `timeout` seconds. Tuned per-caller: cert-writer 10s is
        plenty, TEG 20s to let DB connections close cleanly.

        Returns (rc, evidence) — rc=0 ok, rc=1 SDK error, rc=124 wait timeout.
        """
        def _sync():
            try:
                container = self._client_sync().containers.get(container_name)
                container.restart(timeout=timeout)
                return 0, f"restarted {container_name} (graceful timeout={timeout}s)"
            except Exception as e:
                return 1, f"restart failed: {e}"
        try:
            return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=timeout + 10)
        except asyncio.TimeoutError:
            return 124, f"restart wait timed out after {timeout + 10}s"


_GLOBAL_PROBE: Optional[LocalDockerProbe] = None


def get_probe() -> LocalDockerProbe:
    """Singleton accessor for the LocalDockerProbe."""
    global _GLOBAL_PROBE
    if _GLOBAL_PROBE is None:
        _GLOBAL_PROBE = LocalDockerProbe()
    return _GLOBAL_PROBE
