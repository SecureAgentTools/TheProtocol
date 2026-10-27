"""§MCPTEST30 (V0525, 2026-10-01) — a circuit without compiled bytecode is a 404 that says so, and the list says which
circuits carry it. Round 8 (sbx-alpha, V0523): getCircuits listed four circuits, the ACIR of two answered 500 (never
compiled in the tree, so no image carries it)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import attestations as A


@pytest.fixture()
def two_circuits(tmp_path, monkeypatch):
    built = tmp_path / "built.bin"
    built.write_bytes(b"\x00acir")
    entry = lambda b: {"bin": b, "source": tmp_path / "main.nr", "nargo": tmp_path / "Nargo.toml", "name": "x",
                       "status": "retired", "superseded_by": "x/v2.0.0"}
    monkeypatch.setattr(A, "_CIRCUIT_FILE_MAP", {"compiled/v1.0.0": entry(built),
                                                 "neverCompiled/v1.0.0": entry(tmp_path / "missing.bin")})


def test_the_list_says_which_circuits_carry_bytecode(two_circuits):
    rows = {r["circuit_id"]: r for r in asyncio.run(A.list_circuits())["circuits"]}
    assert rows["compiled/v1.0.0"]["acir_available"] is True
    assert rows["neverCompiled/v1.0.0"]["acir_available"] is False
    assert rows["neverCompiled/v1.0.0"]["acir_url"] == "/api/v1/circuits/neverCompiled/v1.0.0/acir"   # kept for clients


def test_an_uncompiled_circuit_is_a_404_that_names_what_is_served(two_circuits):
    with pytest.raises(HTTPException) as e:
        asyncio.run(A.get_circuit_acir("neverCompiled/v1.0.0"))
    assert e.value.status_code == 404 and "no compiled ACIR bytecode" in e.value.detail and "source" in e.value.detail
    assert asyncio.run(A.get_circuit_acir("compiled/v1.0.0")).body == b"\x00acir"


def test_the_list_detail_probe_asks_only_circuits_with_bytecode():
    from agentvault_registry.api_tests.contracts import list_detail as LD
    pair = next(p for p in LD.PAIRS if p.detail_tool == "theprotocol_getCircuitACIR")
    assert ("acir_available", True) in pair.row_where
