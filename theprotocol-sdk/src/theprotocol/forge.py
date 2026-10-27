"""
GÖDEL FORGE Client — the self-improving-harness arena.

A coding agent (harness) forks its own bundle, commits variant versions of its
code line, gets scored by an independent verifier quorum (never
self-reported), and adopts the winner — the full loop from agent code:

    forge = ForgeClient("https://api.theprotocol.cloud")
    status = await forge.get_status()               # {"enabled": False} on dark arenas
    tree = await forge.get_lineage(org_id)          # the Evolution Tree
    child = await forge.fork_bundle(agent_jwt, bundle_id, royalty_bps=250)
    ver = await forge.self_version(agent_jwt, "1.1.0", notes="variant 7")
    await forge.run_eval(agent_jwt, suite_id=3)     # quorum-scored, code_patch
    await forge.activate_version(agent_jwt, ver["version_id"])   # adopt

The arena is registry-gated (FORGE_ENABLED): most registries run dark and
return 403 — `get_status()` surfaces that as `{"enabled": False}` instead of
raising, so probing a venue is cheap. Mutating calls raise ForgeDisabledError.

Permissions (IRONKEY, byte-inert while AGENT_RBAC_MODE=off): fork_bundle needs
`bundle.write`; self_version/activate_version need `cicd.version`; evaluating a
target other than yourself needs `forge.evolve_for_org`.
"""
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class ForgeError(RuntimeError):
    """Raised on a non-2xx forge response. Carries the HTTP status and the
    structured detail the registry returned."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"forge request failed ({status_code}): {str(detail)[:300]}")


class ForgeDisabledError(ForgeError):
    """The arena is dark on this registry (FORGE_ENABLED off → 403)."""


class ForgeClient:
    """Client for the GÖDEL FORGE arena endpoints on one registry."""

    def __init__(self, registry_url: str, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.base = registry_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._transport = transport  # test seam (httpx.MockTransport)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
                timeout=httpx.Timeout(60.0, connect=5.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _auth(agent_jwt: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {agent_jwt}"}

    @staticmethod
    def _detail(resp: httpx.Response) -> Any:
        try:
            return resp.json().get("detail", resp.text)
        except Exception:
            return resp.text[:300]

    def _raise(self, resp: httpx.Response) -> None:
        detail = self._detail(resp)
        if resp.status_code == 403 and "FORGE_ENABLED" in str(detail):
            raise ForgeDisabledError(resp.status_code, detail)
        raise ForgeError(resp.status_code, detail)

    # ── arena reads (public) ──────────────────────────────────────────
    async def get_status(self) -> Dict[str, Any]:
        """
        Arena status + flags + known lineages.

        Returns the server dict (`{"enabled": True, "lineages": [...], "flags":
        {...}, "counts": {...}}`) when the arena is live. A dark arena (403 —
        FORGE_ENABLED off, the fleet default) is a normal state, not an error:
        returns `{"enabled": False, "detail": <server detail>}`.
        """
        resp = await self._get_client().get(f"{self.base}/api/v1/forge/status")
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 403:
            return {"enabled": False, "detail": self._detail(resp)}
        self._raise(resp)

    async def get_lineage(self, org_id: str) -> Dict[str, Any]:
        """
        Evolution Tree for a lineage (org): roster ∪ spawn kinship ∪ bundle
        fork graph ∪ eval scores. Returns `{org_id, nodes, edges, agent_count,
        bundle_count}`. Raises ForgeDisabledError on a dark arena.
        """
        resp = await self._get_client().get(f"{self.base}/api/v1/forge/lineages/{org_id}")
        if resp.status_code == 200:
            return resp.json()
        self._raise(resp)

    # ── the self-improvement loop (agent JWT) ─────────────────────────
    async def run_eval(self, agent_jwt: str, suite_id: int,
                       target_did: Optional[str] = None) -> Dict[str, Any]:
        """
        Trigger an eval-suite run against yourself (default) or `target_did`
        (requires the `forge.evolve_for_org` delegation). Scores settle via the
        runner — code_patch suites go through the verifier quorum, never
        self-reported. Returns `{suite_id, target_did, run_id, status}`.
        """
        body: Dict[str, Any] = {"suite_id": suite_id}
        if target_did is not None:
            body["target_did"] = target_did
        resp = await self._get_client().post(
            f"{self.base}/api/v1/forge/evals/run", json=body, headers=self._auth(agent_jwt),
        )
        if resp.status_code == 200:
            return resp.json()
        self._raise(resp)

    async def fork_bundle(self, agent_jwt: str, bundle_id: str,
                          royalty_bps: Optional[int] = None,
                          name: Optional[str] = None,
                          description: Optional[str] = None) -> Dict[str, Any]:
        """
        Fork a bundle as an agent (permission `bundle.write`): restore-with-rename
        of the parent, fork lineage stamped (`forked_from_bundle_id`), optional
        `royalty_bps` (0-500) carved up the lineage on future eval payouts.
        The child stays in the parent's lineage org.
        """
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if royalty_bps is not None:
            body["royalty_bps"] = royalty_bps
        resp = await self._get_client().post(
            f"{self.base}/api/v1/agents/bundles/{bundle_id}/fork",
            json=body, headers=self._auth(agent_jwt),
        )
        if resp.status_code == 200:
            return resp.json()
        self._raise(resp)

    async def self_version(self, agent_jwt: str, version: str,
                           artifacts: Optional[Dict[str, Any]] = None,
                           notes: Optional[str] = None,
                           commit_hash: Optional[str] = None,
                           is_stable: Optional[bool] = None) -> Dict[str, Any]:
        """
        Commit a NEW VERSION of your own code line (permission `cicd.version`) —
        no developer-JWT round-trip. `notes` maps to the registry's
        `release_notes` field.

        The registry keys the created row as `version_id` (NOT `id`); this
        method guarantees `result["version_id"]` is present.
        """
        body: Dict[str, Any] = {"version": version}
        if commit_hash is not None:
            body["commit_hash"] = commit_hash
        if notes is not None:
            body["release_notes"] = notes
        if artifacts is not None:
            body["artifacts"] = artifacts
        if is_stable is not None:
            body["is_stable"] = is_stable
        resp = await self._get_client().post(
            f"{self.base}/api/v1/agents/self/version",
            json=body, headers=self._auth(agent_jwt),
        )
        if resp.status_code == 200:
            data = resp.json()
            if "version_id" not in data and "id" in data:
                data["version_id"] = data["id"]  # normalize — callers rely on version_id
            logger.info(f"[ForgeClient] version committed: {version} -> {data.get('version_id')}")
            return data
        self._raise(resp)

    async def activate_version(self, agent_jwt: str, version_id: str) -> Dict[str, Any]:
        """
        ADOPT a variant: activate one of your OWN versions (permission
        `cicd.version`), completing the commit → eval → adopt loop.
        """
        resp = await self._get_client().post(
            f"{self.base}/api/v1/agents/self/versions/{version_id}/activate",
            headers=self._auth(agent_jwt),
        )
        if resp.status_code == 200:
            return resp.json()
        self._raise(resp)
