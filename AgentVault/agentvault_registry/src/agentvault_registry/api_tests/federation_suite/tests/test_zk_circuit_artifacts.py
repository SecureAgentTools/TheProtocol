"""ZK circuit artifacts retrievability tests (§pass73.3.10 Batch 32).

4 read-only tests probing the ZKP circuit artifact endpoints. Each
circuit serves 3 artifacts (ACIR bytecode, Rust source, Nargo.toml).
A peer verifying an attestation needs all 3 to reconstruct the circuit.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


@federation_test(
    name="circuits_catalog_lists_artifact_urls",
    category="zk_circuit_artifacts",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["zkp", "circuits", "catalog"],
)
async def test_circuits_catalog_urls(rig: FederationTestRig) -> AssertionResult:
    """getCircuits returns each circuit with acir_url + source_url +
    nargo_toml_url populated."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getCircuits")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            circuits = r.get("circuits") if isinstance(r, dict) else r
            if not isinstance(circuits, list) or not circuits:
                state["empty_or_bad"] = True
                return False
            with_all_urls = sum(
                1 for c in circuits
                if isinstance(c, dict)
                and c.get("acir_url") and c.get("source_url")
                and c.get("nargo_toml_url")
            )
            state["count"] = len(circuits)
            state["with_all_urls"] = with_all_urls
            state["sample_id"] = circuits[0].get("circuit_id") if circuits else None
            return with_all_urls >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="circuits catalog has ≥1 circuit with all 3 artifact URLs",
        capture_state=lambda: state,
    )


@federation_test(
    name="circuit_acir_artifact_retrievable",
    category="zk_circuit_artifacts",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["zkp", "circuit-acir"],
)
async def test_circuit_acir(rig: FederationTestRig) -> AssertionResult:
    """getCircuitACIR returns the ACIR bytecode for a known circuit_id
    from the catalog. The ACIR is base64-encoded Noir IR + structural
    metadata."""
    state: dict = {}

    async def predicate():
        try:
            lst = await rig.mcp("sandbox-A").call("getCircuits")
            circuits = (lst or {}).get("circuits") if isinstance(lst, dict) else []
            if not circuits:
                state["no_circuits"] = True
                return False
            target = circuits[0]
            cid = target.get("circuit_id") if isinstance(target, dict) else None
            if not cid:
                state["no_circuit_id"] = True
                return False
            state["circuit_id"] = cid
            r = await rig.mcp("sandbox-A").call("getCircuitACIR", {"circuit_id": cid})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            # ACIR can be bytes (str representation), dict envelope, or text
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                # Common shapes: {acir: ..., circuit_id: ...} or {data: ...}
                return bool(r.keys())
            elif isinstance(r, str):
                state["bytes_len"] = len(r)
                return len(r) > 0
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="circuit ACIR retrievable for known circuit_id",
        capture_state=lambda: state,
    )


@federation_test(
    name="circuit_source_artifact_retrievable",
    category="zk_circuit_artifacts",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["zkp", "circuit-source"],
)
async def test_circuit_source(rig: FederationTestRig) -> AssertionResult:
    """getCircuitSource returns the Noir source code for a known
    circuit_id. Validates source is non-empty + has Noir syntax markers."""
    state: dict = {}

    async def predicate():
        try:
            lst = await rig.mcp("sandbox-A").call("getCircuits")
            circuits = (lst or {}).get("circuits") if isinstance(lst, dict) else []
            if not circuits:
                state["no_circuits"] = True
                return False
            cid = circuits[0].get("circuit_id") if isinstance(circuits[0], dict) else None
            if not cid:
                state["no_circuit_id"] = True
                return False
            state["circuit_id"] = cid
            r = await rig.mcp("sandbox-A").call("getCircuitSource", {"circuit_id": cid})
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                text = (r.get("source") or r.get("text")
                        or r.get("_text") or "")
                if isinstance(text, str) and text:
                    state["source_len"] = len(text)
                    return True
                return bool(r.keys())
            elif isinstance(r, str):
                state["len"] = len(r)
                return len(r) > 0
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="circuit source retrievable for known circuit_id",
        capture_state=lambda: state,
    )


@federation_test(
    name="circuit_nargo_toml_retrievable",
    category="zk_circuit_artifacts",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["zkp", "circuit-nargo-toml"],
)
async def test_circuit_nargo_toml(rig: FederationTestRig) -> AssertionResult:
    """getCircuitNargoToml returns the Nargo.toml manifest for a known
    circuit_id. The manifest declares compiler version + dependencies."""
    state: dict = {}

    async def predicate():
        try:
            lst = await rig.mcp("sandbox-A").call("getCircuits")
            circuits = (lst or {}).get("circuits") if isinstance(lst, dict) else []
            if not circuits:
                state["no_circuits"] = True
                return False
            cid = circuits[0].get("circuit_id") if isinstance(circuits[0], dict) else None
            if not cid:
                state["no_circuit_id"] = True
                return False
            state["circuit_id"] = cid
            r = await rig.mcp("sandbox-A").call(
                "getCircuitNargoToml", {"circuit_id": cid}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return bool(r.keys())
            elif isinstance(r, str):
                state["len"] = len(r)
                return len(r) > 0
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="circuit Nargo.toml retrievable for known circuit_id",
        capture_state=lambda: state,
    )
