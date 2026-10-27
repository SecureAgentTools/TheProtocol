"""§MCPTEST30 (V0612) — zero-knowledge attestations v2 through the MCP tools (agentvault2-90's §ZKV2).

His word in agentvault2-90's session: the tester tests the v2 circuits. Every step here goes through a tool an agent or
an operator uses. The circuit reads are public; the proof is made by the registry's own prover (generateTutorialProof,
admin bridge) for a THROWAWAY agent made for this run, and that agent submits it (submitAttestation). A fresh agent
makes every count exact: its first proof of a circuit on a UTC day earns one point, a second earns nothing, and the
governance preview counts its circuit-days from 0. The rows (`zk v2: ...`):

- the catalog: the four v2.0.0 circuits active, with bytecode, a key and metadata; their v1.0.0 ids retired, each
  superseded by its v2.0.0 circuit;
- the keys: each v2.0.0 key's sha256, as served, is the one its metadata names (Artifacts.verification_key_sha256);
- a retired v1.0.0 circuit serves no key (404 naming its successor);
- the proof is bound to the agent it was made for: its reference (context) is derive_reference(that DID, its
  reference_label), derived here independently (api_tests/zkp_v2_helpers), never with the product's own function;
- submitted by that agent it verifies, carries the values it was made for and earns one reputation point;
- the same proof again is refused (409); without reference_label it is refused (422); submitted by another agent (the
  run's sentinel) it fails; with one element raised by the field order it fails (non-canonical); under its retired
  v1.0.0 id it fails as retired; proof_of_reputation (Option B) answers, and is never verified;
- a second proof of the circuit the same UTC day verifies and earns nothing, and the governance preview counts the two
  as one circuit-day;
- a stored attestation verifies again; revoked, it leaves the governance count and fails re-verification.

The throwaway revokes what it verified and is deleted. Rows keep ids, statuses, counts and reasons, never proof bytes
or a credential. Sandbox targets only: the governance preview answers 403 elsewhere, and that row then says so.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.zkp_v2_helpers import (
    FAIR_MARKUP,
    OPTION_B,
    REFERENCE_INPUT,
    V1_CIRCUITS,
    V2_CIRCUITS,
    carried_matches,
    derive_reference,
    offset_element,
)

PREFIX = "zk v2: "
ROW_CATALOG = PREFIX + "the catalog lists the four v2.0.0 circuits active and their v1.0.0 ids retired"
ROW_KEYS = PREFIX + "each v2.0.0 circuit serves the verification key its metadata names"
ROW_V1_NO_KEY = PREFIX + "a retired v1.0.0 circuit serves no verification key"
ROW_PROOF = PREFIX + "generateTutorialProof proves for the agent it names"
ROW_VERIFIED = PREFIX + "an agent's first proof of a circuit verifies and earns one reputation point"
ROW_REPLAY = PREFIX + "the same proof submitted again is refused (409)"
ROW_NO_LABEL = PREFIX + "a submission without reference_label is refused (422)"
ROW_OTHER_AGENT = PREFIX + "a proof made for one agent fails when another agent submits it"
ROW_OFFSET = PREFIX + "a proof element raised by the field order is refused"
ROW_V1_RETIRED = PREFIX + "a v1.0.0 submission is refused as retired"
ROW_OPTION_B = PREFIX + "proof_of_reputation (Option B) is never a verified proof"
ROW_SAME_DAY = PREFIX + "a second proof of the circuit the same UTC day verifies and earns nothing"
ROW_GOV_DAYS = PREFIX + "the governance preview counts circuit-days, not attestations"
ROW_REVERIFY = PREFIX + "a stored attestation verifies again"
ROW_REVOKE = PREFIX + "a revoked attestation leaves the governance count and fails re-verification"

READ_ROWS = (ROW_CATALOG, ROW_KEYS, ROW_V1_NO_KEY)
PROOF_ROWS = (ROW_PROOF, ROW_VERIFIED, ROW_REPLAY, ROW_NO_LABEL, ROW_OTHER_AGENT, ROW_OFFSET, ROW_V1_RETIRED,
              ROW_OPTION_B, ROW_SAME_DAY, ROW_GOV_DAYS, ROW_REVERIFY, ROW_REVOKE)
ROWS = READ_ROWS + PROOF_ROWS

PROOF_TIMEOUT_S = 90     # the tool's own call to its route is bounded at 30 s; proving takes about a second
SUBMIT_TIMEOUT_S = 60


def _v1_of(v2_id: str) -> str:
    return v2_id.replace("/v2.0.0", "/v1.0.0")


def refusal_text(inner: Any) -> str:
    """The whole text a refused tool call answered with, for matching a rule's words (never stored in a row)."""
    if isinstance(inner, dict):
        t = inner.get("_text")
        if isinstance(t, str):
            return t
        if isinstance(inner.get("error"), str):
            return inner["error"]
    return ""


def catalog_fail(items: Any) -> Optional[str]:
    """None when the catalog lists every v2.0.0 circuit active (bytecode, key, metadata) and every v1.0.0 id retired
    and superseded by its v2.0.0 circuit; otherwise what is wrong."""
    if not isinstance(items, list):
        return "the catalog answered without a circuits list"
    by_id = {c.get("circuit_id"): c for c in items if isinstance(c, dict)}
    wrong: List[str] = []
    for cid in V2_CIRCUITS:
        c = by_id.get(cid)
        if c is None:
            wrong.append(f"{cid} is not listed")
        elif c.get("status") != "active":
            wrong.append(f"{cid} is {c.get('status')!r}, not active")
        elif not (c.get("acir_available") is True and c.get("vk_url") and c.get("metadata_url")):
            wrong.append(f"{cid} lacks bytecode, a key url or a metadata url")
    for cid in V1_CIRCUITS:
        c = by_id.get(cid)
        if c is None:
            wrong.append(f"{cid} is not listed")
        elif c.get("status") != "retired" or c.get("superseded_by") != cid.replace("/v1.0.0", "/v2.0.0"):
            wrong.append(f"{cid} is {c.get('status')!r} superseded by {c.get('superseded_by')!r}")
        elif c.get("vk_url"):
            wrong.append(f"{cid} is retired but still lists a key url")
    return "; ".join(wrong) or None


def key_fail(cid: str, vk: Any, meta: Any) -> Optional[str]:
    """None when the key served for `cid` hashes to the sha256 the tool names and to the one its metadata names, and
    the metadata states the policy in force; otherwise what is wrong."""
    vk = vk if isinstance(vk, dict) else {}
    md = (meta.get("metadata") if isinstance(meta, dict) else None) or {}
    try:
        raw = base64.b64decode(vk.get("verification_key_b64") or "")
    except Exception:  # noqa: BLE001
        raw = b""
    if not raw:
        return f"{cid}: the key came back empty"
    served = hashlib.sha256(raw).hexdigest()
    if vk.get("sha256") != served:
        return f"{cid}: the tool's sha256 is not the sha256 of the key it returned"
    named = (md.get("Artifacts") or {}).get("verification_key_sha256")
    if named != served:
        return f"{cid}: the key served hashes to {served[:16]}..., its metadata names {str(named)[:16]}..."
    if not isinstance(md.get("policy_in_force"), dict):
        return f"{cid}: the metadata states no policy_in_force"
    return None


def proof_bound_fail(proof: Any, agent_did: str, circuit_id: str = FAIR_MARKUP) -> Optional[str]:
    """None when generateTutorialProof's answer is a proof for `agent_did`: proof bytes, the circuit, public outputs,
    and a reference that is derive_reference(agent_did, reference_label); otherwise what is wrong."""
    proof = proof if isinstance(proof, dict) else {}
    inputs = proof.get("public_inputs") if isinstance(proof.get("public_inputs"), dict) else {}
    ref_name = REFERENCE_INPUT[circuit_id]
    label = inputs.get("reference_label")
    if proof.get("circuit_id") != circuit_id:
        return f"the answer names circuit {proof.get('circuit_id')!r}, not {circuit_id}"
    if not proof.get("proof_bytes_base64"):
        return "the answer carries no proof bytes"
    if not isinstance(proof.get("public_outputs"), dict):
        return "the answer carries no public outputs"
    if not isinstance(label, str) or not label:
        return "the answer's public inputs carry no reference_label"
    try:
        ref = int(str(inputs.get(ref_name)), 0)
    except (TypeError, ValueError):
        return f"the answer's {ref_name} is not a number"
    if ref != derive_reference(agent_did, label):
        return (f"the proof's {ref_name} is not derive_reference(the named agent's DID, its reference_label): it was "
                "made for another agent")
    return None


def submission(circuit_id: str, proof_b64: str, public_inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"circuit_id": circuit_id, "proof_data": {"proof_bytes": proof_b64, "format": "ultra_honk"},
            "public_inputs": dict(public_inputs)}


def _same_value(a: Any, b: Any) -> bool:
    """One public input in two spellings (a decimal string, an integer, a 0x form) is one value."""
    try:
        return int(str(a), 0) == int(str(b), 0)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _inputs_fail(stored: Any, inputs: Dict[str, Any]) -> Optional[str]:
    stored = stored if isinstance(stored, dict) else {}
    wrong = [k for k, v in inputs.items() if k not in stored or not _same_value(stored[k], v)]
    return f"its public inputs do not carry {', '.join(sorted(wrong))} as stated" if wrong else None


def _proof_sha256(proof_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(proof_b64)).hexdigest()


def record_fail(rec: Any, att_id: str, did: str, proof_b64: str, inputs: Dict[str, Any]) -> Optional[str]:
    """None when getAttestationDetail's record is the attestation the run just verified: its id and prover, the circuit
    proved, verified and not revoked, the sha256 of the proof bytes sent, and every public input as stated."""
    rec = rec if isinstance(rec, dict) else {}
    name, _, version = FAIR_MARKUP.partition("/")
    if str(rec.get("id")) != str(att_id):
        return f"the record is of attestation {rec.get('id')!r}, not {att_id}"
    if rec.get("agent_did") != did:
        return "the record names another agent than the prover"
    if not str(rec.get("circuit_id") or "").startswith(name) or rec.get("circuit_version") != version:
        return f"the record reads circuit {rec.get('circuit_id')!r} {rec.get('circuit_version')!r}, not {FAIR_MARKUP}"
    if rec.get("verified") is not True or rec.get("revoked_at"):
        return f"the record reads verified={rec.get('verified')!r} revoked_at={rec.get('revoked_at')!r}"
    if rec.get("proof_hash") != _proof_sha256(proof_b64):
        return "the record's proof_hash is not the sha256 of the proof bytes sent"
    return _inputs_fail(rec.get("public_inputs"), inputs)


def bundle_fail(bundle: Any, att_id: str, did: str, proof_b64: str, inputs: Dict[str, Any]) -> Optional[str]:
    """None when getAttestationBundle exports the attestation the run just verified: the proof bytes it sent (and their
    sha256), every public input as stated, verified and not revoked."""
    b = bundle if isinstance(bundle, dict) else {}
    if str(b.get("attestation_id")) != str(att_id) or b.get("agent_did") != did:
        return f"the bundle is of attestation {b.get('attestation_id')!r}, not the prover's {att_id}"
    if b.get("verified") is not True or b.get("revoked") is not False:
        return f"the bundle reads verified={b.get('verified')!r} revoked={b.get('revoked')!r}"
    if b.get("proof_b64") != proof_b64:
        return "the bundle does not carry the proof bytes sent"
    if b.get("proof_hash") != _proof_sha256(proof_b64):
        return "the bundle's proof_hash is not the sha256 of the proof bytes sent"
    return _inputs_fail(b.get("public_inputs"), inputs)


def failed_for(resp: Any, words: str) -> Optional[str]:
    """None when a submission came back status failed for the rule named by `words`; otherwise what came back."""
    resp = resp if isinstance(resp, dict) else {}
    why = f"{resp.get('reason') or ''} {resp.get('message') or ''}"
    if resp.get("status") == "verified":
        return "it VERIFIED"
    if resp.get("status") != "failed":
        return f"it answered status {resp.get('status')!r}"
    if words.lower() not in why.lower():
        return f"it failed, but not for this rule (wanted '{words}'): {why.strip()[:160]}"
    return None


def same_day_fail(resp: Any) -> Optional[str]:
    resp = resp if isinstance(resp, dict) else {}
    if resp.get("status") != "verified" or not resp.get("attestation_id"):
        return f"the second proof did not verify (status {resp.get('status')!r}: {str(resp.get('reason'))[:120]})"
    if resp.get("reputation_delta") not in (None, 0):
        return (f"BUG-FIND: the second verified proof of {FAIR_MARKUP} the same UTC day earned "
                f"{resp.get('reputation_delta')!r}: the point is once per agent, circuit and day")
    return None


def gov_fail(n0: Any, n1: Any) -> Optional[str]:
    if n0 != 0:
        return f"a throwaway agent's governance count read {n0!r} before it had any attestation"
    if n1 == 2:
        return ("BUG-FIND: two verified proofs of one circuit on one UTC day counted 2 in the governance preview: it "
                "counts attestations, not circuit-days")
    if n1 != 1:
        return f"after two verified proofs of one circuit on one UTC day the governance preview read {n1!r}, not 1"
    return None


async def run_zk_v2(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                    answered: Callable, said: Callable,
                    today: Callable[[], date] = lambda: datetime.now(timezone.utc).date()) -> None:
    t0 = time.time()
    dev = getattr(bag, "developer_jwt", "") or ""
    rpc_admin = getattr(bag, "rpc_admin", None)
    other_jwt = getattr(bag, "sentinel_jwt", "") or ""

    def row(name: str, healthy: Optional[bool], code: Any = "0", fail: Optional[str] = None, skip: Optional[str] = None,
            ev: Optional[Dict[str, Any]] = None, expect: str = "success") -> None:
        outcomes[name] = make_outcome(name, "zk_v2", bool(healthy) and not skip and not fail, str(code or "0"),
                                      int((time.time() - t0) * 1000), fail, {}, expect_status=expect, skip_reason=skip)
        outcomes[name]["result_excerpt"] = ev or {}

    def tool_row(tool: str, healthy: bool, code: Any, fail: Optional[str] = None, ev: Optional[Dict[str, Any]] = None,
                 tier: str = "2", skip: Optional[str] = None) -> None:
        """§MCPTEST30 (V0636): the tool's own row from this lifecycle's real call (the rows above name no tool, so
        the three tools read refusal-only although their success path ran here every night)."""
        outcomes[tool] = make_outcome(tool, tier, bool(healthy) and not fail and not skip, str(code or "0"),
                                      int((time.time() - t0) * 1000), fail, {}, skip_reason=skip)
        outcomes[tool]["result_excerpt"] = ev or {}

    def effect_row(tool: str, healthy: Optional[bool], code: Any, fail: Optional[str] = None,
                   skip: Optional[str] = None, ev: Optional[Dict[str, Any]] = None) -> None:
        """§MCPTEST30 (V0636): an admin tool's step on the run's own object, as `admin_effect: <tool>` (the row family
        mcp_lifecycles._admin_effect writes; agentvault2-aa's admin tools are only ever called here)."""
        name = "admin_effect: " + tool.replace("theprotocol_", "")
        outcomes[name] = make_outcome(name, "admin_effect", bool(healthy) and not fail and not skip, str(code or "0"),
                                      int((time.time() - t0) * 1000), fail, {}, skip_reason=skip)
        outcomes[name]["result_excerpt"] = ev or {}

    def skip_rows(names, why: str) -> None:
        for name in names:
            if name not in outcomes:
                row(name, None, skip=why)

    async def call(tool: str, args: Dict[str, Any], *, jwt: Optional[str] = None, timeout: int = 40,
                   admin: bool = False) -> Tuple[bool, Any, str]:
        ok, body, code = await (rpc_admin if admin else rpc)(tool, args, jwt=dev if jwt is None else jwt,
                                                             timeout=timeout)
        inner = parse(body)
        return answered(ok, inner, code), inner, str(code)

    # ── the circuit reads (public) ────────────────────────────────────────────────────────────────────────────────
    okc, cat, code = await call("theprotocol_getCircuits", {})
    if not okc:
        row(ROW_CATALOG, None, code, skip=f"NOT MEASURED: the catalog could not be read ({said(cat)})")
    else:
        items = cat.get("circuits") if isinstance(cat, dict) else None
        fail = catalog_fail(items)
        row(ROW_CATALOG, fail is None, code, fail, ev={"circuits": len(items) if isinstance(items, list) else None})
    key_wrong: List[str] = []
    for cid in V2_CIRCUITS:
        okk, vk, ck = await call("theprotocol_getCircuitVerificationKey", {"circuit_id": cid})
        okm, md, cm = await call("theprotocol_getCircuitMetadata", {"circuit_id": cid})
        if not (okk and okm):
            key_wrong.append(f"{cid}: the key or the metadata was refused (HTTP {ck}/{cm}: "
                             f"{said(vk if not okk else md)[:100]})")
            continue
        why = key_fail(cid, vk, md)
        if why:
            key_wrong.append(why)
    row(ROW_KEYS, not key_wrong, "200", "; ".join(key_wrong) or None, ev={"circuits": len(V2_CIRCUITS),
                                                                           "wrong": len(key_wrong)})
    v1 = _v1_of(FAIR_MARKUP)
    okv1, v1k, cv1 = await call("theprotocol_getCircuitVerificationKey", {"circuit_id": v1})
    text = refusal_text(v1k)
    if okv1:
        fail = f"BUG-FIND: the retired {v1} served a verification key"
    elif cv1 != "404" or "retired" not in text:
        fail = f"expected 404 naming {v1} retired, got HTTP {cv1}: {said(v1k)[:120]}"
    else:
        fail = None
    row(ROW_V1_NO_KEY, fail is None, cv1, fail, ev={"http": cv1}, expect="error_4xx")

    # ── a throwaway prover ────────────────────────────────────────────────────────────────────────────────────────
    if rpc_admin is None:
        return skip_rows(PROOF_ROWS, "NOT MEASURED: the run carries no admin bridge (bag.rpc_admin), and only the "
                                     "admin tool generateTutorialProof makes a proof here")
    if not dev:
        return skip_rows(PROOF_ROWS, "NOT MEASURED: the run has no developer token to make a throwaway prover with")
    tag = secrets.token_hex(6)
    oka, made, code = await call("theprotocol_createAgent", {
        "name": f"mcp-zkv2-{tag}", "description": "MCP tester zk-v2 prover (throwaway, deleted after)"})
    did = cid_ = sec = None
    if oka and isinstance(made, dict):
        did, cid_, sec = made.get("agent_did") or made.get("did"), made.get("client_id"), made.get("client_secret")
    if not (did and cid_ and sec):
        return skip_rows(PROOF_ROWS, f"NOT MEASURED: no throwaway prover could be created ({said(made)[:90]})")
    ids: List[str] = []
    prover = None
    try:
        okt, tok, _c = await call("theprotocol_getAgentToken", {"client_id": cid_, "client_secret": sec}, timeout=20)
        prover = (tok.get("access_token") or tok.get("agent_jwt")) if okt and isinstance(tok, dict) else None
        sec = tok = None
        if not prover:
            return skip_rows(PROOF_ROWS, "NOT MEASURED: the throwaway prover's token could not be had")

        async def prove() -> Tuple[bool, Any, str]:
            return await call("theprotocol_generateTutorialProof", {"circuit_id": FAIR_MARKUP, "agent_did": did},
                              timeout=PROOF_TIMEOUT_S, admin=True)

        async def submit(circuit_id: str, proof_b64: str, inputs: Dict[str, Any],
                         jwt: Optional[str] = None) -> Tuple[bool, Any, str]:
            return await call("theprotocol_submitAttestation",
                              {**submission(circuit_id, proof_b64, inputs), "agent_jwt": jwt or prover},
                              timeout=SUBMIT_TIMEOUT_S)

        async def preview() -> Tuple[Optional[int], str, str]:
            okp, pv, cp = await call("theprotocol_previewVotingPowerAttestation", {"agent_did": did})
            n = pv.get("recent_verified_attestations") if okp and isinstance(pv, dict) else None
            return (n if isinstance(n, int) else None), cp, ("" if okp else said(pv))

        okp1, p1, cp1 = await prove()
        bound = proof_bound_fail(p1, did) if okp1 else None
        if not okp1:
            row(ROW_PROOF, False, cp1, f"generateTutorialProof refused a v2.0.0 proof for a fresh agent: {said(p1)[:160]}")
        else:
            row(ROW_PROOF, bound is None, cp1, bound, ev={"circuit_id": FAIR_MARKUP,
                                                          "generation_time_ms": (p1 or {}).get("generation_time_ms")})
        _p1 = p1 if isinstance(p1, dict) else {}
        _wrong = (None if (_p1.get("proof_bytes_base64") and isinstance(_p1.get("public_inputs"), dict)
                           and _p1.get("circuit_id", FAIR_MARKUP) == FAIR_MARKUP) else
                  f"the answer carries no proof of {FAIR_MARKUP} (circuit {_p1.get('circuit_id')!r})")
        effect_row("theprotocol_generateTutorialProof", okp1, cp1,
                   (bound or _wrong) if okp1 else f"generateTutorialProof refused: HTTP {cp1}: {said(p1)[:120]}",
                   ev={"circuit_id": FAIR_MARKUP, "proof": bool(_p1.get("proof_bytes_base64"))})
        if not okp1 or bound:
            return skip_rows(PROOF_ROWS, "NOT MEASURED: no proof for the throwaway prover to submit")
        b64, inputs = p1["proof_bytes_base64"], dict(p1["public_inputs"])
        n0, cn0, pv_refusal = await preview()

        # proof_of_reputation: input validation, never a proof
        okb, rb, cb = await submit(OPTION_B, "", {"reputation_threshold": 1, "agent_did": did})
        fail = failed_for(rb, "nothing was proven") if okb else f"submitAttestation refused it: HTTP {cb}: {said(rb)[:120]}"
        row(ROW_OPTION_B, fail is None, cb, None if fail is None else (f"BUG-FIND: {OPTION_B} {fail}"
                                                                      if fail == "it VERIFIED" else fail),
            ev={"status": (rb or {}).get("status") if isinstance(rb, dict) else None})

        # no reference_label: 422 before anything is verified
        okn, rn, cn = await submit(FAIR_MARKUP, b64, {k: v for k, v in inputs.items() if k != "reference_label"})
        text = refusal_text(rn)
        if okn:
            fail = f"BUG-FIND: a v2.0.0 submission without reference_label was answered ({(rn or {}).get('status')!r})"
        elif cn != "422" or "reference_label" not in text:
            fail = f"expected 422 naming reference_label, got HTTP {cn}: {said(rn)[:120]}"
        else:
            fail = None
        row(ROW_NO_LABEL, fail is None, cn, fail, ev={"http": cn}, expect="error_4xx")

        # one element raised by the field order: the same proof to a verifier that reduces, other bytes to a replay check
        off = offset_element(b64)
        if off is None:
            row(ROW_OFFSET, None, skip="NOT MEASURED: the proof does not have the layout offset_element reads "
                                       "(a 4-byte count and 32-byte elements)")
        else:
            oko, ro, co = await submit(FAIR_MARKUP, off, inputs)
            fail = failed_for(ro, "non-canonical") if oko else f"refused with HTTP {co}: {said(ro)[:120]}"
            row(ROW_OFFSET, fail is None, co,
                None if fail is None else (f"BUG-FIND: a proof with an element raised by the field order {fail}"
                                           if fail == "it VERIFIED" else fail),
                ev={"status": (ro or {}).get("status") if isinstance(ro, dict) else None})

        # another agent submits the throwaway's proof
        if not other_jwt:
            row(ROW_OTHER_AGENT, None, skip="NOT MEASURED: the run has no sentinel agent to submit as another agent")
        else:
            okx, rx, cx = await submit(FAIR_MARKUP, b64, inputs, jwt=other_jwt)
            fail = failed_for(rx, "made for another agent") if okx else f"refused with HTTP {cx}: {said(rx)[:120]}"
            row(ROW_OTHER_AGENT, fail is None, cx,
                None if fail is None else (f"BUG-FIND: a proof made for one agent {fail} for another"
                                           if fail == "it VERIFIED" else fail),
                ev={"status": (rx or {}).get("status") if isinstance(rx, dict) else None})

        # the retired v1.0.0 id
        okr, rr, cr = await submit(v1, b64, inputs)
        fail = failed_for(rr, "is retired") if okr else f"refused with HTTP {cr}: {said(rr)[:120]}"
        if fail and fail != "it VERIFIED":
            fail += " (the target refused it, but not as retired: v1 acceptance switched on there, or the rule changed)"
        row(ROW_V1_RETIRED, fail is None, cr,
            None if fail is None else (f"BUG-FIND: a proof submitted under the retired {v1} {fail}"
                                       if fail == "it VERIFIED" else fail),
            ev={"status": (rr or {}).get("status") if isinstance(rr, dict) else None})

        # the proof, by its agent
        day0 = today()
        oks, rs, cs = await submit(FAIR_MARKUP, b64, inputs)
        rs = rs if isinstance(rs, dict) else {}
        id1 = rs.get("attestation_id") if oks and rs.get("status") == "verified" else None
        if id1:
            ids.append(str(id1))
        okv, rv, cv = (await call("theprotocol_reverifyAttestation", {"attestation_id": id1}) if id1
                       else (False, {}, "0"))
        kept = okv or cv != "404"
        if not id1:
            row(ROW_VERIFIED, False, cs, f"the throwaway's own fresh proof did not verify: HTTP {cs} status "
                                         f"{rs.get('status')!r}: {str(rs.get('reason') or said(rs))[:160]}")
            return skip_rows(PROOF_ROWS, "NOT MEASURED: the run's proof did not verify, so nothing builds on it")
        fail = None
        if not carried_matches(rs, p1):
            fail = "the verified answer's proof_public_values are not the values the proof was made for"
        elif kept and rs.get("reputation_delta") != 1:
            fail = (f"BUG-FIND: the first verified proof of {FAIR_MARKUP} of a fresh agent earned "
                    f"{rs.get('reputation_delta')!r}, not 1")
        row(ROW_VERIFIED, fail is None, cs, fail, ev={"attestation_id": id1, "reputation_delta": rs.get("reputation_delta"),
                                                      "kept": kept})
        tool_row("theprotocol_submitAttestation", fail is None, cs, fail, ev={"status": rs.get("status"),
                                                                          "attestation_id": id1})
        if not kept:
            return skip_rows(PROOF_ROWS, "NOT MEASURED: the target answered 404 for the attestation it had just "
                                         "verified: it keeps no attestation rows (no replay, day or revocation to measure)")
        rv = rv if isinstance(rv, dict) else {}
        fail = None if (okv and rv.get("verified") is True and not rv.get("revoked")) else (
            f"re-verification of a fresh verified attestation answered HTTP {cv} verified={rv.get('verified')!r} "
            f"revoked={rv.get('revoked')!r}: {str(rv.get('failure_reason') or said(rv))[:120]}")
        row(ROW_REVERIFY, fail is None, cv, fail, ev={"attestation_id": id1, "verified": rv.get("verified")})
        tool_row("theprotocol_reverifyAttestation", fail is None, cv, fail, ev={"verified": rv.get("verified")},
                 tier="1")

        # the attestation's own record and its signed bundle, read by the prover's owner before anything revokes it
        # (§MCPTEST30, V0636: the two developer-tier reads only this lifecycle makes an attestation for)
        okr1, rec, cr1 = await call("theprotocol_getAttestationDetail", {"attestation_id": id1})
        fail = record_fail(rec, id1, did, b64, inputs) if okr1 else (
            f"the owner's read of its verified attestation was refused: HTTP {cr1}: {said(rec)[:120]}")
        rec = rec if isinstance(rec, dict) else {}
        tool_row("theprotocol_getAttestationDetail", fail is None, cr1, fail, tier="3",
                 ev={"verified": rec.get("verified"), "circuit_version": rec.get("circuit_version")})
        okb1, bun, cb1 = await call("theprotocol_getAttestationBundle", {"attestation_id": id1})
        bun = bun if isinstance(bun, dict) else {}
        if not okb1 and cb1 == "503":
            tool_row("theprotocol_getAttestationBundle", False, cb1, tier="3",
                     skip=f"NOT MEASURED: this target exports no bundles ({said(bun)[:100]})")
        else:
            fail = bundle_fail(bun, id1, did, b64, inputs) if okb1 else (
                f"the bundle of the owner's verified attestation was refused: HTTP {cb1}: {said(bun)[:120]}")
            tool_row("theprotocol_getAttestationBundle", fail is None, cb1, fail, tier="3",
                     ev={"verified": bun.get("verified"), "signed": bool(bun.get("signature"))})

        # the same proof again
        okd, rd, cd = await submit(FAIR_MARKUP, b64, inputs)
        text = refusal_text(rd)
        if okd:
            fail = f"BUG-FIND: the same verified proof was answered again ({(rd or {}).get('status')!r}): a proof counts once"
        elif cd != "409" or "already attested" not in text:
            fail = f"expected 409 'already attested', got HTTP {cd}: {said(rd)[:120]}"
        else:
            fail = None
        row(ROW_REPLAY, fail is None, cd, fail, ev={"http": cd}, expect="error_4xx")

        # a second proof, same circuit, same UTC day
        okp2, p2, cp2 = await prove()
        bound2 = proof_bound_fail(p2, did) if okp2 else "generateTutorialProof refused the second proof"
        rs2: Dict[str, Any] = {}
        if bound2:
            row(ROW_SAME_DAY, None, cp2, skip=f"NOT MEASURED: no second proof ({bound2}: {said(p2)[:80]})")
        else:
            oks2, rs2, cs2 = await submit(FAIR_MARKUP, p2["proof_bytes_base64"], dict(p2["public_inputs"]))
            rs2 = rs2 if isinstance(rs2, dict) else {}
            if rs2.get("status") == "verified" and rs2.get("attestation_id"):
                ids.append(str(rs2["attestation_id"]))
            if today() != day0:
                row(ROW_SAME_DAY, None, cs2, skip="NOT MEASURED: the run crossed UTC midnight between the two proofs")
            else:
                fail = same_day_fail(rs2) if oks2 else f"the second proof was refused: HTTP {cs2}: {said(rs2)[:120]}"
                row(ROW_SAME_DAY, fail is None, cs2, fail, ev={"reputation_delta": rs2.get("reputation_delta"),
                                                               "status": rs2.get("status")})
        n1, cn1, _ = await preview()
        if n0 is None:
            row(ROW_GOV_DAYS, None, cn0, skip=f"NOT MEASURED: the governance preview answered HTTP {cn0} "
                                              f"({pv_refusal[:100]})")
        elif len(ids) < 2 or today() != day0:
            row(ROW_GOV_DAYS, None, cn1, skip="NOT MEASURED: fewer than two verified proofs on one UTC day, where "
                                              "counting attestations and counting circuit-days agree")
        else:
            fail = gov_fail(n0, n1)
            row(ROW_GOV_DAYS, fail is None, cn1, fail, ev={"before": n0, "after_two_proofs": n1})

        # §MCPTEST30 (V0636): the admin revokes the second proof's attestation (adminRevokeAttestation, an admin tool no
        # other step reaches on a real object); the agent revokes the first below, as before
        id2 = str(rs2["attestation_id"]) if rs2.get("status") == "verified" and rs2.get("attestation_id") else None
        if id2 and id2 in ids:
            oka, ra, ca = await call("theprotocol_adminRevokeAttestation",
                                     {"attestation_id": id2,
                                      "reason": "MCP tester zk-v2: the admin revokes the run's own second attestation"},
                                     admin=True)
            okr2, rr2, _cr2 = await call("theprotocol_reverifyAttestation", {"attestation_id": id2})
            rr2 = rr2 if isinstance(rr2, dict) else {}
            okd2, rec2, _cd2 = await call("theprotocol_getAttestationDetail", {"attestation_id": id2})
            rec2 = rec2 if isinstance(rec2, dict) else {}
            fail = None
            if not oka:
                fail = f"the admin's revocation answered HTTP {ca}: {said(ra)[:120]}"
            elif not (okr2 and rr2.get("revoked") is True and rr2.get("verified") is False):
                fail = (f"BUG-FIND: after the admin's revocation re-verification answered verified={rr2.get('verified')!r} "
                        f"revoked={rr2.get('revoked')!r}")
            elif not (okd2 and rec2.get("revoked_at")):
                fail = (f"BUG-FIND: after the admin's revocation the attestation's record reads revoked_at="
                        f"{rec2.get('revoked_at')!r}")
            ev = {"revoked": rr2.get("revoked"), "revoked_at": bool(rec2.get("revoked_at"))}
            # the revocation moves no units: it stamps revoked_at (read back from the record here) and takes back a
            # reputation point this second proof never earned
            effect_row("theprotocol_adminRevokeAttestation", fail is None, ca, fail, ev=ev)
            if oka:
                ids.remove(id2)
        else:
            effect_row("theprotocol_adminRevokeAttestation", None, "0",
                       skip="NOT MEASURED: no second verified attestation of the run's to revoke as the admin")

        # revoke what the run verified: out of the governance count, and re-verification answers revoked
        revoked: List[bool] = []
        for aid in ids:
            okx, rx, _cx = await call("theprotocol_agentRevokeAttestation", {
                "agent_jwt": prover, "attestation_id": aid, "reason": "MCP tester zk-v2: the run's own attestation"})
            revoked.append(bool(okx and isinstance(rx, dict) and rx.get("revoked_at") and not rx.get("already_revoked")))
            if len(revoked) == 1:
                tool_row("theprotocol_agentRevokeAttestation", revoked[0], _cx,
                         None if revoked[0] else f"the revocation of the run's own attestation answered HTTP {_cx}",
                         ev={"revoked_at": bool(isinstance(rx, dict) and rx.get("revoked_at"))})
        n2, _cn2, _ = await preview()
        okv2, rv2, cv2 = await call("theprotocol_reverifyAttestation", {"attestation_id": id1})
        rv2 = rv2 if isinstance(rv2, dict) else {}
        wrong = []
        if not all(revoked):
            wrong.append(f"{revoked.count(False)} of {len(revoked)} revocations were not answered with a revocation")
        if n0 is not None and n2 != 0:
            wrong.append(f"after revoking every attestation the governance preview still read {n2!r}")
        if not (okv2 and rv2.get("verified") is False and rv2.get("revoked") is True):
            wrong.append(f"re-verification of a revoked attestation answered HTTP {cv2} verified={rv2.get('verified')!r} "
                         f"revoked={rv2.get('revoked')!r}")
        ids.clear()
        row(ROW_REVOKE, not wrong, cv2, "; ".join(wrong) or None, ev={"revoked": len(revoked), "count_after": n2})
    except Exception as exc:
        skip_rows(PROOF_ROWS, f"NOT MEASURED: the lifecycle stopped on {type(exc).__name__} before this row")
        raise
    finally:
        for aid in ids:   # a verified attestation the run did not get to revoke
            await call("theprotocol_agentRevokeAttestation", {"agent_jwt": prover, "attestation_id": aid,
                                                               "reason": "MCP tester zk-v2: cleanup"})
        prover = None
        await call("theprotocol_deleteMyAgentByDev", {"agent_did": did}, timeout=30)
