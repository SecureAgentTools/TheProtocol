"""§MTLSGAP (2026-09-08) — the console reads the federated index THROUGH this registry, over mTLS.

His word: *"everything is mtls enforced … i need to know if mtls is setup to directory otherwise we
need to set this up too."* It was not, in either direction. The Directory held no SVID at all, and
the console reached it over a hand-added `location /directory/ { proxy_pass http://127.0.0.1:8600/; }`
on the host vhost — plain http on loopback, with no identity on either end.

WHY A REGISTRY ROUTE AND NOT A CLIENT CERT ON THE HOST VHOST.
Host nginx could present a client certificate, but only by keeping a copy of an SVID's PRIVATE KEY
on the host filesystem, refreshed by cron against a 4-hour TTL. That is a new secret at rest and a
new way to fail quietly (a stale copy 401s and the strip renders empty — the §FXSTRAND shape). The
registry already holds a live, auto-rotating SVID for exactly this kind of hop, so the hop moves
here instead.

IT ALSO DELETES A LANE. §FRAMELIC's finding was that this capability needs THREE hand-added things
(the `/directory/` proxy, `DIRECTORY_PUBLIC_URL`, `DISCOVERY_VIA_DIRECTORY`) and a clean reprovision
removed the whole feature without erroring — *"its always the allow same origin problem with a new
standup."* With the index addressed as `/api/v1/public/directory`, the console vhost needs no
Directory lane at all: it falls through `location /` to the registry like every other API path. One
fewer thing a standup can forget.

⚠ THIS IS A FIXED-TARGET PROXY, NOT A RELAY. The upstream is `DIRECTORY_MTLS_URL` (server-side env)
and nothing in the request can change it; only POST /graphql is forwarded; the body is size-capped;
and the response is passed through unchanged so a GraphQL error still arrives as a GraphQL error
rather than becoming an empty list (a lane that renders "nobody is out there" on a broken index is
telling the reader a different sentence).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/public/directory", tags=["Public"])

# 256 KB: a GraphQL query with variables is a few KB. Anything larger is not this rail's traffic.
_MAX_BODY = 256 * 1024
_TIMEOUT = 20.0


def _upstream() -> str:
    return (os.getenv("DIRECTORY_MTLS_URL", "") or "").strip().rstrip("/")


def _client_kwargs(url: str) -> dict:
    """The SVID to present, and what to verify the far side with.

    The rule is the target's, not ours: port 443 (or a default) is a public host with a webPKI
    certificate, so the system CAs are right and the SPIRE bundle would refuse it; any other port
    is a SPIRE-served endpoint on the fabric, where the reverse holds. Getting this backwards is
    the §FABRICVERIFY class — a chooser that looks correct and fails one whole population.
    """
    kwargs: dict = {"timeout": _TIMEOUT}
    try:
        # ⚠ THE PACKAGE EXPORTS THE INSTANCE, NOT THE MODULE. `from ..identity import svid_client`
        # is the singleton every other caller in this codebase uses (federation_helper,
        # frame_invitations, guild, teg_integration_mtls). Reaching for `<module>.svid_client`
        # instead raises AttributeError, which the except below turns into "no SVID available" —
        # a real state that this is not. Measured live: the first EU wiring logged "dialing the
        # index WITHOUT a client SVID" and then CERTIFICATE_VERIFY_FAILED, and the only reason
        # that was diagnosable in one read is that the warning names what the path IS.
        from agentvault_registry.identity import svid_client
        cfg = svid_client.get_client_cert_config(url)
        if cfg:
            kwargs["cert"] = cfg["cert"]
            kwargs["verify"] = cfg["verify"]
            return kwargs
    except Exception as e:  # noqa: BLE001
        # LOUD, not debug: "the SVID client says it has no config" is a posture; "I could not even
        # ask it" is a defect, and they must not read the same.
        logger.warning("[directory] could not read the SVID config (%s: %s) — this is a WIRING "
                       "fault, not a posture", type(e).__name__, e)
    # UNKNOWN IS NOT EMPTY: with no SVID we still make the call (an index the console cannot read
    # is a worse outcome than one it reads without presenting a certificate) — but the far side
    # runs `ssl_verify_client on`, so this path is what a REFUSAL looks like, and it says so.
    logger.warning("[directory] dialing the index WITHOUT a client SVID — a gateway that verifies "
                   "clients will refuse this at the handshake")
    return kwargs


@router.post("/graphql")
async def directory_graphql(request: Request) -> Response:
    """Forward one GraphQL query to the federated index over mTLS, and return its answer verbatim."""
    up = _upstream()
    if not up:
        # Named, not silent: an unconfigured index is a posture, and the console shows the strip
        # only when `directory_url` is set, so this is reachable mainly by a direct caller.
        return Response(content='{"errors":[{"message":"no federated index is configured on this registry"}]}',
                        status_code=503, media_type="application/json")
    body = await request.body()
    if len(body) > _MAX_BODY:
        return Response(content='{"errors":[{"message":"query too large"}]}',
                        status_code=413, media_type="application/json")
    try:
        async with httpx.AsyncClient(**_client_kwargs(up)) as client:
            r = await client.post(f"{up}/graphql", content=body,
                                  headers={"Content-Type": "application/json"})
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))
    except Exception as e:  # noqa: BLE001
        # The failure is REPORTED, in the shape the caller parses. A lane that swallows this
        # renders an empty index, which reads as "nobody is out there".
        logger.warning("[directory] index unreachable at %s: %s", up, e)
        return Response(content='{"errors":[{"message":"the federated index is unreachable"}]}',
                        status_code=502, media_type="application/json")


@router.get("/health")
async def directory_health() -> Response:
    """The index's own health, read over the same mTLS hop, so a reader can tell an index that is
    down from a lane that is misconfigured, which the strip alone cannot."""
    up = _upstream()
    if not up:
        return Response(content='{"configured":false}', status_code=200, media_type="application/json")
    try:
        async with httpx.AsyncClient(**_client_kwargs(up)) as client:
            r = await client.get(f"{up}/health")
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[directory] health unreachable at %s: %s", up, e)
        return Response(content='{"configured":true,"reachable":false}', status_code=502,
                        media_type="application/json")
