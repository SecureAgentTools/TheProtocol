"""D6-815 (2026-10-24) — contracts.origin_ref holds a DID as long as the DID columns beside it (migration 0195).

engage_agent passes the engaged agent's DID as origin_ref; the column was String(80) beside String(120) DID columns, and
agentvault2-aa's V0636 pair proof engaged agents whose DIDs are 82 characters: "value too long for type character
varying(80)", HTTP 500. The model and the migration are pinned here; the graph (one head) is CI's migrations job.
"""
from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

from agentvault_registry.models import Contract

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
PAIR_DID = "did:theprotocol:nt261024x2a.theprotocol.cloud:0b8a5d2e-7c1f-4e6a-9d3b-2f4c6e8a1b3d"   # 82 characters


def _migration():
    spec = importlib.util.spec_from_file_location("m0195", VERSIONS / "0195_contract_origin_ref_120.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Op:
    """Records alter_column; answers the downgrade's count with `longer`."""

    def __init__(self, longer=0):
        self.calls, self.longer = [], longer

    def alter_column(self, table, column, **kw):
        self.calls.append((table, column, kw["type_"].length, kw["existing_type"].length))

    def get_bind(self):
        outer = self
        return SimpleNamespace(execute=lambda stmt: SimpleNamespace(scalar=lambda: outer.longer))


def test_the_pair_did_that_failed_is_longer_than_the_old_column():
    """Control: the DID the proof engaged really did not fit."""
    assert len(PAIR_DID) == 82 > 80


def test_origin_ref_is_as_wide_as_the_did_columns_beside_it():
    c = Contract.__table__.c
    assert c.origin_ref.type.length == c.client_did.type.length == c.provider_did.type.length == 120
    assert len(PAIR_DID) <= c.origin_ref.type.length


def test_the_upgrade_widens_the_one_column_to_120(monkeypatch):
    m = _migration()
    op = _Op()
    monkeypatch.setattr(m, "op", op)
    m.upgrade()
    assert op.calls == [("contracts", "origin_ref", 120, 80)]


def test_the_downgrade_narrows_back_while_nothing_is_longer(monkeypatch):
    m = _migration()
    op = _Op(longer=0)
    monkeypatch.setattr(m, "op", op)
    m.downgrade()
    assert op.calls == [("contracts", "origin_ref", 80, 120)]


def test_the_downgrade_refuses_while_a_longer_origin_ref_exists(monkeypatch):
    m = _migration()
    op = _Op(longer=3)
    monkeypatch.setattr(m, "op", op)
    with pytest.raises(RuntimeError, match="3 contract"):
        m.downgrade()
    assert op.calls == []


def test_the_revision_follows_0194_and_fits_the_version_column():
    m = _migration()
    assert m.down_revision == "0194_delivery_xreg_revoke" and m.revision == "0195_contract_origin_ref_120"
    assert len(m.revision) <= 32
