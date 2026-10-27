"""§MCPTEST30 (V0612) — the zk-v2 lifecycle (api_tests/contracts/zk_v2_attestations.py) against a fake registry.

The fake keeps the rules of agentvault2-90's §ZKV2 (routers/attestations.py, core/zkp_verifier.py, crud/attestation.py):
a 422 without reference_label, the reference bound to the submitting agent, a non-canonical element refused, v1.0.0
retired, Option B never verified, one verified attestation per proof and per reference (409), one point per agent,
circuit and UTC day (revoked rows included), the governance preview counting unrevoked circuit-days. A correct fake
gives every row healthy; each control breaks ONE rule and the row for it must go red, so no row can pass by
construction. The lifecycle runs through the real `_make_outcome`, `_answered`, `_said` and the flow's own
`_parse_rpc_result`.
"""
from __future__ import annotations

import ast
import asyncio
import base64
import hashlib
import json
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.contracts import mcp_lifecycles as ml  # noqa: E402
from agentvault_registry.api_tests.contracts import zk_v2_attestations as ZK  # noqa: E402
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    _parse_rpc_result,
)
from agentvault_registry.api_tests.zkp_v2_helpers import (  # noqa: E402
    BN254_R, FAIR_MARKUP, OPTION_B, V1_CIRCUITS, V2_CIRCUITS, derive_reference,
)

SENTINEL_JWT = "sentinel-jwt"
SENTINEL_DID = "did:theprotocol:sentinel"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _ok(obj: Any):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {
        "content": [{"type": "text", "text": json.dumps(obj)}], "isError": False}}, "200"


def _refused(tool: str, code: int, detail: str):
    text = f"Error: {tool.replace('theprotocol_', '')} returned HTTP {code}: {detail}"
    return False, {"jsonrpc": "2.0", "id": 1, "result": {
        "content": [{"type": "text", "text": text}], "isError": True}}, str(code)


class FakeRegistry:
    """The §ZKV2 rules, small. `broken` names the one rule a control breaks."""

    def __init__(self, broken: str = "", day: date = date(2026, 10, 13)):
        self.broken = broken
        self.day = day
        self.tokens: Dict[str, str] = {SENTINEL_JWT: SENTINEL_DID}
        self.agents: Dict[str, Dict[str, str]] = {}
        self.deleted: list = []
        self.issued: set = set()
        self.rows: list = []           # each {id, did, circuit, verified, revoked, hash, ref, day}
        self.calls: list = []
        self.secrets: list = []

    # ── proofs: a 4-byte count and 32-byte elements, every element below the field order ──
    def _proof(self, did: str) -> Dict[str, Any]:
        label = uuid.uuid4().hex
        if self.broken == "proof_for_other":
            did = "did:theprotocol:someone-else"
        elems = [int.from_bytes(uuid.uuid4().bytes, "big") for _ in range(8)]
        raw = len(elems).to_bytes(4, "big") + b"".join(e.to_bytes(32, "big") for e in elems)
        self.issued.add(hashlib.sha256(raw).hexdigest())
        return {"circuit_id": FAIR_MARKUP, "proof_bytes_base64": base64.b64encode(raw).decode(),
                "public_inputs": {"max_markup_bps": "2000", "offered_price": "720",
                                  "context": str(derive_reference(did, label)), "reference_label": label},
                "public_outputs": {"commitment": "424242"}, "generation_time_ms": 900}

    def _submit(self, a: Dict[str, Any]):
        tool = "theprotocol_submitAttestation"
        did = self.tokens.get(a.get("agent_jwt", ""))
        cid, inputs = a["circuit_id"], dict(a.get("public_inputs") or {})
        new_id = str(uuid.uuid4())

        def failed(reason):
            self.rows.append({"id": new_id, "did": did, "circuit": cid, "verified": False, "revoked": False})
            return _ok({"status": "failed", "circuit_id": cid, "attestation_id": new_id, "reason": reason,
                        "message": f"Proof not verified: {reason}"})

        if cid == OPTION_B:
            if self.broken == "option_b_verified":
                return _ok({"status": "verified", "circuit_id": cid, "attestation_id": new_id})
            return failed("proof_of_reputation has no circuit keys; inputs are valid but nothing was proven")
        if cid in V1_CIRCUITS:
            if self.broken == "v1_accepted":
                return _ok({"status": "verified", "circuit_id": cid, "attestation_id": new_id})
            return failed(f"{cid} is retired: its policy limits are private inputs that nothing binds")
        label = inputs.get("reference_label")
        if not label and self.broken != "no_label_accepted":
            return _refused(tool, 422, "public_inputs.reference_label is required (1 to 200 characters): ...")
        raw = base64.b64decode(a["proof_data"]["proof_bytes"])
        n = int.from_bytes(raw[:4], "big")
        elems = [int.from_bytes(raw[4 + 32 * i:36 + 32 * i], "big") for i in range(n)]
        if self.broken == "offset_accepted":
            raw = n.to_bytes(4, "big") + b"".join((e % BN254_R).to_bytes(32, "big") for e in elems)
        elif any(e >= BN254_R for e in elems):
            return failed("proof bytes do not have the bb proof layout (or carry a non-canonical element)")
        h = hashlib.sha256(raw).hexdigest()
        if h not in self.issued:
            return failed("bb verify failed")
        ref = inputs.get("context")
        if self.broken != "other_agent_verifies" and (not label or str(derive_reference(did, label)) != ref):
            return failed("the proof's context is not derive_reference(<your agent DID>, reference_label): it was "
                          "made for another agent or another label")
        if self.broken != "replay_accepted":
            for r in self.rows:
                if r["verified"] and (r.get("hash") == h or (r["circuit"] == cid and r.get("ref") == ref)):
                    return _refused(tool, 409, f"This proof (or one with the same context) was already attested as "
                                               f"{r['id']}. A proof counts once")
        earlier = [r for r in self.rows if r["verified"] and r["did"] == did and r["circuit"] == cid
                   and r.get("day") == self.day]
        earns = not earlier or self.broken == "second_earns"
        self.rows.append({"id": new_id, "did": did, "circuit": cid, "verified": True, "revoked": False,
                          "hash": h, "ref": ref, "day": self.day})
        values = {k: v for k, v in inputs.items() if k != "reference_label"}
        values["commitment"] = "424242"
        self.rows[-1].update({"b64": a["proof_data"]["proof_bytes"], "inputs": {**inputs, **values}})
        return _ok({"status": "verified", "circuit_id": cid, "attestation_id": new_id, "message": "ok",
                    "reputation_delta": 1 if earns else None, "proof_public_values": values})

    def _count(self, did: str) -> int:
        live = [r for r in self.rows if r["did"] == did and r["verified"]
                and (not r["revoked"] or self.broken == "revoke_ignored")]
        if self.broken == "gov_counts_rows":
            return len(live)
        return len({(r["circuit"], r["day"]) for r in live})

    async def rpc(self, tool: str, a: Dict[str, Any], jwt: str = "", timeout: int = 15):
        self.calls.append(tool)
        if tool == "theprotocol_getCircuits":
            items = [{"circuit_id": c, "status": "active", "acir_available": True, "vk_url": "x", "metadata_url": "y"}
                     for c in V2_CIRCUITS]
            items += [{"circuit_id": c, "status": "retired", "acir_available": True,
                       "superseded_by": c.replace("/v1.0.0", "/v2.0.0")} for c in V1_CIRCUITS]
            return _ok({"circuits": items})
        if tool == "theprotocol_getCircuitVerificationKey":
            if a["circuit_id"] in V1_CIRCUITS:
                return _refused(tool, 404, f"Circuit '{a['circuit_id']}' has no published verification key; it is "
                                           f"retired, use {a['circuit_id'].replace('/v1.0.0', '/v2.0.0')}")
            key = ("vk:" + a["circuit_id"]).encode()
            return _ok({"circuit_id": a["circuit_id"], "verification_key_b64": base64.b64encode(key).decode(),
                        "size_bytes": len(key), "sha256": hashlib.sha256(key).hexdigest()})
        if tool == "theprotocol_getCircuitMetadata":
            key = ("vk:" + a["circuit_id"]).encode()
            sha = hashlib.sha256(b"other" if self.broken == "key_mismatch" else key).hexdigest()
            return _ok({"circuit_id": a["circuit_id"], "metadata": {
                "Artifacts": {"verification_key_sha256": sha}, "policy_in_force": {"max_markup_bps": 3000}}})
        if tool == "theprotocol_createAgent":
            did, sec = f"did:theprotocol:{uuid.uuid4()}", "SECRET-" + uuid.uuid4().hex
            self.agents[a["name"]] = {"did": did, "client_id": "cid-" + did[-6:], "secret": sec}
            self.secrets.append(sec)
            return _ok({"agent_did": did, "client_id": "cid-" + did[-6:], "client_secret": sec})
        if tool == "theprotocol_getAgentToken":
            ag = next(x for x in self.agents.values() if x["client_id"] == a["client_id"])
            assert a["client_secret"] == ag["secret"]
            tok = "TOKEN-" + uuid.uuid4().hex
            self.tokens[tok] = ag["did"]
            self.secrets.append(tok)
            return _ok({"access_token": tok})
        if tool == "theprotocol_generateTutorialProof":
            return _ok(self._proof(a["agent_did"]))
        if tool == "theprotocol_submitAttestation":
            return self._submit(a)
        if tool == "theprotocol_previewVotingPowerAttestation":
            if self.broken == "preview_403":
                return _refused(tool, 403, "sandbox-only endpoint")
            return _ok({"agent_did": a["agent_did"], "recent_verified_attestations": self._count(a["agent_did"])})
        if tool == "theprotocol_reverifyAttestation":
            r = next((x for x in self.rows if x["id"] == a["attestation_id"]), None)
            if r is None or self.broken == "no_rows_kept":
                return _refused(tool, 404, "Attestation not found")
            return _ok({"attestation_id": r["id"], "verified": r["verified"] and not r["revoked"],
                        "revoked": r["revoked"], "failure_reason": "attestation revoked" if r["revoked"] else None})
        if tool in ("theprotocol_getAttestationDetail", "theprotocol_getAttestationBundle"):
            r = next((x for x in self.rows if x["id"] == a["attestation_id"]), None)
            if r is None:
                return _refused(tool, 404, "Attestation not found")
            b64 = r.get("b64") or ""
            if self.broken == "bundle_other_proof" and tool.endswith("Bundle"):
                b64 = base64.b64encode(b"another proof").decode()
            version = "v1.0.0" if self.broken == "detail_wrong_circuit" and tool.endswith("Detail") else "v2.0.0"
            common = {"agent_did": r["did"], "circuit_id": r["circuit"], "circuit_version": version,
                      "public_inputs": r.get("inputs") or {}, "verified": r["verified"],
                      "proof_hash": hashlib.sha256(base64.b64decode(b64)).hexdigest()}
            if tool.endswith("Detail"):
                stamped = r["revoked"] and self.broken != "admin_revoke_unstamped"
                return _ok({"id": r["id"], **common, "revoked_at": "2026-10-13T03:30:00Z" if stamped else None})
            return _ok({"attestation_id": r["id"], **common, "proof_b64": b64, "revoked": r["revoked"],
                        "signature": "c2ln"})
        if tool in ("theprotocol_agentRevokeAttestation", "theprotocol_adminRevokeAttestation"):
            r = next(x for x in self.rows if x["id"] == a["attestation_id"])
            already, r["revoked"] = r["revoked"], True
            return _ok({"attestation_id": r["id"], "revoked_at": "2026-10-13T03:30:00Z", "already_revoked": already})
        if tool == "theprotocol_deleteMyAgentByDev":
            self.deleted.append(a["agent_did"])
            return _ok({"deleted": True})
        raise AssertionError(f"unexpected tool {tool}")


class Bag:
    def __init__(self, reg: FakeRegistry, admin: bool = True):
        self.developer_jwt = "dev-jwt"
        self.sentinel_jwt = SENTINEL_JWT
        self.rpc_admin = reg.rpc if admin else None


def _run(reg: FakeRegistry, admin: bool = True, today=None) -> Dict[str, dict]:
    outcomes: Dict[str, dict] = {}
    kw = {"today": today} if today else {"today": lambda: reg.day}
    asyncio.run(ZK.run_zk_v2(reg.rpc, _parse_rpc_result, Bag(reg, admin), outcomes, ml._make_outcome,
                             ml._answered, ml._said, **kw))
    return outcomes


def test_a_correct_registry_measures_every_row_healthy():
    reg = FakeRegistry()
    out = _run(reg)
    # §MCPTEST30 (V0636): beside its own rows, the lifecycle writes the three tools' own rows from its real calls
    assert set(out) == set(ZK.ROWS) | {"theprotocol_submitAttestation", "theprotocol_reverifyAttestation",
                                       "theprotocol_getAttestationDetail", "theprotocol_getAttestationBundle",
                                       "theprotocol_agentRevokeAttestation", "admin_effect: generateTutorialProof",
                                       "admin_effect: adminRevokeAttestation"}
    bad = {k: (v.get("fail_reason"), v.get("skip_reason")) for k, v in out.items() if not v["healthy"]}
    assert bad == {}
    assert len(reg.deleted) == 1                                   # the throwaway is gone
    assert all(r["revoked"] for r in reg.rows if r["verified"] and r["did"] != SENTINEL_DID)
    record = json.dumps(out)
    assert not any(s in record for s in reg.secrets)               # no credential in a row
    assert "proof_bytes" not in record and "AAAA" not in record    # no proof bytes either


CONTROLS = [
    ("replay_accepted", ZK.ROW_REPLAY, "BUG-FIND"),
    ("second_earns", ZK.ROW_SAME_DAY, "BUG-FIND"),
    ("gov_counts_rows", ZK.ROW_GOV_DAYS, "counts attestations, not circuit-days"),
    ("other_agent_verifies", ZK.ROW_OTHER_AGENT, "BUG-FIND"),
    ("offset_accepted", ZK.ROW_OFFSET, "BUG-FIND"),
    ("v1_accepted", ZK.ROW_V1_RETIRED, "BUG-FIND"),
    ("option_b_verified", ZK.ROW_OPTION_B, "BUG-FIND"),
    ("no_label_accepted", ZK.ROW_NO_LABEL, "BUG-FIND"),
    ("key_mismatch", ZK.ROW_KEYS, "its metadata names"),
    ("revoke_ignored", ZK.ROW_REVOKE, "still read"),
    ("proof_for_other", ZK.ROW_PROOF, "made for another agent"),
    ("detail_wrong_circuit", "theprotocol_getAttestationDetail", "not fairMarkupPolicy/v2.0.0"),
    ("bundle_other_proof", "theprotocol_getAttestationBundle", "proof bytes sent"),
    ("admin_revoke_unstamped", "admin_effect: adminRevokeAttestation", "revoked_at"),
]


@pytest.mark.parametrize("broken,row,words", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_each_broken_rule_turns_its_row_red(broken, row, words):
    reg = FakeRegistry(broken=broken)
    out = _run(reg)
    assert out[row]["healthy"] is False, (broken, out[row])
    assert words in (out[row].get("fail_reason") or ""), out[row].get("fail_reason")
    assert len(reg.deleted) == 1                                   # cleanup runs on every path


def test_without_the_admin_bridge_the_proof_rows_say_so_and_no_agent_is_made():
    reg = FakeRegistry()
    out = _run(reg, admin=False)
    for name in ZK.READ_ROWS:
        assert out[name]["healthy"] is True
    for name in ZK.PROOF_ROWS:
        assert out[name]["healthy"] is False and "admin bridge" in out[name]["skip_reason"]
    assert "theprotocol_createAgent" not in reg.calls and reg.deleted == []


def test_a_run_across_utc_midnight_measures_no_day_rule():
    reg = FakeRegistry()
    days = iter([date(2026, 10, 13)] + [date(2026, 10, 14)] * 10)
    out = _run(reg, today=lambda: next(days))
    assert "crossed UTC midnight" in (out[ZK.ROW_SAME_DAY].get("skip_reason") or "")
    assert out[ZK.ROW_GOV_DAYS]["skip_reason"] and out[ZK.ROW_GOV_DAYS]["healthy"] is False
    assert out[ZK.ROW_VERIFIED]["healthy"] is True


def test_a_target_without_the_preview_skips_the_count_and_still_judges_revocation():
    reg = FakeRegistry(broken="preview_403")
    out = _run(reg)
    assert "403" in out[ZK.ROW_GOV_DAYS]["skip_reason"]
    assert out[ZK.ROW_REVOKE]["healthy"] is True and out[ZK.ROW_SAME_DAY]["healthy"] is True


def test_a_target_that_keeps_no_rows_measures_nothing_that_needs_them():
    reg = FakeRegistry(broken="no_rows_kept")
    out = _run(reg)
    assert out[ZK.ROW_VERIFIED]["healthy"] is True                 # verified, no point expected without a row
    for name in (ZK.ROW_REPLAY, ZK.ROW_SAME_DAY, ZK.ROW_GOV_DAYS, ZK.ROW_REVERIFY, ZK.ROW_REVOKE):
        assert "keeps no attestation rows" in (out[name].get("skip_reason") or ""), name


def test_the_lifecycle_is_registered_and_derives_the_reference_itself():
    assert {"name": "zk_v2_attestations", "runner": ml.lifecycle_zk_v2_attestations} in ml.LIFECYCLES
    tree = ast.parse(Path(ZK.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any("zkp_verifier" in (m or "") for m in imported)  # the product's own derive_reference is never used
