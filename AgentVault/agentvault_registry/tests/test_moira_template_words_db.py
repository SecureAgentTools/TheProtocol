"""W2 (2026-10-25, agentvault2-66): migration 0197 rewords the seeded MOIRA template, its row and its .tpb file alike.

0076 seeded `sovereign-moira-v1` as an insurance pattern; MOIRA is a risk analyst now. The template a developer browses
(the row) and forks (the .tpb: manifest, README, agent payload) must both say so, and the other five templates must not
move. Driven through alembic's own Operations on a REAL Postgres (0075 makes agent_bundles): 0076's upgrade seeds the six, 0197's upgrade rewords
one, its downgrade puts 0076's words back. THE PRECONDITION is asserted too (0076's file does carry the words), so the
test cannot pass by reading the wrong file. THE CONTROL: on a registry 0076 never seeded, 0197 changes nothing.

Skipped unless MEMBERSHIP_TEST_DB names a throwaway database it may WIPE.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

DB = os.environ.get("MEMBERSHIP_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
SLUG = "sovereign-moira-v1"
WORDS = ("insurance", "premium", "underwrit", "bookie", "claim", "policy", "policies")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(sync_conn, module, fn: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(sync_conn)):
        getattr(module, fn)()


@pytest.fixture
async def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("BUNDLE_STORAGE_DIR", str(tmp_path))
    from agentvault_registry.models import Base
    eng = create_async_engine(DB)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    await _migrate(eng, _load("0075_bdl_bundles_core"), "upgrade")   # agent_bundles is 0075's own DDL, not the models'
    yield eng
    await eng.dispose()


async def _migrate(eng, module, fn):
    async with eng.begin() as conn:
        await conn.run_sync(lambda c: _run(c, module, fn))


async def _rows(eng):
    async with eng.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT slug, name, description, category, manifest_json, bundle_sha256, bundle_size_bytes, storage_key "
            "FROM agent_bundles WHERE is_official = TRUE"))).all()
    return {r.slug: r for r in rows}


def _tpb(storage: Path, key: str):
    raw = (storage / key).read_bytes()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        return raw, {m.name: tar.extractfile(m).read().decode() for m in tar.getmembers() if m.isfile()}


def _said(row, files) -> str:
    manifest = row.manifest_json if isinstance(row.manifest_json, str) else json.dumps(row.manifest_json)
    return " ".join([row.name, row.description, row.category, manifest, json.dumps(files)]).lower()


async def test_the_moira_template_is_reworded_in_its_row_and_its_file_and_back(engine, tmp_path):
    seed, words = _load("0076_bdl_seed_templates"), _load("0197_moira_template_words")
    await _migrate(engine, seed, "upgrade")
    before = await _rows(engine)
    assert SLUG in before and len(before) == len(seed.TEMPLATE_BLUEPRINTS), sorted(before)
    raw0, files0 = _tpb(tmp_path, before[SLUG].storage_key)
    assert [w for w in WORDS if w in _said(before[SLUG], files0)], "0076's template should carry the old words"

    await _migrate(engine, words, "upgrade")
    after = await _rows(engine)
    raw1, files1 = _tpb(tmp_path, after[SLUG].storage_key)
    left = [w for w in WORDS if w in _said(after[SLUG], files1)]
    assert not left, f"the reworded template still says {left}"
    assert "Risk Analyst" in after[SLUG].name and "Risk Analyst" in files1["README.md"]
    assert after[SLUG].category == "risk"
    assert after[SLUG].bundle_sha256 == hashlib.sha256(raw1).hexdigest() and after[SLUG].bundle_size_bytes == len(raw1)
    assert after[SLUG].storage_key == before[SLUG].storage_key, "the file is rebuilt where the row points"
    for slug, row in before.items():
        if slug != SLUG:
            assert (after[slug].description, after[slug].bundle_sha256) == (row.description, row.bundle_sha256), slug

    await _migrate(engine, words, "downgrade")
    back = (await _rows(engine))[SLUG]
    raw2, files2 = _tpb(tmp_path, back.storage_key)
    assert (back.name, back.description, back.category) == (before[SLUG].name, before[SLUG].description,
                                                             before[SLUG].category)
    assert files2["README.md"] == files0["README.md"]
    assert back.bundle_sha256 == hashlib.sha256(raw2).hexdigest()


async def test_control_a_registry_0076_never_seeded_is_left_alone(engine):
    await _migrate(engine, _load("0197_moira_template_words"), "upgrade")
    assert await _rows(engine) == {}
