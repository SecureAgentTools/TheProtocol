"""§FEDLICENCE (2026-09-28): the signed federation licence, measured across the pair.

agentvault2-a4's four pins, plus agentvault2-41's review item 5. Read-only against both frames, except ONE refusal
probe per frame, which must write nothing and is checked to have written nothing. Every JWS is verified here with an
independent Ed25519 check (the cryptography library over the compact form's own signing input), never with the
product's own verifier, so a verifier bug cannot mark itself green; and every check that verifies also carries a
control that must fail.

 1. the genesis's signed list verifies under the key its root certificate names, and a one-character change does not;
 2. the public lookup refuses an unknown hash with its OWN 404 and a malformed one with 422, and answers a listed hash
    with the list's own state;
 3. POST /api/v1/admin/federation/licence/issue refuses a frame licence the frame cannot grant (a non-genesis: any;
    the genesis: one naming its own trust domain), and the refusal writes nothing: no licence key appears, nothing is
    issued;
 4. the card declares the three licence leaves in signature.signed_canonical, and its licence block agrees with the
    frame's own /.well-known/federation-licence.json;
 5. a frame's public envelope for a peer (/api/v1/public/registry-card?peer=) carries THIS frame's verdict, the same one
    its admin status route reports for that peer.

A frame whose image predates the licence routes answers FastAPI's own "Not Found": that is NOT MEASURED, never red. The
route's own 404 is told apart from it by its sentence, never by its status.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    AssertionResult, FederationTestRig, PreconditionUnmet,
)

FRAMES = ("sandbox-A-admin", "sandbox-B-admin")
LICENCE_LEAVES = ("federation.licence.state", "federation.licence.hash", "federation.licence.operator.hash")
CATEGORY = "federation_licence_certificates"


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────────

async def _rest(rig: FederationTestRig, method: str, endpoint: str, label: str,
                body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
    """One call through adminRequest -> (status_code, response body); the status is kept apart from the body because
    a refusal is as much the subject here as a 200."""
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if params is not None:
        args["params"] = params
    try:
        r = await rig.mcp(label).call("adminRequest", args, timeout=60)
    except Exception as e:  # noqa: BLE001 — the row records the failure
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


def _detail(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("detail") or "")
    return str(body or "")


def _route_missing(code: int, body: Any) -> bool:
    """FastAPI's own 404 for a path no route serves (an image without the licence routes)."""
    return code == 404 and _detail(body).strip() == "Not Found"


def _b64u_dec(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _jws_payload(jws: str) -> Dict[str, Any]:
    return json.loads(_b64u_dec(jws.split(".")[1]))


def _eddsa_verifies(jws: str, jwk: Dict[str, Any]) -> bool:
    """Independent: Ed25519 over the compact form's own signing input, under the JWK's raw public key."""
    try:
        h, p, s = jws.split(".")
        if json.loads(_b64u_dec(h)).get("alg") != "EdDSA":
            return False
        if not isinstance(jwk, dict) or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
            return False
        Ed25519PublicKey.from_public_bytes(_b64u_dec(str(jwk["x"]))).verify(_b64u_dec(s), (h + "." + p).encode("ascii"))
        return True
    except (InvalidSignature, ValueError, KeyError, TypeError, AttributeError):
        return False


def _tampered(jws: str) -> str:
    """The same JWS with one character of its payload segment changed (still valid base64url)."""
    h, p, s = jws.split(".")
    i = len(p) // 2
    return h + "." + p[:i] + ("A" if p[i] != "A" else "B") + p[i + 1:] + "." + s


async def _own_licence(rig: FederationTestRig, label: str) -> Dict[str, Any]:
    code, body = await _rest(rig, "GET", "/.well-known/federation-licence.json", label)
    if _route_missing(code, body):
        raise PreconditionUnmet(f"{label} serves no /.well-known/federation-licence.json: its image predates §FEDLICENCE")
    if code != 200 or not isinstance(body, dict):
        raise AssertionError(f"{label}'s own licence answered {code}: {str(body)[:200]}")
    return body


async def _status(rig: FederationTestRig, label: str) -> Dict[str, Any]:
    code, body = await _rest(rig, "GET", "/api/v1/admin/federation/licence/status", label)
    if _route_missing(code, body):
        raise PreconditionUnmet(f"{label} serves no licence status route: its image predates §FEDLICENCE")
    if code != 200 or not isinstance(body, dict):
        raise AssertionError(f"{label}'s licence status answered {code}: {str(body)[:200]}")
    return body


async def _issued_count(rig: FederationTestRig, label: str) -> int:
    code, body = await _rest(rig, "GET", "/api/v1/admin/federation/licence/issued", label)
    if code != 200 or not isinstance(body, dict) or not isinstance(body.get("count"), int):
        raise AssertionError(f"{label}'s issued list answered {code}: {str(body)[:200]}")
    return body["count"]


async def _genesis(rig: FederationTestRig) -> Tuple[str, Dict[str, Any]]:
    """(label, own licence) of the frame holding the network's root, or NOT MEASURED when neither does."""
    seen: Dict[str, Any] = {}
    for label in FRAMES:
        own = await _own_licence(rig, label)
        seen[label] = own.get("state")
        if own.get("state") == "genesis" and own.get("certificate"):
            return label, own
    raise PreconditionUnmet(f"no frame of the pair holds the network's genesis certificate (states {seen}): the "
                            "genesis ceremony has not run on this pair")


# ── pin 1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@federation_test(
    name="fedlicence_genesis_list_verifies_under_its_root_key",
    category=CATEGORY, budget_sec=30.0, severity="high",
    requires=list(FRAMES), tags=["fedlicence", "federation", "signature"],
)
async def test_genesis_list_verifies_under_its_root_key(rig: FederationTestRig) -> AssertionResult:
    """The list every peer reads for revocations verifies, independently, under the key the root certificate names;
    the root certificate is signed by that same key; the list names the genesis as its issuer; the unsigned copy the
    route repeats for humans is the signed payload; and a one-character change to the list does NOT verify."""
    label, own = await _genesis(rig)
    state: Dict[str, Any] = {"genesis": label, "root": str(own.get("hash") or "")[:16]}
    root = str(own.get("certificate") or "")
    key = _jws_payload(root).get("key") or {}

    async def predicate() -> bool:
        state["root_self_signed"] = _eddsa_verifies(root, key)
        code, body = await _rest(rig, "GET", "/.well-known/federation-licences.json", label)
        jws = str((body or {}).get("jws") or "") if isinstance(body, dict) else ""
        state["list_http"] = code
        state["list_len"] = len(jws)
        if code != 200 or not jws:
            state["list"] = str(body)[:200]
            return False
        payload = _jws_payload(jws)
        state["list_verifies"] = _eddsa_verifies(jws, key)
        state["control_tampered_refused"] = not _eddsa_verifies(_tampered(jws), key)
        state["issuer_is_the_genesis"] = (payload.get("issuer") or {}).get("trust_domain") == own.get("trust_domain")
        state["human_copy_is_the_signed_payload"] = body.get("payload") == payload
        state["count_matches"] = body.get("count") == len(payload.get("licences") or [])
        return all(state[k] for k in ("root_self_signed", "list_verifies", "control_tampered_refused",
                                      "issuer_is_the_genesis", "human_copy_is_the_signed_payload", "count_matches"))

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=3.0,
        description="the genesis's list verifies under its root key, and a changed list does not",
        capture_state=lambda: state,
    )


# ── pin 2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@federation_test(
    name="fedlicence_public_lookup_refuses_an_unknown_hash",
    category=CATEGORY, budget_sec=30.0, severity="medium",
    requires=list(FRAMES), tags=["fedlicence", "federation", "public"],
)
async def test_public_lookup_refuses_an_unknown_hash(rig: FederationTestRig) -> AssertionResult:
    """GET /api/v1/public/federation/licences/{hash}: the route's OWN 404 for a hash nobody issued, 422 for a malformed
    one, and for a hash the genesis lists, 200 with the list's state and a certificate whose sha256 IS that hash."""
    for label in FRAMES:
        await _own_licence(rig, label)            # an image without the routes is NOT MEASURED, before any poll
    state: Dict[str, Any] = {}

    async def predicate() -> bool:
        ok = True
        for label in FRAMES:
            h = secrets.token_hex(32)
            code, body = await _rest(rig, "GET", f"/api/v1/public/federation/licences/{h}", label)
            code_bad, _b = await _rest(rig, "GET", f"/api/v1/public/federation/licences/{h[:-1]}", label)
            own_404 = code == 404 and "no licence with that hash" in _detail(body)
            state[label] = {"unknown": [code, _detail(body)[:80]], "malformed": code_bad}
            ok = ok and own_404 and code_bad == 422
        try:
            glabel, _own = await _genesis(rig)
        except PreconditionUnmet as e:
            state["listed"] = f"not measured: {e}"
            return ok
        code, body = await _rest(rig, "GET", "/.well-known/federation-licences.json", glabel)
        items: List[Dict[str, Any]] = (((body or {}).get("payload") or {}).get("licences") or []) \
            if isinstance(body, dict) else []
        if not items:
            state["listed"] = "not measured: the genesis has issued nothing yet"
            return ok
        first = items[0]
        code3, body3 = await _rest(rig, "GET", f"/api/v1/public/federation/licences/{first.get('hash')}", glabel)
        cert = str((body3 or {}).get("certificate") or "") if isinstance(body3, dict) else ""
        state["listed"] = {"http": code3, "state": (body3 or {}).get("state") if isinstance(body3, dict) else None,
                           "list_state": first.get("state")}
        return (ok and code3 == 200 and isinstance(body3, dict) and body3.get("state") == first.get("state")
                and hashlib.sha256(cert.strip().encode("ascii", "replace")).hexdigest() == first.get("hash"))

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=3.0,
        description="the public lookup: its own 404 for an unknown hash, 422 for a malformed one, the list's state "
                    "for a listed one",
        capture_state=lambda: state,
    )


# ── pin 3 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@federation_test(
    name="fedlicence_issue_refuses_a_frame_licence_it_cannot_grant",
    category=CATEGORY, budget_sec=45.0, severity="high",
    requires=list(FRAMES), tags=["fedlicence", "federation", "refusal", "admin"],
)
async def test_issue_refuses_a_frame_licence_it_cannot_grant(rig: FederationTestRig) -> AssertionResult:
    """Only the genesis issues frame licences, and never one for its own trust domain. On each frame the probe that
    must be refused is sent ONCE, and the refusal must write nothing: the frame's licence key (none, or the same one)
    and its issued count are read before and after."""
    plans: Dict[str, Dict[str, Any]] = {}
    for label in FRAMES:
        st = await _status(rig, label)
        local = str(st.get("local_trust_domain") or "")
        is_genesis = bool(st.get("genesis_trust_domain")) and st.get("genesis_trust_domain") == local \
            and st.get("root") is not None
        plans[label] = {
            "genesis": is_genesis,
            "body": {"type": "frame", "name": "fedlicence refusal probe (must be refused)",
                     "trust_domain": local if is_genesis else "refusal-probe.invalid"},
            "expect": ("names another trust domain" if is_genesis else "only the network's genesis issues frame licences"),
            "key_before": (st.get("self") or {}).get("key"),
            "issued_before": await _issued_count(rig, label),
        }
    state: Dict[str, Any] = {}
    for label, plan in plans.items():            # ONE probe per frame, never retried: it is the act under test
        code, body = await _rest(rig, "POST", "/api/v1/admin/federation/licence/issue", label, body=plan["body"])
        state[label] = {"genesis": plan["genesis"], "http": code, "detail": _detail(body)[:160]}

    async def predicate() -> bool:
        ok = True
        for label, plan in plans.items():
            st = await _status(rig, label)
            key_after = (st.get("self") or {}).get("key")
            issued_after = await _issued_count(rig, label)
            row = state[label]
            row["refused_with_its_sentence"] = row["http"] == 422 and plan["expect"] in row["detail"]
            row["key_unchanged"] = key_after == plan["key_before"]
            row["issued_unchanged"] = issued_after == plan["issued_before"]
            ok = ok and row["refused_with_its_sentence"] and row["key_unchanged"] and row["issued_unchanged"]
        return ok

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=3.0,
        description="a frame licence the frame cannot grant is refused with its sentence, and nothing is written",
        capture_state=lambda: state,
    )


# ── pin 4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

@federation_test(
    name="fedlicence_card_signs_its_licence_leaves",
    category=CATEGORY, budget_sec=30.0, severity="medium",
    requires=list(FRAMES), tags=["fedlicence", "federation", "registry-card"],
)
async def test_card_signs_its_licence_leaves(rig: FederationTestRig) -> AssertionResult:
    """The card declares federation.licence.{state,hash,operator.hash} among its signed paths, so editing them breaks
    its signature; and where the card carries the block, its state and hash are the frame's own licence endpoint's."""
    for label in FRAMES:
        await _own_licence(rig, label)
    state: Dict[str, Any] = {}

    async def predicate() -> bool:
        ok = True
        for label in FRAMES:
            code, card = await _rest(rig, "GET", "/.well-known/registry-card.json", label)
            if code != 200 or not isinstance(card, dict):
                state[label] = f"card {code}"
                ok = False
                continue
            declared = set((card.get("signature") or {}).get("signed_canonical") or [])
            missing = [p for p in LICENCE_LEAVES if p not in declared]
            block = (card.get("federation") or {}).get("licence")
            row: Dict[str, Any] = {"missing_leaves": missing}
            if isinstance(block, dict):
                own = await _own_licence(rig, label)
                row["card"] = [block.get("state"), str(block.get("hash") or "")[:16]]
                row["own"] = [own.get("state"), str(own.get("hash") or "")[:16]]
                row["agree"] = block.get("state") == own.get("state") and block.get("hash") == own.get("hash")
            else:
                row["agree"] = True
                row["card"] = "no licence block (no network configured and nothing held)"
            state[label] = row
            ok = ok and not missing and row["agree"]
        return ok

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=3.0,
        description="the card signs its licence leaves and its block agrees with the licence endpoint",
        capture_state=lambda: state,
    )


# ── review item 5 ────────────────────────────────────────────────────────────────────────────────────────────────────

@federation_test(
    name="fedlicence_peer_envelope_carries_our_verdict",
    category=CATEGORY, budget_sec=30.0, severity="medium",
    requires=list(FRAMES), tags=["fedlicence", "federation", "registry-card", "peer-view"],
)
async def test_peer_envelope_carries_our_verdict(rig: FederationTestRig) -> AssertionResult:
    """Two views of one fact: a frame's public envelope for its peer (/api/v1/public/registry-card?peer=) carries the
    verdict its admin status route reports for that peer (state, reason, checked_at), never the card's own claim."""
    own = {label: await _own_licence(rig, label) for label in FRAMES}
    names: Dict[Tuple[str, str], str] = {}
    for viewer, subject in ((FRAMES[0], FRAMES[1]), (FRAMES[1], FRAMES[0])):
        td = str(own[subject].get("trust_domain") or "")
        row = next((p for p in (await _status(rig, viewer)).get("peers") or []
                    if str(p.get("trust_domain") or "") == td and str(p.get("peer_type") or "").lower() == "frame"), None)
        if row is None:
            raise PreconditionUnmet(f"{viewer} holds no ACTIVE frame row for {subject} ({td})")
        names[(viewer, subject)] = str(row.get("name"))
    state: Dict[str, Any] = {}

    async def predicate() -> bool:
        ok = True
        for (viewer, subject), name in names.items():
            peers = (await _status(rig, viewer)).get("peers") or []
            row = next((p for p in peers if str(p.get("name")) == name), None) or {}
            code, env = await _rest(rig, "GET", "/api/v1/public/registry-card", viewer, params={"peer": name})
            got = {k: (env or {}).get(k, "<absent>") if isinstance(env, dict) else "<no body>"
                   for k in ("licence_state", "licence_reason", "licence_checked_at")}
            want = {"licence_state": row.get("licence_state"), "licence_reason": row.get("licence_reason"),
                    "licence_checked_at": row.get("licence_checked_at")}
            state[f"{viewer}->{subject}"] = {"http": code, "envelope": got, "status_route": want}
            ok = ok and code == 200 and got == want
        return ok

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=3.0,
        description="the peer envelope carries this frame's verdict, the one its status route reports",
        capture_state=lambda: state,
    )


# ── the list reaches the peers (agentvault2-41, after the 38-entry cap measured on 21f51c99) ─────────────────────────

# the reasons evaluate() gives when it has no usable list: the verdict then falls to `unverified`, which enforce allows
_NO_LIST_REASONS = ("no verified licence list", "licence list from", "list does not name this certificate")


@federation_test(
    name="fedlicence_peer_accepts_the_genesis_list",
    category=CATEGORY, budget_sec=30.0, severity="high",
    requires=list(FRAMES), tags=["fedlicence", "federation", "revocation"],
)
async def test_peer_accepts_the_genesis_list(rig: FederationTestRig) -> AssertionResult:
    """The frame that is NOT the genesis reads its own network licence against the genesis's list every sync cycle.
    Its stored verdict (served from the database, so any worker answers the same) must come FROM that list: licensed,
    revoked, suspended or expired. `unverified` with a reason naming a missing, stale or silent list is exactly the
    state a refused list produces (21f51c99 refused every list past 38 entries), and enforce lets it through."""
    glabel, _g = await _genesis(rig)
    other = next(label for label in FRAMES if label != glabel)
    own = await _own_licence(rig, other)
    if own.get("state") in (None, "unlicensed") or not own.get("certificate"):
        raise PreconditionUnmet(f"{other} holds no network licence yet (state {own.get('state')!r}): nothing reads "
                                "the genesis's list on its behalf")
    state: Dict[str, Any] = {"genesis": glabel, "reader": other}

    async def predicate() -> bool:
        o = await _own_licence(rig, other)
        reason = str(o.get("reason") or "")
        state.update(state_=o.get("state"), reason=reason[:200], checked_at=o.get("checked_at"))
        from_the_list = o.get("state") in ("licensed", "revoked", "suspended", "expired")
        no_list = o.get("state") == "unverified" and any(r in reason for r in _NO_LIST_REASONS)
        state["verdict_from_the_list"] = from_the_list
        state["no_usable_list"] = no_list
        return from_the_list and not no_list

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate, poll_interval_sec=3.0,
        description="the non-genesis frame's own verdict comes from the genesis's list",
        capture_state=lambda: state,
    )
