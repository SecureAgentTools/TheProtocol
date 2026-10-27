"""OurChat under federation (§FEDCHAT 2026-09-04).

The suite had NO chat coverage at all. These pin the OurChat design laws that
federation can actually break, and every one of them is written so it can FAIL:

  * the lane parameter is a validated, closed vocabulary — not decoration
  * threads are per-frame; a shared row across frames is the §ORGLEAK class
  * an unknown thread is REFUSED, never answered as an empty thread
    (an empty 200 is the blank-promise class: indistinguishable from "no
    messages yet", which is how a broken read stays invisible for months)
  * conversation_kind is a closed vocabulary
  * client_ref is an IDEMPOTENCY key — a replay must not create a second
    message. Chat carries no money, but `chat.py`'s sibling seed is an
    Idempotency-Key on /a2a-payment/buy where a replay IS a second charge,
    so the idempotency habit is load-bearing here.

House note: the existing suite's `_is_silent_or_error(...) -> return True`
habit makes a silent or errored response PASS. These tests deliberately do not
copy it — where a frame cannot supply the precondition they report NOT
MEASURED and FAIL, because a test that cannot fail measures nothing.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)

_MAINFRAMES = ("sandbox-A", "sandbox-B")

# Observed lanes + kinds. Keep in sync with routers/chat.py — a NEW legal value
# appearing here should be a deliberate edit, which is the point of pinning it.
_KNOWN_LANES = {"active", "requests"}
# `conversations.kind` is an unconstrained String(16) — there is no DB enum and
# no Literal on the read path, so NOTHING else in the stack pins this. Creation
# is restricted to Literal["dm","agent_service"] (routers/chat.py:100); the
# org / support / system kinds are written by the product's own internal paths.
# Derived from source + the live distinct set, not from memory: an earlier
# hand-written guess here missed "org", and this test is what caught it.
_KNOWN_KINDS = {"dm", "agent_service", "org", "support", "system"}


def _soft_error(r: Any) -> Optional[str]:
    """The bridge reports some refusals as a soft {'_text': 'Error: ... HTTP 404'}
    envelope and others by raising MCPError. Classify the soft form."""
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """Return (result, refusal_text). Never raises — an MCPError becomes a refusal."""
    try:
        r = await rig.mcp(label).call(tool, args)
    except Exception as e:                      # MCPError included
        return None, f"{type(e).__name__}: {e}"
    return r, _soft_error(r)


@federation_test(
    name="chat_lane_parameter_is_validated_and_echoed",
    category="chat_federation",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A", "sandbox-B"],
    tags=["chat", "ourchat", "contract"],
)
async def test_chat_lane_validated(rig: FederationTestRig) -> AssertionResult:
    """`state` is a real closed vocabulary on every frame, not a decorative arg.

    Both legal lanes must answer AND echo the lane they served; a bogus lane
    must be REFUSED. The refusal leg is required to fire — if validation were
    dropped the bogus call would 200 with the default lane and this test goes
    red, which is exactly what should happen.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        ok = True
        denials = 0
        for label in _MAINFRAMES:
            per: Dict[str, Any] = {}
            for lane in sorted(_KNOWN_LANES):
                r, refused = await _call(rig, label, "listConversations", {"state": lane})
                if refused or not isinstance(r, dict):
                    per[lane] = f"unexpected refusal: {refused}"
                    ok = False
                    continue
                echoed = r.get("state")
                per[lane] = {"echoed": echoed, "count": len(r.get("conversations") or [])}
                if echoed != lane:
                    ok = False
            r, refused = await _call(rig, label, "listConversations", {"state": "bogus-lane"})
            if refused:
                denials += 1
                per["bogus"] = "refused"
            else:
                per["bogus"] = f"ACCEPTED (should refuse): {str(r)[:120]}"
                ok = False
            state[label] = per
        state["denials"] = denials
        # A validation test with zero denials proved nothing.
        return ok and denials == len(_MAINFRAMES)

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="chat lane param validated + echoed on both frames, bogus lane refused",
        capture_state=lambda: state,
    )


@federation_test(
    name="chat_threads_do_not_leak_across_frames",
    category="chat_federation",
    budget_sec=20.0,
    severity="critical",
    requires=["sandbox-A", "sandbox-B"],
    tags=["chat", "ourchat", "isolation"],
)
async def test_chat_no_cross_frame_leak(rig: FederationTestRig) -> AssertionResult:
    """A conversation belongs to exactly one frame.

    Sovereign frames keep their own chat store; the same conversation id
    surfacing on both frames would be the §ORGLEAK class (a row outliving the
    relationship that authorised it). Disjointness is the assertion.

    ⚠ Two empty frames would make the sets trivially disjoint, so the test
    reports NOT MEASURED and FAILS unless at least one frame has a thread —
    `all()` over an empty population is the trap this guards against.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        ids: Dict[str, set] = {}
        for label in _MAINFRAMES:
            r, refused = await _call(rig, label, "listConversations", {"state": "active"})
            if refused or not isinstance(r, dict):
                state[label] = f"unreadable: {refused}"
                return False
            convs = r.get("conversations") or []
            ids[label] = {c.get("id") for c in convs if isinstance(c, dict) and c.get("id")}
            state[label] = {"count": len(ids[label])}
        total = sum(len(v) for v in ids.values())
        if total == 0:
            state["verdict"] = "NOT MEASURED — no thread on either frame; disjointness is vacuous"
            return False
        overlap = ids[_MAINFRAMES[0]] & ids[_MAINFRAMES[1]]
        state["overlap"] = sorted(overlap)[:5]
        state["measured_threads"] = total
        return not overlap

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="no conversation id is shared between sandbox-A and sandbox-B",
        capture_state=lambda: state,
    )


@federation_test(
    name="chat_unknown_thread_is_refused_not_empty",
    category="chat_federation",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A"],
    tags=["chat", "ourchat", "negative"],
)
async def test_chat_unknown_thread_refused(rig: FederationTestRig) -> AssertionResult:
    """readThread on an unknown id REFUSES; it must not answer an empty thread.

    "Not found" and "found but empty" are different facts. A surface that
    collapses them is unfalsifiable from outside — the caller cannot tell a
    broken read from a quiet one.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        bogus = str(uuid.uuid4())
        r, refused = await _call(rig, "sandbox-A", "readThread", {"conversation_id": bogus})
        state["probe_id"] = bogus
        state["refused"] = refused
        state["raw"] = None if refused else str(r)[:200]
        if not refused:
            return False
        return "404" in refused or "not_found" in refused.lower() or "not found" in refused.lower()

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="unknown conversation id is refused 404, not answered as an empty thread",
        capture_state=lambda: state,
    )


@federation_test(
    name="chat_conversation_kind_is_a_closed_vocabulary",
    category="chat_federation",
    budget_sec=25.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["chat", "ourchat", "vocabulary"],
)
async def test_chat_kind_closed_vocabulary(rig: FederationTestRig) -> AssertionResult:
    """Typed cards are a CLOSED vocabulary (OurChat design law).

    Two legs: a bogus `conversation_kind` on send must be refused, and every
    kind actually present on the frame must be one this suite knows about. The
    second leg is what catches a vocabulary that widened without anyone saying
    so.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        r, refused = await _call(rig, "sandbox-A", "sendChatMessage", {
            "body": "federation-suite closed-vocabulary probe",
            "target_developer_id": 1,
            "conversation_kind": "bogus-kind",
            "client_ref": str(uuid.uuid4()),
        })
        state["bogus_kind_refused"] = refused
        if not refused:
            state["verdict"] = "bogus conversation_kind ACCEPTED"
            return False

        seen: set = set()
        for lane in sorted(_KNOWN_LANES):
            rr, ref2 = await _call(rig, "sandbox-A", "listConversations", {"state": lane})
            if ref2 or not isinstance(rr, dict):
                continue
            for c in rr.get("conversations") or []:
                if isinstance(c, dict) and c.get("kind"):
                    seen.add(c["kind"])
        state["kinds_seen"] = sorted(seen)
        unknown = seen - _KNOWN_KINDS
        state["unknown_kinds"] = sorted(unknown)
        return not unknown

    return await rig.assert_within(
        budget_sec=25.0, predicate=predicate,
        description="bogus conversation_kind refused and every live kind is in the known set",
        capture_state=lambda: state,
    )


@federation_test(
    name="chat_client_ref_is_idempotent",
    category="chat_federation",
    budget_sec=40.0,
    severity="critical",
    requires=["sandbox-A"],
    tags=["chat", "ourchat", "idempotency"],
)
async def test_chat_client_ref_idempotent(rig: FederationTestRig) -> AssertionResult:
    """The same client_ref replayed must NOT create a second message.

    `sendChatMessage` documents itself as "Idempotent on client_ref". This
    drives the replay for real: send, capture the thread's sequence, send the
    byte-identical call again, and require the sequence NOT to advance. A
    duplicate here is harmless; the identical habit one module over is an
    Idempotency-Key on /a2a-payment/buy, where a replay is a second charge.

    ⚠ Writes: leaves one thread on sandbox-A tagged 'federation-suite
    idempotency probe'. There is no delete-thread rail, so this is deliberate,
    identifiable litter rather than a swept fixture.
    """
    state: Dict[str, Any] = {}

    async def predicate():
        # A stranger DID gives us a fresh pair thread rather than mutating an
        # existing fixture thread that other tests read.
        d, refused = await _call(rig, "sandbox-A", "discoverAgents", {"limit": 5})
        if refused:
            state["verdict"] = f"NOT MEASURED — discoverAgents refused: {refused}"
            return False
        agents = (d.get("agents") or d.get("items") or []) if isinstance(d, dict) else (d or [])
        dids = [a.get("did") or a.get("agent_did") for a in agents
                if isinstance(a, dict) and (a.get("did") or a.get("agent_did"))]
        if not dids:
            state["verdict"] = "NOT MEASURED — no agent DID discoverable to address"
            return False
        target = dids[0]
        ref = f"fedsuite-idem-{uuid.uuid4()}"
        body = "federation-suite idempotency probe"
        state["target"] = target
        state["client_ref"] = ref

        first, ref1 = await _call(rig, "sandbox-A", "sendChatMessage", {
            "body": body, "target_agent_did": target, "client_ref": ref})
        if ref1 or not isinstance(first, dict):
            state["verdict"] = f"NOT MEASURED — first send refused: {ref1}"
            return False
        conv = first.get("conversation_id") or first.get("id")
        seq1 = first.get("seq") or first.get("last_seq")
        state["first"] = {"conversation_id": conv, "seq": seq1}
        if not conv:
            state["verdict"] = "NOT MEASURED — first send returned no conversation id"
            return False

        second, ref2 = await _call(rig, "sandbox-A", "sendChatMessage", {
            "body": body, "target_agent_did": target, "client_ref": ref})
        if ref2 or not isinstance(second, dict):
            state["verdict"] = f"replay refused rather than de-duplicated: {ref2}"
            return False
        conv2 = second.get("conversation_id") or second.get("id")
        seq2 = second.get("seq") or second.get("last_seq")
        state["second"] = {"conversation_id": conv2, "seq": seq2}

        same_thread = conv2 == conv
        # Idempotent replay: same thread, and the sequence did not advance.
        not_advanced = (seq1 is None or seq2 is None) or (seq2 == seq1)
        state["verdict"] = {"same_thread": same_thread, "seq_unchanged": not_advanced}
        return bool(same_thread and not_advanced)

    return await rig.assert_within(
        budget_sec=40.0, predicate=predicate, poll_interval_sec=2.0,
        description="replayed client_ref returns the same thread and does not add a message",
        capture_state=lambda: state,
    )
