"""A federation caller speaks only for itself (§TWOAGENT, the class of 2026-09-23; TESTPLAN FB5 + FB6).

Every federation route that acts FOR someone must bind the registry the request names to the caller's own SVID: a chat
participant's state and household join, a hosted delivery, a relayed message, a cross-registry delegation's listing and
revoke, a Guild bid and a stake slash. On 2026-09-23 each of them trusted a registry named in the body, eight times in
one day; V0429-V0436 bound them all.

The flow sends the SAME eight payloads to sandbox-B's federation lane twice: from a THIRD registry (the sandbox
operator, with its own SVID, which sandbox-B resolves to the operator itself, never to its parent) and from the REAL
home (sandbox-A). The stranger must be refused at the binding, by that sentence; the home must get past it (a different
answer). Where the two answers are the same by design (a revoke of a credential that is not live, a stake that is not
held: the answer confirms nothing either way), sandbox-B's own record tells them apart: the refusal audit row, the
refusal log line. Each run names its own order and credential ids, so those records count this run and nothing else.

Nothing real changes: every payload names a thread, order or credential that does not exist, or reads. The only fixture
read is a live cross-registry credential at sandbox-B (the ironkey cross-registry flow leaves them), so the listing leg
compares the home's non-empty answer with the stranger's empty one; with no such credential that leg is NOT MEASURED.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet, SANDBOX_REGISTRIES,
)
from agentvault_registry.api_tests.multiframe_helpers import (
    REG_DB_A, REG_DB_B, exec_in_container, run_psql_in_db_container, _get_container,
)

_A, _B, _THIRD = "sandbox-A", "sandbox-B", "sandboxalpha"

# Runs INSIDE a registry container: its own SVID, the frame's bundles, one call per line out. Prints status, a short
# detail, list lengths and a few flags per call; never the certificate or the key.
_CALLER = r'''
import glob, json, ssl, sys
import httpx
calls, target = json.loads(sys.argv[1]), sys.argv[2]
ctx = ssl.create_default_context()
ctx.check_hostname = False   # a SPIFFE certificate names a URI, not a host; the chain is what is verified
for pem in ["/certs/bundle.0.pem"] + sorted(glob.glob("/certs/federated_bundle.*.pem")):
    ctx.load_verify_locations(pem)
ctx.load_cert_chain("/certs/svid.0.pem", "/certs/svid.0.key")
with httpx.Client(verify=ctx, timeout=20) as c:
    for name, method, path, body in calls:
        try:
            r = c.request(method, target + path, json=body)
            try:
                b = r.json()
            except ValueError:
                b = r.text[:200]
            detail = b.get("detail") if isinstance(b, dict) else b
            lists = {k: len(v) for k, v in b.items() if isinstance(v, list)} if isinstance(b, dict) else {}
            flags = {k: b.get(k) for k in ("ok", "revoked", "already", "reason") if isinstance(b, dict) and k in b}
            print(json.dumps({"name": name, "status": r.status_code,
                              "detail": str(detail)[:240] if detail is not None else None,
                              "lists": lists, "flags": flags}))
        except Exception as e:
            print(json.dumps({"name": name, "error": type(e).__name__, "msg": str(e)[:200]}))
'''


def _public(url: str) -> str:
    """A peer row's address in its public form: scheme + host, no port (chat_federation.public_form)."""
    p = urlparse(str(url or "").strip())
    return f"{p.scheme.lower()}://{(p.hostname or '').lower()}" if p.scheme and p.hostname else ""


def _psql(container: str, sql: str) -> List[List[str]]:
    rc, out = run_psql_in_db_container(container, sql)
    if rc != 0:
        raise PreconditionUnmet(f"could not read {container!r} (rc={rc}): {out[:160]}")
    return [line.split("|") for line in out.strip().splitlines() if line.strip()]


def _run_calls(container: str, calls: List[list], target: str) -> Dict[str, Dict[str, Any]]:
    rc, out = exec_in_container(container, ["python", "-c", _CALLER, json.dumps(calls), target], timeout=120)
    rows: Dict[str, Dict[str, Any]] = {}
    for line in (out or "").splitlines():
        if line.startswith("{"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[r.get("name")] = r
    if not rows:
        raise PreconditionUnmet(f"the caller rig ran nothing in {container!r} (rc={rc}): {(out or '')[:200]}")
    return rows


def _refused_at_binding(r: Dict[str, Any], words: str) -> bool:
    return r.get("status") == 403 and words in str(r.get("detail") or "")


@federation_test(
    name="federation_caller_speaks_only_for_itself",
    category="federation_caller_binding",
    budget_sec=120.0,
    severity="critical",
    # The third registry is reached by docker exec with its own SVID, never through its MCP, so it is NOT a
    # requirement: listing it would make the preflight log in to the operator admin this flow never uses.
    requires=[_A, _B, "sandbox-A-admin", "sandbox-B-admin"],
    tags=["federation", "security", "caller_binding", "chat", "ironkey", "guild", "cross_frame"],
)
async def test_caller_binding(rig: FederationTestRig) -> AssertionResult:
    """Eight federation routes, the same payload from a stranger registry and from the real home: only the home passes."""
    t0 = time.monotonic()
    # Each frame's chat address (the one a key names) comes from its own status route.
    base: Dict[str, str] = {}
    for label, admin in ((_A, "sandbox-A-admin"), (_B, "sandbox-B-admin")):
        r = await rig.mcp(admin).call("adminRequest", {"method": "GET", "endpoint": "/api/v1/chat/federation/status"},
                                      timeout=60)
        body = (r or {}).get("response") if isinstance(r, dict) else None
        if not isinstance(body, dict) or not body.get("host_base_url"):
            raise PreconditionUnmet(f"chat federation status unreadable on {label}: {str(r)[:160]}")
        base[label] = _public(body["host_base_url"])
    home_url = base[_A]

    # sandbox-B's federation lane, as sandbox-A itself dials it (its peer row), never a literal.
    lanes = [row[0] for row in _psql(REG_DB_A, "SELECT base_url FROM peer_registries WHERE status = 'ACTIVE' "
                                               "AND base_url IS NOT NULL")
             if _public(row[0]) == base[_B]]
    if not lanes:
        raise PreconditionUnmet(f"sandbox-A holds no ACTIVE peer row for {base[_B]}")
    target = lanes[0].rstrip("/")

    # A sandbox-A agent that holds a live credential at sandbox-B, and that credential's delegate on sandbox-B.
    creds = _psql(REG_DB_B, "SELECT issuer_did, delegate_did, host_registry FROM agent_delegation_credentials "
                            "WHERE revoked_at IS NULL ORDER BY received_at DESC LIMIT 20")
    live = [c for c in creds if len(c) == 3 and _public(c[2]) == home_url]
    issuer = live[0][0] if live else f"did:theprotocol:fedsuite-no-issuer-{uuid.uuid4().hex[:8]}"
    delegate = live[0][1] if live else f"did:theprotocol:fedsuite-no-delegate-{uuid.uuid4().hex[:8]}"

    run = uuid.uuid4().hex[:12]
    order, cred, thread = f"fs-bind-{run}", f"fs-bind-cred-{run}", f"fs-bind-thread-{run}"
    calls = [
        ["state", "POST", "/api/v1/federation/chat/state",
         {"conversation_ref": thread, "participant_key": f"{issuer}@{home_url}", "state": "left"}],
        ["join", "POST", "/api/v1/federation/chat/state",
         {"conversation_ref": thread, "participant_key": f"fsowner-{run}@{home_url}", "state": "join",
          "household_of": f"{issuer}@{home_url}", "client_ref": f"fs-join-{run}"}],
        ["deliver", "POST", "/api/v1/federation/chat/deliver",
         {"v": 1, "host_registry": home_url, "conversation": {}, "message": {}}],
        ["relay-send", "POST", "/api/v1/federation/chat/relay-send",
         {"conversation_ref": thread, "sender_key": f"{issuer}@{home_url}", "sender_display": "fedsuite",
          "kind": "text", "body": "fedsuite caller binding", "client_ref": f"fs-relay-{run}"}],
        ["delegations-for-issuer", "GET", f"/api/v1/federation/ironkey/delegations-for-issuer?issuer_did={issuer}",
         None],
        ["delegation-revoke", "POST", "/api/v1/federation/ironkey/delegation-revoke",
         {"credential_id": cred, "issuer_registry": home_url}],
        ["guild-bid", "POST", f"/api/v1/federation/guild/orders/{order}/bid",
         {"bidder_did": issuer, "home_registry_url": home_url, "price": 0.1}],
        ["guild-stake", "POST", "/api/v1/federation/guild/stake",
         {"order_id": order, "bidder_did": delegate, "action": "slash", "host_registry": home_url}],
    ]
    since = int(time.time()) - 2
    stranger = _run_calls(SANDBOX_REGISTRIES[_THIRD].container, calls, target)
    home = _run_calls(SANDBOX_REGISTRIES[_A].container, calls, target)

    audit = _psql(REG_DB_B, "SELECT count(*) FROM security_audit_logs WHERE action LIKE "
                            f"'%xreg_delegation_revoke_refused' AND target_id = '{cred}'")
    audit_rows = int(audit[0][0]) if audit and audit[0] and audit[0][0].isdigit() else -1
    try:
        raw = _get_container(SANDBOX_REGISTRIES[_B].container).logs(since=since, stdout=True, stderr=True)
        log = raw.decode(errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        stake_lines: Optional[int] = log.count(f"remote stake slash on {order}/")
    except Exception as e:  # noqa: BLE001 (an unreadable log is NOT MEASURED, never zero)
        stake_lines, log = None, f"{type(e).__name__}: {e}"

    def pair(name: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return stranger.get(name) or {}, home.get(name) or {}

    legs: Dict[str, bool] = {}
    ev: Dict[str, Any] = {}
    for name, words in (("state", "not that participant's home registry"),
                        ("join", "not that participant's home registry"),
                        ("deliver", "not this thread's host"),
                        ("relay-send", "not the sender's home registry"),
                        ("guild-bid", "vouches only for its own agents")):
        s, h = pair(name)
        # the home must get PAST the binding: any answer that does not carry the binding's refusal
        legs[name] = (_refused_at_binding(s, words) and h.get("status") is not None
                      and words not in str(h.get("detail") or ""))
        ev[name] = {"stranger": [s.get("status"), s.get("detail")], "home": [h.get("status"), h.get("detail")]}
    s, h = pair("delegations-for-issuer")
    s_items, h_items = sum((s.get("lists") or {}).values()), sum((h.get("lists") or {}).values())
    legs["delegations-for-issuer"] = bool(live) and s.get("status") in (200, 403) and s_items == 0 \
        and h.get("status") == 200 and h_items >= 1
    ev["delegations-for-issuer"] = {"stranger": [s.get("status"), s_items], "home": [h.get("status"), h_items],
                                    "fixture": "a live credential at sandbox-B" if live else "NOT MEASURED: none"}
    s, h = pair("delegation-revoke")
    legs["delegation-revoke"] = ((s.get("flags") or {}).get("revoked") is False
                                 and (h.get("flags") or {}).get("revoked") is False and audit_rows == 1)
    ev["delegation-revoke"] = {"stranger": s.get("flags"), "home": h.get("flags"),
                               "refusal_audit_rows_for_this_run": audit_rows}
    s, h = pair("guild-stake")
    legs["guild-stake"] = ((s.get("flags") or {}).get("already") is True
                           and (h.get("flags") or {}).get("already") is True and stake_lines == 1)
    ev["guild-stake"] = {"stranger": s.get("flags"), "home": h.get("flags"),
                         "refusal_log_lines_for_this_run": stake_lines if stake_lines is not None else log[:160]}

    planned = ["state", "join", "deliver", "relay-send", "delegations-for-issuer", "delegation-revoke", "guild-bid",
               "guild-stake"]
    # §NIGHTPROV (2026-09-27): the promise the docstring makes, kept. With no live cross-registry credential at sandbox-B
    # the listing leg cannot tell a bound route from an open one (both answer an empty list), so it is NOT MEASURED,
    # named in the state and never counted as a failure; the legs that did measure still decide. Measured on a fresh
    # nightly pair (nt260927x3): seven legs passed and the run went red on the one that had nothing to compare.
    not_measured = [] if live else ["delegations-for-issuer"]
    failed = [n for n in planned if n not in not_measured and not legs.get(n)]
    return AssertionResult(
        passed=not failed and len(legs) == len(planned),
        description=("a third registry is refused at the caller binding on eight federation routes; the home is not"
                     + (f" (NOT MEASURED: {', '.join(not_measured)}, no live credential at sandbox-B)"
                        if not_measured else "")),
        budget_sec=0.0, elapsed_sec=time.monotonic() - t0, polling_attempts=1,
        last_state={"legs": legs, "evidence": ev, "target": target, "not_measured": not_measured},
        failure_detail=None if not failed else json.dumps({"failed": failed,
                                                           "evidence": {n: ev.get(n) for n in failed}},
                                                          default=str)[:700],
    )
