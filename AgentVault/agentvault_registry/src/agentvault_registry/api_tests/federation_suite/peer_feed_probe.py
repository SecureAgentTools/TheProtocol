"""§MCPTEST30 (V0547) — the peers' feeds, read the way a peer reads them.

The two federation rows that named these feeds (federation_registry_cards_endpoint_reachable_per_frame and
federation_agent_cards_endpoint_reachable) called the MCP wrappers listFederationRegistryCards and
listFederationAgentCards. Their routes authenticate only a federation PEER (mTLS, the internal secret or a federation
licence), which no MCP caller holds; the wrappers turned the 401 into an empty list, and the rows passed on any dict
("empty list is fine in current sandbox state"): neither could fail, and both read the refusal as a reachable feed.

The feeds serve peers, so this probe reads one the way the sync worker does: inside sandbox-B's registry, with its own
SVID and its frame's bundles, at the address sandbox-B's own peer row names for sandbox-A. Then the same feed with no
client certificate, the control: a stranger must be refused. It prints status codes and counts, never a card.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.rig import (
    AssertionResult, FederationTestRig, PreconditionUnmet, SANDBOX_REGISTRIES,
)
from agentvault_registry.api_tests.multiframe_helpers import exec_in_container

READER, SOURCE = "sandbox-B", "sandbox-A"

_PROBE = r'''
import glob, json, ssl, sys
import httpx
base, path = sys.argv[1].rstrip("/"), sys.argv[2]

def context(with_cert):
    c = ssl.create_default_context()
    c.check_hostname = False   # a SPIFFE certificate names a URI, not a host; the chain is what is verified
    for pem in ["/certs/bundle.0.pem"] + sorted(glob.glob("/certs/federated_bundle.*.pem")):
        c.load_verify_locations(pem)
    if with_cert:
        c.load_cert_chain("/certs/svid.0.pem", "/certs/svid.0.key")
    return c

def count(body):
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        for k in ("agent_cards", "registry_cards", "items", "cards"):
            if isinstance(body.get(k), list):
                return len(body[k])
    return None

for name, with_cert in (("peer", True), ("stranger", False)):
    try:
        with httpx.Client(verify=context(with_cert), timeout=20) as cl:
            r = cl.get(base + path)
        try:
            body = r.json()
        except ValueError:
            body = None
        detail = body.get("detail") if isinstance(body, dict) else None
        print(json.dumps({"name": name, "status": r.status_code, "items": count(body),
                          "detail": str(detail)[:160] if detail is not None else None}))
    except Exception as e:
        print(json.dumps({"name": name, "error": type(e).__name__, "msg": str(e)[:160]}))
'''


def read_answers(out: str) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for line in (out or "").splitlines():
        if line.startswith("{"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[str(r.get("name"))] = r
    return rows


def verdict(rows: Dict[str, Dict[str, Any]], feed: str) -> Tuple[bool, str, Dict[str, Any]]:
    """(passed, sentence, evidence). Raises PreconditionUnmet when the probe could not decide."""
    peer, stranger = rows.get("peer") or {}, rows.get("stranger") or {}
    ev = {"peer": {k: peer.get(k) for k in ("status", "items", "detail", "error")},
          "stranger": {k: stranger.get(k) for k in ("status", "detail", "error")}}
    if peer.get("error") and peer.get("error") not in ("SSLError", "ConnectError", "ReadError", "RemoteProtocolError"):
        raise PreconditionUnmet(f"the probe could not ask sandbox-A's {feed} ({peer.get('error')}: {peer.get('msg')})")
    if stranger.get("status") == 200:
        return False, (f"BUG-FIND: sandbox-A's {feed} answered 200 to a caller with no client certificate: the peers' "
                       "feed serves a stranger"), ev
    if peer.get("status") != 200:
        return False, (f"sandbox-B's registry, with its own SVID, could not read sandbox-A's {feed} at the address its "
                       f"peer row names ({peer.get('status') or peer.get('error')}: {peer.get('detail') or peer.get('msg')}): "
                       "the path the sync worker takes is closed"), ev
    if peer.get("items") is None:
        return False, f"sandbox-A's {feed} answered 200 without a list a peer could read", ev
    if not (stranger.get("error") or (stranger.get("status") or 0) in (400, 401, 403, 495, 496)):
        raise PreconditionUnmet(f"the stranger's read of the {feed} answered neither a refusal nor a failed handshake: {ev}")
    return True, (f"sandbox-B's registry read sandbox-A's {feed} with its own SVID ({peer['items']} item(s)), and a "
                  "caller with no certificate was refused"), ev


async def _source_name(rig: FederationTestRig) -> Optional[str]:
    """sandbox-A's own name, from its own signed card (never inferred from a container)."""
    card = await rig.mcp(SOURCE).call("getRegistryCard")
    if not isinstance(card, dict):
        return None
    ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    return ident.get("registry_name") or card.get("registry_name")


async def _peer_base_url(rig: FederationTestRig, name: str) -> Optional[str]:
    """The address sandbox-B's own ACTIVE peer row names for sandbox-A (what its sync worker dials)."""
    body = await rig.mcp(READER).call("listFederationPeers")
    peers = body if isinstance(body, list) else (
        (body.get("items") or body.get("peers") or []) if isinstance(body, dict) else [])
    for p in peers:
        if isinstance(p, dict) and str(p.get("name") or "").lower() == name.lower() \
                and str(p.get("status") or "ACTIVE").upper() == "ACTIVE" and p.get("base_url"):
            return str(p["base_url"])
    return None


async def peer_feed_row(rig: FederationTestRig, path: str, feed: str) -> AssertionResult:
    t0 = time.monotonic()
    name = await _source_name(rig)
    if not name:
        raise PreconditionUnmet("sandbox-A's registry card named no registry")
    base = await _peer_base_url(rig, name)
    if not base:
        raise PreconditionUnmet(f"sandbox-B has no ACTIVE peer row named {name!r} with an address")
    container = SANDBOX_REGISTRIES[READER].container
    rc, out = exec_in_container(container, ["python", "-c", _PROBE, base, path], timeout=90)
    rows = read_answers(out)
    if "peer" not in rows:
        raise PreconditionUnmet(f"the probe ran nothing in {container!r} (rc={rc}): {(out or '')[:200]}")
    passed, sentence, ev = verdict(rows, feed)
    ev["target"] = base
    return AssertionResult(passed=passed, description=sentence, budget_sec=0.0,
                           elapsed_sec=time.monotonic() - t0, polling_attempts=1, last_state=ev,
                           failure_detail=None if passed else json.dumps(ev))
