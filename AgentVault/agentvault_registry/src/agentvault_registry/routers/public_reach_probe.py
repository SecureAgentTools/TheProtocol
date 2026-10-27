"""§EXTREACH design A (agentvault2-5b, 2026-10-14; his word "build A"): can the internet reach a new frame?

A self-hosted frame needs four public lanes before a peer will federate with it: the console (443), the federation
gateway (8443), the SPIRE bundle endpoint (8444) and the ledger gateway (8445). From its own host a frame cannot tell
whether the internet gets in: the router's port forwarding, the provider's firewall and carrier NAT are all outside
it, and the first sign used to be a peer refusing the invitation at step 5 (the peer dials the bundle endpoint before
it stores the invitation). This route dials back from the network: the kit's frame-reach.py (and frame-up at its end)
asks, the registry resolves the name and dials each lane once, and every port gets one verdict the kit turns into a
sentence ("8444: no answer from the internet: forward TCP 8444 to this machine").

    POST /api/v1/public/reach-probe   {"public_name": "frame.example.org", "ports": {"bundle": 8454, ...}}

Guards, so it cannot be turned against anyone:
- OFF unless REACH_PROBE_ENABLED=true (a positive flag; the network's root frame turns it on);
- only the address the name resolves to, and only a GLOBAL unicast one (no private, loopback, link-local, carrier-NAT
  or reserved address): it reaches nothing a stranger could not reach already;
- never this server's own addresses (REACH_PROBE_DENY_ADDRESSES plus whatever this registry's public URL resolves
  to): otherwise a stranger could ask it to dial, from inside, the docker ports the edge firewall closes;
- four ports, one TLS handshake each (plus one GET / on the bundle port), run concurrently;
- 10 probes an hour per caller and 60 an hour from everyone together, through the shared limiter;
- a port other than the four defaults only for a name that resolves to the caller itself (the kit asks from the
  frame's own host), so nobody can choose ports of a third party's host for this server to dial;
- one deadline per lane over dial and read together (lane_cap): a port that drips bytes cannot hold a probe open;
- no remote body is ever returned, only verdicts and the certificate's names.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agentvault_registry.core.client_ip import effective_client_ip
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/public", tags=["Public"])

ROLES = ("console", "federation", "bundle", "ledger")
DEFAULT_PORTS = {"console": 443, "federation": 8443, "bundle": 8444, "ledger": 8445}
CONNECT_TIMEOUT = 8.0
READ_TIMEOUT = 6.0
_NAME = re.compile(r"^(?=.{4,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


class ReachProbeRequest(BaseModel):
    public_name: str = Field(..., max_length=253, description="the frame's public name (its trust domain)")
    ports: Dict[str, int] = Field(default_factory=dict,
                                  description="role -> public port, for lanes moved off 443/8443/8444/8445")


def enabled() -> bool:
    return (os.environ.get("REACH_PROBE_ENABLED", "") or "").strip().lower() in ("1", "true", "yes", "on")


def normalize_name(name: str) -> str:
    """The name as a lower-case DNS hostname with at least one dot; a ValueError says why it is not one."""
    n = (name or "").strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(n)
    except ValueError:
        pass
    else:
        raise ValueError("public_name must be a DNS name, not an address: a frame's trust domain is its name")
    if not _NAME.match(n):
        raise ValueError("public_name must be a DNS name with at least one dot (letters, digits, hyphens)")
    return n


def plan_ports(ports: Dict[str, int]) -> List[Tuple[str, int]]:
    """(role, port) for the four lanes, a request's ports overriding the defaults; a ValueError says what is wrong."""
    unknown = sorted(set(ports or {}) - set(ROLES))
    if unknown:
        raise ValueError(f"unknown role(s) {', '.join(unknown)}; the roles are {', '.join(ROLES)}")
    out = []
    for role in ROLES:
        p = (ports or {}).get(role, DEFAULT_PORTS[role])
        if not isinstance(p, int) or isinstance(p, bool) or not 1 <= p <= 65535:
            raise ValueError(f"{role}: a port is a number from 1 to 65535")
        out.append((role, p))
    if len({p for _, p in out}) != len(out):
        raise ValueError("the four lanes need four different ports")
    return out


def deny_addresses() -> set:
    """This server's own addresses: the configured list plus what this registry's public URL resolves to."""
    deny = {a.strip() for a in (os.environ.get("REACH_PROBE_DENY_ADDRESSES", "") or "").split(",") if a.strip()}
    for var in ("PUBLIC_URL", "PUBLIC_UI_URL", "BASE_URL"):
        host = urlsplit((os.environ.get(var) or "").strip()).hostname
        if host:
            try:
                deny |= {ai[4][0] for ai in socket.getaddrinfo(host, None, socket.AF_INET)}
            except OSError:
                pass
    return deny


def choose_address(addresses: List[str], deny: set) -> Tuple[Optional[str], Optional[str]]:
    """(address, None) for the first global unicast address not in `deny`, else (None, the reason)."""
    if not addresses:
        return None, "no_address"
    for a in addresses:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if not ip.is_global or ip.is_multicast:
            return None, "private_address"
        if a in deny:
            return None, "this_server"
    return addresses[0], None


def certificate_names(der: Optional[bytes]) -> Tuple[List[str], List[str]]:
    """(DNS names, URIs) of a peer certificate the handshake did not verify."""
    if not der:
        return [], []
    try:
        from cryptography import x509
        cert = x509.load_der_x509_certificate(der)
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return ext.get_values_for_type(x509.DNSName), ext.get_values_for_type(x509.UniformResourceIdentifier)
    except Exception:  # noqa: BLE001 - a certificate without names is reported as such
        return [], []


def verdict_of(exc: BaseException) -> Tuple[str, str]:
    """(verdict, sentence) for a failed dial."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout", "no answer from the internet within 8 s: nothing forwards this port to the frame"
    if isinstance(exc, ConnectionRefusedError):
        return "refused", "the address answered, but nothing listens on this port there"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "certificate_invalid", f"TLS, but the certificate is not valid for the name: {exc.verify_message or 'unverified'}"
    if isinstance(exc, ssl.SSLError):
        return "not_tls", "something answers, but not with TLS"
    return "unreachable", f"the dial failed ({type(exc).__name__})"


async def _dial(address: str, name: str, port: int, verify: bool):
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return await asyncio.wait_for(asyncio.open_connection(address, port, ssl=ctx, server_hostname=name),
                                  CONNECT_TIMEOUT)


async def _read_bundle(reader, writer, name: str) -> Tuple[str, str]:
    writer.write(f"GET / HTTP/1.1\r\nHost: {name}\r\nUser-Agent: theprotocol-reach-probe/1\r\nAccept: application/json"
                 f"\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()
    data = await _read_until_deadline(reader, 262144, READ_TIMEOUT)
    head, _, body = data.partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0].decode(errors="replace").split()
    code = status[1] if len(status) > 1 else "?"
    if code != "200":
        return "not_a_bundle", f"TLS, but GET / answered {code}, not a SPIRE bundle (a JWK set)"
    if b"transfer-encoding: chunked" in head.lower():
        body = _dechunk(body)
    try:
        roots = [k for k in json.loads(body.decode(errors="replace")).get("keys", []) if k.get("use") == "x509-svid"]
    except (ValueError, AttributeError):
        roots = []
    if not roots:
        return "not_a_bundle", "TLS and 200, but no JWK set with x509 roots"
    return "ok", f"a SPIRE bundle with {len(roots)} x509 root(s)"


async def _read_until_deadline(reader, limit: int, budget: float) -> bytes:
    """Up to `limit` bytes, for at most `budget` seconds IN ALL (agentvault2-61's review, 2026-10-14): a timeout per
    chunk let a port that drips one byte every few seconds hold a probe, its socket and its coroutine for weeks."""
    loop = asyncio.get_running_loop()
    end = loop.time() + budget
    data = bytearray()
    while len(data) < limit:
        left = end - loop.time()
        if left <= 0:
            break
        try:
            chunk = await asyncio.wait_for(reader.read(65536), left)
        except (asyncio.TimeoutError, TimeoutError):
            break
        if not chunk:
            break
        data += chunk
    return bytes(data)


def lane_cap() -> float:
    """The most one lane may take, dial and read together; the outer bound the inner timeouts cannot exceed."""
    return CONNECT_TIMEOUT + READ_TIMEOUT + 3.0


async def probe_lane(address: str, name: str, role: str, port: int) -> Dict[str, Any]:
    """probe_port under one outer deadline: whatever a hostile endpoint does, a lane ends within lane_cap()."""
    t0 = time.monotonic()
    try:
        return await asyncio.wait_for(probe_port(address, name, role, port), lane_cap())
    except (asyncio.TimeoutError, TimeoutError):
        return {"role": role, "port": port, "verdict": "timeout", "ms": int((time.monotonic() - t0) * 1000),
                "detail": f"the lane did not finish within {lane_cap():.0f} s"}


def _dechunk(body: bytes) -> bytes:
    out, rest = b"", body
    while rest:
        size, _, rest = rest.partition(b"\r\n")
        try:
            n = int(size.split(b";")[0], 16)
        except ValueError:
            break
        if n == 0:
            break
        out, rest = out + rest[:n], rest[n + 2:]
    return out


async def probe_port(address: str, name: str, role: str, port: int) -> Dict[str, Any]:
    t0 = time.monotonic()
    row: Dict[str, Any] = {"role": role, "port": port}
    writer = None
    try:
        reader, writer = await _dial(address, name, port, verify=(role == "console"))
        if role == "console":
            row["verdict"], row["detail"] = "ok", f"TLS with a public certificate valid for {name}"
        else:
            sslobj = writer.get_extra_info("ssl_object")
            dns, uris = certificate_names(sslobj.getpeercert(binary_form=True) if sslobj else None)
            spiffe = next((u for u in uris if u.startswith("spiffe://")), "")
            if role == "bundle":
                row["verdict"], row["detail"] = await _read_bundle(reader, writer, name)
            elif name not in dns:
                row["verdict"] = "wrong_name"
                row["detail"] = f"TLS, but the certificate names {', '.join(dns) or 'no host'}, not {name}"
            else:
                row["verdict"], row["detail"] = "ok", f"TLS; the certificate names {name}" + (f" ({spiffe})" if spiffe else "")
    except Exception as e:  # noqa: BLE001 - every failure is a verdict
        row["verdict"], row["detail"] = verdict_of(e)
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 2)
            except Exception:  # noqa: BLE001
                pass
    row["ms"] = int((time.monotonic() - t0) * 1000)
    return row


def _everyone(request: Request) -> str:
    """One bucket for every caller: the global cap (agentvault2-61's review, 2026-10-14). Whatever the number of
    callers, this server dials at most GLOBAL_PER_HOUR probes an hour, so it cannot be made into a scanner."""
    return "reach-probe:global"


GLOBAL_PER_HOUR = "60/hour"


def custom_ports_refused(plan: List[Tuple[str, int]], addresses: List[str], caller: Optional[str]) -> bool:
    """True when a request moves a lane off its default port for a name that does not resolve to the caller.

    The four defaults are the lanes every frame publishes; a CUSTOM port is the frame's own business, so it is
    dialled only for the host that asks about itself (the kit runs on the frame's host, so its address is the
    name's). Otherwise a stranger could choose four ports of any host for this server to dial."""
    custom = any(port != DEFAULT_PORTS[role] for role, port in plan)
    return custom and not (caller and caller in addresses)


@router.post("/reach-probe", summary="Can the internet reach this frame's four lanes? (a dial-back, for frame-up)")
@limiter.limit("10/hour")
@limiter.limit(GLOBAL_PER_HOUR, key_func=_everyone)
async def reach_probe(request: Request, payload: ReachProbeRequest) -> Dict[str, Any]:
    if not enabled():
        raise HTTPException(status_code=503, detail="this registry does not offer the reachability probe "
                                                    "(REACH_PROBE_ENABLED); ask the network's root frame")
    try:
        name = normalize_name(payload.public_name)
        plan = plan_ports(payload.ports)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    caller = effective_client_ip(request)
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM), 10)
        addresses = sorted({i[4][0] for i in infos})
    except (OSError, asyncio.TimeoutError):
        addresses = []
    address, refusal = choose_address(addresses, deny_addresses())
    if not refusal and custom_ports_refused(plan, addresses, caller):
        refusal = "custom_ports_need_own_address"
    out: Dict[str, Any] = {"public_name": name, "addresses": addresses, "address": address, "caller_address": caller,
                           "name_points_at_caller": bool(caller and caller in addresses),
                           "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    if refusal:
        out.update(results=[], all_ok=False, refusal=refusal, detail={
            "no_address": f"{name} has no A record a resolver here can see: create one pointing at the frame",
            "private_address": f"{name} resolves to a private address the internet cannot reach: point it at the "
                               "frame's public address",
            "this_server": f"{name} resolves to this server itself; the probe dials other hosts only",
            "custom_ports_need_own_address": f"ports other than 443/8443/8444/8445 are dialled only when {name} "
                                             f"resolves to the address asking ({caller}); run the check on the frame's "
                                             "own host, or ask for the default ports",
        }[refusal])
        logger.info("[REACH-PROBE] caller=%s name=%s refused=%s", caller, name, refusal)
        return out
    results = await asyncio.gather(*(probe_lane(address, name, role, port) for role, port in plan))
    out["results"] = list(results)
    out["all_ok"] = all(r["verdict"] == "ok" for r in results)
    logger.info("[REACH-PROBE] caller=%s name=%s address=%s %s", caller, name, address,
                " ".join(f"{r['role']}:{r['port']}={r['verdict']}" for r in results))
    return out
