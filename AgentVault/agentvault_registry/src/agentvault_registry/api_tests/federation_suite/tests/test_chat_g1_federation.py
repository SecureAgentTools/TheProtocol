"""OurChat across registries, G1 (§TWOAGENT, V0432-V0437): the hand-run proofs as flows the nightly re-runs.

FB7-FB10 and FB12 were proven by hand on the sandbox pair (`scratchpad/twoagent/b_sbx_v0431.py`) and on production.
These are the same claims, driven through the MCP chat tools a client uses (sendChatMessage with target_remote_key,
respondChatRequest, readThread with join, blockChatPrincipal / unblockChatPrincipal, all V0437), so a regression in
the MCP surface is caught here too. Every flow makes its own agents (one per frame), its own webhooks and its own
threads, and removes the agents and webhooks it made.

HOW A FLOW HEARS AN OWNER. Chat notifications are webhook-only (`notify_request_received`, `notify_request_accepted`,
`fan_out_message`) and the suite has no receiver. The registry records every dispatch, event and payload, whether or
not the receiver answers (`GET /webhooks/{id}/deliveries`), so a flow subscribes the owner with a webhook whose host is
`.invalid` (RFC 6761: it never resolves, so nothing leaves the box) and reads the dispatcher's own record. That is the
registry's answer to "was the owner told?", which is the claim. An unreadable record is never read as silence.
Retries run at +1 min and +5 min and a hook is disabled after 10 failures; a flow sends at most a handful of events per
hook and deletes it at the end (its deliveries cascade).

HOW A FLOW ADDRESSES SOMEONE ELSEWHERE. `GET /chat/federation/status` answers the registry's own chat address
(`host_base_url`, the one its keys carry) and the peers it will talk to. An address is `<did>@<that address>`,
lower-case, the one form a key takes (`chat_federation.remote_key`). A frame with cross-registry chat off, or not
listing the other frame as a peer, is NOT MEASURED, never a pass.

⚠ Writes: throwaway agents named `fedsuite-g1-*` on both frames (soft-deleted at the end), threads between them (there
is no delete-thread rail), and a visible owner join in the household flow. No money moves: the agents hold nothing and
chat has no money code.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet,
)

_TAG = "fedsuite-g1"
_A, _B = "sandbox-A", "sandbox-B"
_ADMIN = {_A: "sandbox-A-admin", _B: "sandbox-B-admin"}
_HEAR_SEC = 45.0     # FB9's window: an owner not told within it was not told
_POLL_SEC = 3.0
_JOINED = "joined as the owner of"
_REQUIRES = [_A, _B, _ADMIN[_A], _ADMIN[_B]]


# ─── plumbing ──────────────────────────────────────────────────────────────

def _soft(r: Any) -> Optional[str]:
    """The rig hands a tool failure back as {'_text': 'Error: ...'}; the refusal's reason is in that sentence."""
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """MCP call -> (result, refusal). `refusal` non-None means the call did not land; it carries the reason."""
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:  # noqa: BLE001 (MCPError included: a refusal, with its words)
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and isinstance(r.get("status_code"), int) and r["status_code"] >= 400:
        return r, f"wrapped HTTP {r['status_code']}: {json.dumps(r.get('response'))[:200]}"
    return r, _soft(r)


async def _rest(rig, method: str, endpoint: str, label: str) -> Tuple[int, Any]:
    """One REST read through adminRequest -> (status_code, body)."""
    try:
        r = await rig.mcp(label).call("adminRequest", {"method": method, "endpoint": endpoint}, timeout=60)
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


def _origin(url: str) -> str:
    u = str(url or "").strip().rstrip("/")
    p = urlparse(u)
    return f"{p.scheme.lower()}://{p.netloc.lower()}" if p.scheme and p.netloc else u.lower()


def _key(did: str, base: str) -> str:
    """The one form a remote key takes (chat_federation.remote_key): id@origin, lower-case."""
    return f"{did.lower()}@{_origin(base)}"


async def _until(fn: Callable[[], Awaitable[Any]], budget: float, every: float = _POLL_SEC) -> Any:
    """Poll `fn` until it returns something truthy or the budget runs out; returns the last value."""
    end = time.monotonic() + budget
    while True:
        last = await fn()
        if last or time.monotonic() >= end:
            return last
        await asyncio.sleep(every)


class _Legs:
    """Named legs, each with its evidence. A flow passes only when EVERY leg it planned ran and held: a leg that never
    ran is a failure, never an absence (the all()-over-empty trap)."""

    def __init__(self, planned: List[str]):
        self.planned = list(planned)
        self.got: Dict[str, bool] = {}
        self.evidence: Dict[str, Any] = {}
        self._missed: Dict[str, Callable[[], Awaitable[Any]]] = {}
        self._on_host: Dict[str, Callable[[], Awaitable[Any]]] = {}

    def check(self, name: str, ok: bool, evidence: Any = None) -> bool:
        assert name in self.planned, f"unplanned leg {name}"
        self.got[name] = bool(ok)
        self.evidence[name] = evidence
        return bool(ok)

    async def heard(self, name: str, told: Callable[[], Awaitable[Any]], budget: float, sent: Any = None,
                    on_host: Optional[Callable[[], Awaitable[Any]]] = None) -> Any:
        """A leg asking whether an owner was told: `told` polled for `budget` seconds. A miss stays a miss, and is
        asked once more just before the flow deletes its hooks (the dispatcher's record goes with the hook), so the
        evidence says which of three things was seen then: heard late, still nothing, or a record that could not be
        read. It never says why (§MCPTEST30 2026-10-06: a control leg heard nothing in the window while the message
        had reached the host on time, and nothing was left to tell late from never).

        V0641 (agentvault2-d6's D6-826, 4 such misses in 60 runs): `sent` is what the send this leg waits on answered
        (_sent_view: its refusal, or its relay receipt and seq), kept in the evidence; `on_host` is asked once on a miss,
        beside the re-read, and says whether the host's thread holds the message and at which seq. A relay the host
        refused and a message the host stored but never dispatched then read apart in the archive."""
        got = await _until(told, budget)
        evidence: Dict[str, Any] = {"deliveries": got}
        if sent is not None:
            evidence["send"] = sent
        if not self.check(name, bool(got), evidence):
            self._missed[name] = told
            if on_host is not None:
                self._on_host[name] = on_host
        return got

    async def reread_misses(self) -> None:
        """Ask each missed heard-leg once more (see heard()); the leg stays failed whatever this finds."""
        for name, told in self._missed.items():
            try:
                late = await told()
            except Exception as e:  # noqa: BLE001
                late = None
                seen = f"the record could not be read: {type(e).__name__}"
            else:
                seen = ("heard late, after the window" if late
                        else "the record could not be read" if late is None
                        else "still nothing")
            first = self.evidence.get(name) if isinstance(self.evidence.get(name), dict) else {}
            again: Dict[str, Any] = {"deliveries": first.get("deliveries"), "at_cleanup": seen, "late": late}
            if "send" in first:
                again["send"] = first["send"]
            host = self._on_host.get(name)
            if host is not None:
                try:
                    again["on_host"] = await host()
                except Exception as e:  # noqa: BLE001
                    again["on_host"] = {"unread": type(e).__name__}
            self.evidence[name] = again

    def result(self, description: str, t0: float) -> AssertionResult:
        missing = [n for n in self.planned if n not in self.got]
        failed = [n for n, ok in self.got.items() if not ok]
        passed = not missing and not failed
        state = {"legs": self.got, "not_run": missing, "evidence": self.evidence}
        detail = None if passed else json.dumps({"failed": failed, "not_run": missing,
                                                 "evidence": {n: self.evidence.get(n) for n in failed}},
                                                default=str)[:600]
        return AssertionResult(passed=passed, description=description, budget_sec=0.0,
                               elapsed_sec=time.monotonic() - t0, polling_attempts=1,
                               last_state=state, failure_detail=detail)


# ─── fixtures: frames, agents, webhooks ────────────────────────────────────

async def _frames(rig) -> Dict[str, str]:
    """Each frame's own chat address, and proof that each will talk to the other."""
    status: Dict[str, Dict[str, Any]] = {}
    for label in (_A, _B):
        code, body = await _rest(rig, "GET", "/api/v1/chat/federation/status", _ADMIN[label])
        if code != 200 or not isinstance(body, dict):
            raise PreconditionUnmet(f"chat federation status unreadable on {label}: HTTP {code} {str(body)[:160]}")
        if not body.get("enabled"):
            raise PreconditionUnmet(f"cross-registry chat is off on {label} (CHAT_FEDERATION_ENABLED): "
                                    f"nothing to measure")
        if not body.get("host_base_url"):
            raise PreconditionUnmet(f"{label} answers no chat address (host_base_url)")
        status[label] = body
    base = {label: _origin(s["host_base_url"]) for label, s in status.items()}
    for label, other in ((_A, _B), (_B, _A)):
        peers = {_origin(p) for p in (status[label].get("peers") or [])}
        if base[other] not in peers:
            raise PreconditionUnmet(f"{label} does not list {other}'s chat address {base[other]} among its chat "
                                    f"peers {sorted(peers)[:4]}: the frames are not chat peers")
    return base


async def _agent(rig, label: str, tag: str, made: List[Tuple[str, str]]) -> Dict[str, str]:
    """A throwaway agent with its own JWT. No bond and no funding: chat is not a bond site and moves no money."""
    name = f"{_TAG}-{tag}-{uuid.uuid4().hex[:8]}"
    r, refused = await _call(rig, label, "createAgent", {"name": name, "description": "federation suite G1 chat probe"})
    if refused or not isinstance(r, dict) or r.get("error"):
        raise PreconditionUnmet(f"createAgent refused on {label}: {refused or r.get('error')}")
    creds = r.get("credentials") or {}
    cid, sec = r.get("client_id") or creds.get("client_id"), r.get("client_secret") or creds.get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made(label, did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent on {label}: no credential triple (keys={sorted(r)[:8]})")
    made.append((label, did))
    t, tref = await _call(rig, label, "getAgentToken", {"client_id": cid, "client_secret": sec})
    jwt = (t or {}).get("access_token") or (t or {}).get("agent_jwt") if isinstance(t, dict) else None
    if tref or not jwt:
        raise PreconditionUnmet(f"getAgentToken refused on {label}: {tref}")
    return {"did": did, "jwt": jwt, "name": name, "label": label}


async def _hook(rig, label: str, events: List[str], hooks: List[Tuple[str, str]]) -> str:
    """Subscribe the frame's admin (the owner of every agent this file makes there) to `events`."""
    r, refused = await _call(rig, label, "createWebhook", {
        "url": f"https://{_TAG}-{uuid.uuid4().hex[:10]}.invalid/hook",
        "events": events,
        "description": "federation suite G1: a host that never resolves; the flow reads the dispatcher's record"})
    if refused or not isinstance(r, dict) or not r.get("id"):
        raise PreconditionUnmet(f"createWebhook refused on {label}: {refused or str(r)[:160]}")
    hooks.append((label, r["id"]))
    return r["id"]


async def _told(rig, label: str, hook_id: str, event: str, conv_id: str,
                match: Optional[Callable[[Dict[str, Any]], bool]] = None) -> Optional[List[Dict[str, Any]]]:
    """What the dispatcher sent this hook for `event` in `conv_id` (one entry per delivery), or None when the record
    could not be read. None is never silence."""
    r, refused = await _call(rig, label, "getWebhookDeliveries", {"webhook_id": hook_id, "limit": 100})
    if refused or not isinstance(r, dict) or not isinstance(r.get("deliveries"), list):
        return None
    out: List[Dict[str, Any]] = []
    seen = set()
    for d in r["deliveries"]:
        if not isinstance(d, dict) or d.get("event_type") != event:
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        # the envelope as sent (§TWOAGENT #33), or the bare data an older image stored
        data = p.get("data") if isinstance(p.get("data"), dict) else p
        if str(data.get("conversation_id") or "") != conv_id:
            continue
        if match is not None and not match(data):
            continue
        ident = p.get("id") or d.get("id")
        if ident in seen:
            continue
        seen.add(ident)
        out.append(data)
    return out


def _body_is(text: str) -> Callable[[Dict[str, Any]], bool]:
    return lambda data: str(((data.get("message") or {}).get("body")) or "") == text


def _body_has(text: str) -> Callable[[Dict[str, Any]], bool]:
    return lambda data: text in str(((data.get("message") or {}).get("body")) or "")


async def _cleanup(rig, made: List[Tuple[str, str]], hooks: List[Tuple[str, str]]) -> List[str]:
    """Remove what the flow made; returns what it could NOT remove. Never silent: the ironkey flows' cleanup passed
    `did` to a tool that takes `agent_did`, threw the refusal away, and left 3,506 agents on sandbox-A and 543 on
    sandbox-B between 2026-09-04 and 2026-09-23 while their docstring called the residue bounded."""
    left: List[str] = []
    for label, hook_id in hooks:
        _, refused = await _call(rig, label, "deleteWebhook", {"webhook_id": hook_id})
        if refused:
            left.append(f"webhook {hook_id} on {label}: {refused[:120]}")
    for label, did in made:
        _, refused = await throwaways.retire(rig, label, did)      # V0641: what it holds goes back first
        if refused:
            left.append(f"agent {did} on {label}: {refused[:120]}")
    return left


async def _run(rig, planned: List[str], description: str,
               body: Callable[[_Legs, List[Tuple[str, str]], List[Tuple[str, str]]], Awaitable[None]]) -> AssertionResult:
    """Run a flow body, then remove what it made and judge that too: a flow that leaves its fixtures behind is red."""
    t0 = time.monotonic()
    legs = _Legs(planned + ["the_flow_removed_what_it_made"])
    made: List[Tuple[str, str]] = []
    hooks: List[Tuple[str, str]] = []
    ran = False
    try:
        await body(legs, made, hooks)
        ran = True
    finally:
        await legs.reread_misses()
        left = await _cleanup(rig, made, hooks)
        if ran:
            legs.check("the_flow_removed_what_it_made", not left, {"left": left})
    return legs.result(description, t0)


# ─── chat steps (MCP) ──────────────────────────────────────────────────────

def _ref() -> str:
    return f"{_TAG}-{uuid.uuid4().hex}"


def _posted(r: Any) -> Any:
    """A post into a thread answers `{"message": <msg>, "my_state": ...}` (routers/chat.py::post_message), where <msg>
    is the stored message at a host and the relay receipt (`relayed`, `host_seq`, `duplicate`) on a mirror; a CREATE
    (`target_remote_key`) answers its fields at the top. Read a post's fields from its message."""
    return r["message"] if isinstance(r, dict) and isinstance(r.get("message"), dict) else r


def _sent_view(r: Any, refused: Optional[str]) -> Dict[str, Any]:
    """What a send answered, for the evidence of the heard leg that waits on it (D6-826): its refusal, or its post's
    relay receipt (relayed, host_seq, duplicate) at a mirror and its seq at a host."""
    if refused:
        return {"refused": str(refused)[:200]}
    m = _posted(r)
    if not isinstance(m, dict):
        return {"answer": str(m)[:200]}
    return {k: m.get(k) for k in ("relayed", "host_seq", "seq", "duplicate") if k in m}


def _on_host(rig, label: str, host_agent: Dict[str, str], host_conv: str,
             body: str) -> Callable[[], Awaitable[Dict[str, Any]]]:
    """Asked once when a heard leg missed (D6-826): does the host's thread, read by its own agent, hold `body`, and at
    which seq."""
    async def look() -> Dict[str, Any]:
        page, refused = await _read(rig, label, host_agent, host_conv)
        if refused or not isinstance(page, dict) or not isinstance(page.get("messages"), list):
            return {"unread": str(refused or "no thread page")[:160]}
        hit = next((m for m in page["messages"] if isinstance(m, dict) and m.get("body") == body), None)
        return {"present": hit is not None, "seq": (hit or {}).get("seq")}
    return look


async def _send(rig, label: str, speaker: Optional[Dict[str, str]], body: str, **target) -> Tuple[Any, Optional[str]]:
    """sendChatMessage as `speaker` (an agent), or as the frame's admin developer when speaker is None."""
    args: Dict[str, Any] = {"body": body, "client_ref": target.pop("client_ref", None) or _ref(), **target}
    if speaker is not None:
        args["agent_jwt"] = speaker["jwt"]
    return await _call(rig, label, "sendChatMessage", args)


async def _read(rig, label: str, speaker: Optional[Dict[str, str]], conv_id: str,
                join: bool = False) -> Tuple[Any, Optional[str]]:
    args: Dict[str, Any] = {"conversation_id": conv_id, "limit": 50}
    if join:
        args["join"] = True
    if speaker is not None:
        args["agent_jwt"] = speaker["jwt"]
    return await _call(rig, label, "readThread", args)


def _joins(page: Any) -> Optional[int]:
    """Visible household joins on a thread page, or None when the page is not one."""
    if not isinstance(page, dict) or not isinstance(page.get("messages"), list):
        return None
    return sum(1 for m in page["messages"]
               if isinstance(m, dict) and m.get("kind") == "system" and _JOINED in str(m.get("body") or ""))


async def _mirror_of(rig, speaker: Dict[str, str], counterparty_key: str, lane: str) -> Optional[str]:
    """The thread on `speaker`'s frame whose counterparty is `counterparty_key` (V0436 lists carry `remote_key`)."""
    r, refused = await _call(rig, speaker["label"], "listConversations", {"state": lane, "agent_jwt": speaker["jwt"]})
    if refused or not isinstance(r, dict):
        return None
    for c in r.get("conversations") or []:
        cp = (c or {}).get("counterparty") or {}
        if str(cp.get("remote_key") or "").lower() == counterparty_key:
            return c.get("id")
    return None


async def _knock_and_find(rig, legs: _Legs, n: Dict[str, str], w: Dict[str, str], w_key: str,
                          n_key: str, base: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """N (sandbox-A) knocks W (sandbox-B) by address; returns (host thread, W's mirror) or None."""
    r, refused = await _send(rig, _A, n, f"{_TAG} knock", target_remote_key=w_key)
    ok = (not refused and isinstance(r, dict) and r.get("federated") is True and r.get("created") is True
          and bool(r.get("conversation_id")) and _origin(str(r.get("host") or "")) == base[_A])
    if not legs.check("knock_hosted_by_the_sender", ok, {"refused": refused, "answer": r}):
        return None
    host_conv = r["conversation_id"]
    mirror = await _until(lambda: _mirror_of(rig, w, n_key, "requests"), _HEAR_SEC)
    if not legs.check("knock_waits_in_the_recipients_requests", bool(mirror), {"mirror": mirror}):
        return None
    return host_conv, mirror


# ─── FB8 + V0437 (4) + FB10 + FB7 ──────────────────────────────────────────

@federation_test(
    name="chat_g1_round_trip_a_reply_accepts_the_knock",
    category="chat_federation",
    budget_sec=240.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "g1", "cross_frame", "webhooks"],
)
async def test_g1_round_trip(rig: FederationTestRig) -> AssertionResult:
    """An agent on sandbox-A knocks an agent on sandbox-B by address; the reply is the accept.

    FB8: the recipient's owner hears the knock, the reply travels to the host, the knocker's owner hears it, and the
    replying agent's own owner is not woken by its own reply coming home. V0437 (4): a reply that accepts a knock tells
    the knocker's owner (`chat.request.accepted`); before V0437 the host flipped the row silently and only an explicit
    accept was ever heard. FB10: opening a dm from the other side lands in the SAME thread. FB7: a replayed client_ref
    is one message at the host.
    """
    async def body(legs: _Legs, made, hooks) -> None:
        base = await _frames(rig)
        n = await _agent(rig, _A, "n", made)
        w = await _agent(rig, _B, "w", made)
        n_key, w_key = _key(n["did"], base[_A]), _key(w["did"], base[_B])
        hook_a = await _hook(rig, _A, ["chat.request.accepted", "chat.message.received"], hooks)
        hook_b = await _hook(rig, _B, ["chat.request.received", "chat.message.received"], hooks)

        found = await _knock_and_find(rig, legs, n, w, w_key, n_key, base)
        if found is None:
            return
        host_conv, mirror = found

        await legs.heard("recipients_owner_hears_the_knock",
                         lambda: _told(rig, _B, hook_b, "chat.request.received", mirror), _HEAR_SEC)

        reply, reply_ref = f"{_TAG} reply {uuid.uuid4().hex[:6]}", _ref()
        r, refused = await _send(rig, _B, w, reply, conversation_id=mirror, client_ref=reply_ref)
        r = _posted(r)
        reply_at = time.monotonic()
        legs.check("reply_relayed_to_the_host",
                   not refused and isinstance(r, dict) and r.get("relayed") is True
                   and isinstance(r.get("host_seq"), int), {"refused": refused, "answer": r})

        await legs.heard("knockers_owner_hears_the_accept_by_reply", lambda: _told(
            rig, _A, hook_a, "chat.request.accepted", host_conv,
            lambda d: str(d.get("accepted_by") or "").lower() == w_key), _HEAR_SEC)

        await legs.heard("knockers_owner_hears_the_reply",
                         lambda: _told(rig, _A, hook_a, "chat.message.received", host_conv, _body_is(reply)), _HEAR_SEC)

        again, aref = await _send(rig, _B, w, reply, conversation_id=mirror, client_ref=reply_ref)
        again = _posted(again)
        page, pref = await _read(rig, _A, n, host_conv)
        copies = (sum(1 for m in page.get("messages") or [] if isinstance(m, dict) and m.get("client_ref") == reply_ref)
                  if isinstance(page, dict) else None)
        legs.check("a_replay_is_one_message_at_the_host",
                   not aref and isinstance(again, dict) and again.get("duplicate") is True and copies == 1,
                   {"answer": again, "refused": aref, "copies_at_host": copies, "read_refused": pref})

        o, oref = await _send(rig, _B, w, f"{_TAG} same thread", target_remote_key=n_key)
        legs.check("the_other_side_opens_the_same_thread",
                   not oref and isinstance(o, dict) and o.get("conversation_id") == mirror
                   and o.get("created") is False and _origin(str(o.get("host") or "")) == base[_A],
                   {"answer": o, "refused": oref, "mirror": mirror})

        # V0441: the mirror names who wrote (a peer's agent by its card once mirrored, by its address before; never
        # blank, which is what every remote message read as), the thread it is with, and who holds the thread.
        mp, mref = await _read(rig, _B, w, mirror)
        knock_msg = next((m for m in (mp.get("messages") or []) if isinstance(m, dict)
                          and m.get("body") == f"{_TAG} knock"), None) if isinstance(mp, dict) else None
        named = str((knock_msg or {}).get("sender_name") or "")
        legs.check("the_mirror_names_the_remote_sender", named in (n["name"], n_key),
                   {"sender_name": named, "card_name": n["name"], "address": n_key, "refused": mref})
        cp = (mp.get("counterparty") or {}) if isinstance(mp, dict) else {}
        legs.check("the_mirror_names_the_agent_the_thread_is_with",
                   str(cp.get("remote_key") or "").lower() == n_key and str(cp.get("name") or "") in (n["name"], n_key),
                   {"counterparty": cp, "expected": n_key})
        hp, href = await _read(rig, _A, n, host_conv)
        mh = (mp.get("hosting") or {}) if isinstance(mp, dict) else {}
        hh = (hp.get("hosting") or {}) if isinstance(hp, dict) else {}
        legs.check("both_sides_name_the_host_and_the_copy",
                   hh.get("here") is True and mh.get("here") is False and bool(hh.get("registry"))
                   and mh.get("registry") == hh.get("registry") and bool(hh.get("copies"))
                   and mh.get("copies") == hh.get("copies") and hh.get("registry") not in hh.get("copies"),
                   {"host": hh, "mirror": mh, "refused": href})

        await asyncio.sleep(max(0.0, reply_at + _HEAR_SEC - time.monotonic()))
        own = await _told(rig, _B, hook_b, "chat.message.received", mirror, _body_is(reply))
        legs.check("a_reply_does_not_wake_its_own_owner", own == [],
                   {"deliveries": own, "note": "None = the record was unreadable, never silence"})

    return await _run(rig, [
        "knock_hosted_by_the_sender", "knock_waits_in_the_recipients_requests", "recipients_owner_hears_the_knock",
        "reply_relayed_to_the_host", "knockers_owner_hears_the_accept_by_reply", "knockers_owner_hears_the_reply",
        "a_replay_is_one_message_at_the_host", "the_other_side_opens_the_same_thread",
        "the_mirror_names_the_remote_sender", "the_mirror_names_the_agent_the_thread_is_with",
        "both_sides_name_the_host_and_the_copy", "a_reply_does_not_wake_its_own_owner"],
        "G1: a cross-registry knock, answered by a reply, heard by both owners", body)


# ─── FB9 (+ step 3b): a block is silent, on both legs ──────────────────────

@federation_test(
    name="chat_g1_block_is_silent_on_both_legs",
    category="chat_federation",
    budget_sec=300.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "g1", "cross_frame", "webhooks", "blocks"],
)
async def test_g1_blocks(rig: FederationTestRig) -> AssertionResult:
    """A principal on a peer registry can be blocked, at the host and at the home, and the block is silent.

    FB9 on an explicitly accepted thread hosted on sandbox-A (the accept is heard: FB8). HOST leg: N blocks W's address
    on sandbox-A, N's seat leaves, W's next reply is relayed and accepted by the host yet reaches no N owner, and N
    opening a dm to W is refused by name. Step 3b: N unblocks and opens the dm again, and it is the same thread, active.
    HOME leg: W blocks N's address on sandbox-B, W's seat leaves, N's next message is accepted at the host yet reaches
    no W owner. A block cannot take an address too long to store (refused by name). Controls: before either block, a
    message in each direction reached the other owner, so the silence is the block's and not the instrument's.
    """
    async def body(legs: _Legs, made, hooks) -> None:
        base = await _frames(rig)
        n = await _agent(rig, _A, "n", made)
        w = await _agent(rig, _B, "w", made)
        n_key, w_key = _key(n["did"], base[_A]), _key(w["did"], base[_B])
        hook_a = await _hook(rig, _A, ["chat.request.accepted", "chat.message.received"], hooks)
        hook_b = await _hook(rig, _B, ["chat.message.received"], hooks)

        found = await _knock_and_find(rig, legs, n, w, w_key, n_key, base)
        if found is None:
            return
        host_conv, mirror = found

        r, refused = await _call(rig, _B, "respondChatRequest",
                                 {"conversation_id": mirror, "action": "accept", "agent_jwt": w["jwt"]})
        accepted = await _until(lambda: _told(rig, _A, hook_a, "chat.request.accepted", host_conv), _HEAR_SEC)
        legs.check("an_explicit_accept_is_heard", not refused and bool(accepted),
                   {"refused": refused, "deliveries": accepted})

        c1 = f"{_TAG} control n->w {uuid.uuid4().hex[:6]}"
        r1, ref1 = await _send(rig, _A, n, c1, conversation_id=host_conv)
        await legs.heard("control_n_to_w_reaches_ws_owner",
                         lambda: _told(rig, _B, hook_b, "chat.message.received", mirror, _body_is(c1)), _HEAR_SEC,
                         sent=_sent_view(r1, ref1), on_host=_on_host(rig, _A, n, host_conv, c1))
        c2 = f"{_TAG} control w->n {uuid.uuid4().hex[:6]}"
        r2, ref2 = await _send(rig, _B, w, c2, conversation_id=mirror)
        await legs.heard("control_w_to_n_reaches_ns_owner",
                         lambda: _told(rig, _A, hook_a, "chat.message.received", host_conv, _body_is(c2)), _HEAR_SEC,
                         sent=_sent_view(r2, ref2), on_host=_on_host(rig, _A, n, host_conv, c2))

        # HOST leg: N blocks W on sandbox-A.
        r, refused = await _call(rig, _A, "blockChatPrincipal",
                                 {"ptype": "remote", "remote_key": w_key, "agent_jwt": n["jwt"]})
        legs.check("host_block_answers", not refused and isinstance(r, dict) and r.get("blocked") is True,
                   {"refused": refused, "answer": r})
        page, pref = await _read(rig, _A, n, host_conv)
        legs.check("host_block_leaves_ns_seat", isinstance(page, dict) and page.get("my_state") == "left",
                   {"my_state": page.get("my_state") if isinstance(page, dict) else None, "refused": pref})
        hidden = f"{_TAG} while host-blocked {uuid.uuid4().hex[:6]}"
        r, refused = await _send(rig, _B, w, hidden, conversation_id=mirror)
        r = _posted(r)
        hidden_at = time.monotonic()
        legs.check("a_blocked_reply_is_still_accepted_by_the_host",
                   not refused and isinstance(r, dict) and r.get("relayed") is True
                   and isinstance(r.get("host_seq"), int), {"refused": refused, "answer": r})
        r, refused = await _send(rig, _A, n, f"{_TAG} knock again", target_remote_key=w_key)
        legs.check("opening_a_dm_to_a_blocked_address_is_refused",
                   bool(refused) and "you have blocked this principal" in refused, {"refused": refused, "answer": r})

        # Step 3b: unblock, and the pair's thread comes back active.
        r, refused = await _call(rig, _A, "unblockChatPrincipal",
                                 {"ptype": "remote", "remote_key": w_key, "agent_jwt": n["jwt"]})
        legs.check("unblock_answers", not refused and isinstance(r, dict) and r.get("removed") is True,
                   {"refused": refused, "answer": r})
        r, refused = await _send(rig, _A, n, f"{_TAG} back", target_remote_key=w_key)
        legs.check("reopening_after_unblock_is_the_same_thread_active",
                   not refused and isinstance(r, dict) and r.get("conversation_id") == host_conv
                   and r.get("created") is False and r.get("my_state") == "active"
                   and isinstance(r.get("first_message"), dict), {"refused": refused, "answer": r})

        # HOME leg: W blocks N on sandbox-B.
        r, refused = await _call(rig, _B, "blockChatPrincipal",
                                 {"ptype": "remote", "remote_key": n_key, "agent_jwt": w["jwt"]})
        legs.check("home_block_answers", not refused and isinstance(r, dict) and r.get("blocked") is True,
                   {"refused": refused, "answer": r})
        page, pref = await _read(rig, _B, w, mirror)
        legs.check("home_block_leaves_ws_seat", isinstance(page, dict) and page.get("my_state") == "left",
                   {"my_state": page.get("my_state") if isinstance(page, dict) else None, "refused": pref})
        unheard = f"{_TAG} to a blocker {uuid.uuid4().hex[:6]}"
        r, refused = await _send(rig, _A, n, unheard, conversation_id=host_conv)
        r = _posted(r)
        unheard_at = time.monotonic()
        legs.check("a_message_to_a_blocker_is_still_accepted_by_the_host",
                   not refused and isinstance(r, dict) and isinstance(r.get("seq"), int),
                   {"refused": refused, "answer": r})

        long_key = f"{'x' * 230}@{base[_A]}"     # over the 255 a block row stores, under the 320 an address may be
        r, refused = await _call(rig, _B, "blockChatPrincipal",
                                 {"ptype": "remote", "remote_key": long_key, "agent_jwt": w["jwt"]})
        legs.check("an_address_too_long_to_block_is_refused_by_name",
                   bool(refused) and "too long to block" in refused, {"refused": refused, "answer": r})

        await asyncio.sleep(max(0.0, max(hidden_at, unheard_at) + _HEAR_SEC - time.monotonic()))
        at_a = await _told(rig, _A, hook_a, "chat.message.received", host_conv, _body_is(hidden))
        legs.check("a_blocked_reply_reaches_no_n_owner", at_a == [],
                   {"deliveries": at_a, "note": "None = the record was unreadable, never silence"})
        at_b = await _told(rig, _B, hook_b, "chat.message.received", mirror, _body_is(unheard))
        legs.check("a_message_to_a_blocker_reaches_no_w_owner", at_b == [],
                   {"deliveries": at_b, "note": "None = the record was unreadable, never silence"})

    return await _run(rig, [
        "knock_hosted_by_the_sender", "knock_waits_in_the_recipients_requests", "an_explicit_accept_is_heard",
        "control_n_to_w_reaches_ws_owner", "control_w_to_n_reaches_ns_owner", "host_block_answers",
        "host_block_leaves_ns_seat", "a_blocked_reply_is_still_accepted_by_the_host",
        "a_blocked_reply_reaches_no_n_owner", "opening_a_dm_to_a_blocked_address_is_refused", "unblock_answers",
        "reopening_after_unblock_is_the_same_thread_active", "home_block_answers", "home_block_leaves_ws_seat",
        "a_message_to_a_blocker_is_still_accepted_by_the_host", "a_message_to_a_blocker_reaches_no_w_owner",
        "an_address_too_long_to_block_is_refused_by_name"],
        "G1: a block of a peer's principal is silent at the host and at the home", body)


# ─── FB12 + V0437 (3): the owner's join asks first, then shows ─────────────

@federation_test(
    name="chat_g1_owner_join_asks_consent_then_shows",
    category="chat_federation",
    budget_sec=240.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "g1", "cross_frame", "webhooks", "household"],
)
async def test_g1_household(rig: FederationTestRig) -> AssertionResult:
    """An agent's owner joins its cross-registry thread only visibly, and only when the owner says so.

    V0437 (3): the owner's first READ answers 409 `household_join_confirm:` and announces nothing; the same read with
    join=true seats the owner at the host with ONE visible system row "<owner> joined as the owner of <agent>", which
    the other owner hears (FB12). A second read writes no second join; the owner's post is relayed and heard. The same
    holds from the host's side: the knocker's owner reading the host thread is asked first, then shown to the other side.
    The owners are the frames' admin developers, the accounts the rig speaks as and the creators of every agent here.
    """
    async def body(legs: _Legs, made, hooks) -> None:
        base = await _frames(rig)
        n = await _agent(rig, _A, "n", made)
        w = await _agent(rig, _B, "w", made)
        n_key, w_key = _key(n["did"], base[_A]), _key(w["did"], base[_B])
        hook_a = await _hook(rig, _A, ["chat.message.received"], hooks)

        found = await _knock_and_find(rig, legs, n, w, w_key, n_key, base)
        if found is None:
            return
        host_conv, mirror = found
        r, refused = await _call(rig, _B, "respondChatRequest",
                                 {"conversation_id": mirror, "action": "accept", "agent_jwt": w["jwt"]})
        legs.check("thread_accepted", not refused and isinstance(r, dict), {"refused": refused, "answer": r})

        page, refused = await _read(rig, _B, None, mirror)
        legs.check("the_owners_first_read_asks_consent",
                   bool(refused) and "household_join_confirm:" in refused and "join=true" in refused,
                   {"refused": refused, "answered": None if refused else page})
        at_host, _ = await _read(rig, _A, n, host_conv)
        legs.check("an_unconfirmed_read_announces_nothing", _joins(at_host) == 0, {"joins_at_host": _joins(at_host)})

        page, refused = await _read(rig, _B, None, mirror, join=True)
        legs.check("a_confirmed_read_opens_the_thread",
                   not refused and isinstance(page, dict) and page.get("conversation_id") == mirror,
                   {"refused": refused})

        async def _host_joins():
            p, _ = await _read(rig, _A, n, host_conv)
            return _joins(p)
        one = await _until(_host_joins, _HEAR_SEC)
        legs.check("the_host_shows_one_join", one == 1, {"joins_at_host": one})
        await legs.heard("the_other_owner_hears_the_join",
                         lambda: _told(rig, _A, hook_a, "chat.message.received", host_conv, _body_has(_JOINED)), _HEAR_SEC)

        await _read(rig, _B, None, mirror, join=True)
        await _read(rig, _B, None, mirror)
        await asyncio.sleep(5.0)
        still = await _host_joins()
        legs.check("a_second_read_writes_no_second_join", still == 1, {"joins_at_host": still})

        post = f"{_TAG} the owner speaks {uuid.uuid4().hex[:6]}"
        r, refused = await _send(rig, _B, None, post, conversation_id=mirror)
        r = _posted(r)
        legs.check("the_owner_posts_through_the_host",
                   not refused and isinstance(r, dict) and r.get("relayed") is True, {"refused": refused, "answer": r})
        await legs.heard("the_other_owner_hears_the_owners_post",
                         lambda: _told(rig, _A, hook_a, "chat.message.received", host_conv, _body_is(post)), _HEAR_SEC)

        # From the host's side: N's owner is sandbox-A's admin.
        _, first = await _read(rig, _A, None, host_conv)
        _, confirmed = await _read(rig, _A, None, host_conv, join=True)
        legs.check("the_hosts_owner_is_asked_first_too",
                   bool(first) and "household_join_confirm:" in first and not confirmed,
                   {"first": first, "confirmed_refused": confirmed})

        async def _mirror_joins():
            p, _ = await _read(rig, _B, w, mirror)
            j = _joins(p)
            return j if (j or 0) >= 2 else None
        both = await _until(_mirror_joins, _HEAR_SEC)
        legs.check("the_hosts_owner_join_reaches_the_mirror", both == 2, {"joins_on_the_mirror": both})

        # V0441: with the host's owner now seated too, the mirror still names the agent the thread is with. ASIA's
        # production mirror named EU's owner (`dev:12@…`): the counterparty was the first row not mine, in no order.
        mp, mref = await _read(rig, _B, None, mirror)
        cp = (mp.get("counterparty") or {}) if isinstance(mp, dict) else {}
        legs.check("with_both_owners_seated_the_mirror_still_names_the_knocking_agent",
                   str(cp.get("remote_key") or "").lower() == n_key, {"counterparty": cp, "expected": n_key,
                                                                      "refused": mref})

    return await _run(rig, [
        "knock_hosted_by_the_sender", "knock_waits_in_the_recipients_requests", "thread_accepted",
        "the_owners_first_read_asks_consent", "an_unconfirmed_read_announces_nothing",
        "a_confirmed_read_opens_the_thread", "the_host_shows_one_join", "the_other_owner_hears_the_join",
        "a_second_read_writes_no_second_join", "the_owner_posts_through_the_host",
        "the_other_owner_hears_the_owners_post", "the_hosts_owner_is_asked_first_too",
        "the_hosts_owner_join_reaches_the_mirror", "with_both_owners_seated_the_mirror_still_names_the_knocking_agent"],
        "G1: an owner joins its agent's cross-registry thread only with consent, and visibly", body)


# ─── V0441: a developer on the host is ONE principal to its peers ──────────

async def _requests(rig, speaker: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
    """`speaker`'s Requests lane, or None when it could not be read (None is never an empty lane)."""
    r, refused = await _call(rig, speaker["label"], "listConversations", {"state": "requests", "agent_jwt": speaker["jwt"]})
    if refused or not isinstance(r, dict) or not isinstance(r.get("conversations"), list):
        return None
    return [c for c in r["conversations"] if isinstance(c, dict)]


@federation_test(
    name="chat_g1_a_developer_is_one_principal_to_a_peer",
    category="chat_federation",
    budget_sec=240.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["chat", "ourchat", "g1", "cross_frame", "blocks", "keys"],
)
async def test_g1_developer_one_key(rig: FederationTestRig) -> AssertionResult:
    """A block made with the address a developer's seat is listed under stops that developer's knock.

    V0441: a host listed its own developer's seat as `handle@host` (or `dev:<id>@host`) and sent that developer's
    messages as `<id>@host`, so a peer held one person as two principals. A peer agent that blocked the listed address
    was still knocked (its Requests lane took the thread), because the knock's first message carried the other key.
    Here sandbox-A's admin (a developer, no agent) knocks two fresh agents on sandbox-B: W2 blocks nobody (the control:
    the knock arrives, carrying the listed address), W blocks the listed address first (the knock must not arrive).
    """
    async def body(legs: _Legs, made, hooks) -> None:
        base = await _frames(rig)
        w = await _agent(rig, _B, "w", made)
        w2 = await _agent(rig, _B, "w2", made)
        w_key, w2_key = _key(w["did"], base[_B]), _key(w2["did"], base[_B])

        prof, pref = await _call(rig, _A, "getMyDeveloperProfile", {})
        code, hbody = await _rest(rig, "GET", "/api/v1/chat/handles/me", _ADMIN[_A])
        dev_id = prof.get("id") if isinstance(prof, dict) else None
        handle = hbody.get("handle") if code == 200 and isinstance(hbody, dict) else None
        if not legs.check("the_developers_seat_address_is_known", bool(dev_id) and code == 200,
                          {"profile_refused": pref, "handles_me": code, "has_handle": bool(handle)}):
            return
        seat = _key(str(handle) if handle else f"dev:{dev_id}", base[_A])

        r, refused = await _send(rig, _A, None, f"{_TAG} developer knock (control)", target_remote_key=w2_key)
        legs.check("control_the_developers_knock_is_hosted_at_home",
                   not refused and isinstance(r, dict) and r.get("federated") is True
                   and _origin(str(r.get("host") or "")) == base[_A], {"refused": refused, "answer": r})
        rows = await _until(lambda: _requests(rig, w2), _HEAR_SEC)
        legs.check("control_the_knock_reaches_an_agent_that_blocks_nobody", bool(rows) and len(rows) == 1,
                   {"requests": rows})
        cp_key = str((((rows or [{}])[0]).get("counterparty") or {}).get("remote_key") or "").lower()
        page, rref = (await _read(rig, _B, w2, rows[0]["id"])) if rows else (None, "no request to read")
        knock = next((m for m in (page.get("messages") or []) if isinstance(m, dict)), None) \
            if isinstance(page, dict) else None
        sent_as = str((knock or {}).get("sender_id") or "").lower()
        legs.check("the_knock_carries_the_address_the_seat_is_listed_under", sent_as == seat and cp_key == seat,
                   {"message_sender": sent_as, "counterparty": cp_key, "seat": seat, "read_refused": rref})

        r, refused = await _call(rig, _B, "blockChatPrincipal",
                                 {"ptype": "remote", "remote_key": seat, "agent_jwt": w["jwt"]})
        legs.check("the_block_of_the_seat_address_answers",
                   not refused and isinstance(r, dict) and r.get("blocked") is True, {"refused": refused, "answer": r})
        r, refused = await _send(rig, _A, None, f"{_TAG} developer knock (blocked)", target_remote_key=w_key)
        knocked_at = time.monotonic()
        legs.check("the_blocked_knock_is_still_hosted_at_home",
                   not refused and isinstance(r, dict) and r.get("federated") is True, {"refused": refused, "answer": r})
        await asyncio.sleep(max(0.0, knocked_at + _HEAR_SEC - time.monotonic()))
        lane = await _requests(rig, w)
        legs.check("a_block_of_the_seat_address_stops_the_developers_knock", lane == [],
                   {"requests": lane, "note": "None = the lane was unreadable, never silence"})

        r, refused = await _call(rig, _B, "unblockChatPrincipal",
                                 {"ptype": "remote", "remote_key": seat, "agent_jwt": w["jwt"]})
        legs.check("unblock_answers", not refused and isinstance(r, dict) and r.get("removed") is True,
                   {"refused": refused, "answer": r})

    return await _run(rig, [
        "the_developers_seat_address_is_known", "control_the_developers_knock_is_hosted_at_home",
        "control_the_knock_reaches_an_agent_that_blocks_nobody", "the_knock_carries_the_address_the_seat_is_listed_under",
        "the_block_of_the_seat_address_answers", "the_blocked_knock_is_still_hosted_at_home",
        "a_block_of_the_seat_address_stops_the_developers_knock", "unblock_answers"],
        "G1: a developer is one principal to a peer; a block of its listed address stops its knock", body)
