"""§MCPTEST30 (2026-10-01) — one read rule for a bundle by id: manifest, download and restore (every fork is a restore).

The MCP tester's owner-scoping sweep found a second developer reading the manifest of another developer's PRIVATE
snapshot on sbx-alpha (13 of the owner's 13 values); reading the code beside it found restore_bundle loading any bundle
by id, so a fork turned a stranger's private snapshot into copies of its agents in the forker's account. The rule
(owner: any of theirs; anybody: public or official; nobody: hidden) is bundle_visible_to; a bundle the caller may not
see answers as one that does not exist, and its bytes are never read. Since D6-481 an 'org' bundle is also read by its
organization's owner, admins and members (org_reader_of; tests/test_org_bundle_visibility.py), which a row without an
organization never asks.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from agentvault_registry.services.bundles import service as S

OWNER, STRANGER = 7, 8


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row

    def scalar(self):
        return self._row


class FakeDB:
    """Answers the by-id SELECT with one row shaped as each caller selects it; records UPDATEs."""

    def __init__(self, *, source_dev_id=OWNER, visibility="private", is_official=False, is_hidden=False, exists=True,
                 source_org_id=None):
        self.b = dict(source_dev_id=source_dev_id, visibility=visibility, is_official=is_official, is_hidden=is_hidden,
                      source_org_id=source_org_id)
        self.exists, self.updates = exists, []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.strip().upper().startswith("UPDATE"):
            self.updates.append(sql)
            return _Result(None)
        if not self.exists:
            return _Result(None)
        b = self.b
        if "SELECT manifest_json" in sql:
            return _Result(({"bundle_kind": "snapshot"}, b["source_dev_id"], b["visibility"], b["is_official"], b["is_hidden"],
                            b["source_org_id"]))
        if "SELECT storage_key, source_dev_id" in sql:
            return _Result(("key-1", b["source_dev_id"], b["visibility"], b["is_official"], b["is_hidden"],
                            b["source_org_id"]))
        if "SELECT id, storage_key, source_dev_id" in sql:
            return _Result(("bnd-1", "key-1", b["source_dev_id"], b["visibility"], b["is_official"], b["is_hidden"],
                            b["source_org_id"]))
        raise AssertionError(f"unexpected SQL: {sql[:80]}")

    async def commit(self):
        return None


class FakeStorage:
    def __init__(self):
        self.reads = 0

    async def read(self, key):
        self.reads += 1
        raise RuntimeError("stop after the read: the restore itself is not under test")


@pytest.mark.parametrize("kw,owner_sees,stranger_sees", [
    (dict(visibility="private"), True, False),
    (dict(visibility="org"), True, False),
    (dict(visibility="public"), True, True),
    (dict(visibility="private", is_official=True), True, True),
    (dict(visibility="public", is_hidden=True), False, False),
])
def test_the_rule(kw, owner_sees, stranger_sees):
    args = (OWNER, kw.get("visibility"), kw.get("is_official", False), kw.get("is_hidden", False))
    assert S.bundle_visible_to(*args, OWNER) is owner_sees
    assert S.bundle_visible_to(*args, STRANGER) is stranger_sees
    assert S.bundle_visible_to(*args, None) is (stranger_sees and not kw.get("is_hidden", False))


def test_a_private_manifest_is_the_owners_only():
    assert asyncio.run(S.get_manifest(FakeDB(), "bnd-1", OWNER)) == {"bundle_kind": "snapshot"}
    assert asyncio.run(S.get_manifest(FakeDB(), "bnd-1", STRANGER)) is None
    assert asyncio.run(S.get_manifest(FakeDB(visibility="public"), "bnd-1", STRANGER)) == {"bundle_kind": "snapshot"}
    assert asyncio.run(S.get_manifest(FakeDB(), "bnd-1")) is None, "no caller named is nobody's owner"


def test_a_stranger_cannot_restore_or_fork_a_private_bundle_and_its_bytes_are_never_read(monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr(S, "get_bundle_storage", lambda: storage)
    out = asyncio.run(S.restore_bundle(db=FakeDB(), installer_dev_id=STRANGER, bundle_row_id="bnd-1"))
    assert out["success"] is False and out["errors"] == ["Bundle not found"] and storage.reads == 0
    # control: the same row as the OWNER (or a public one) goes on to read the bytes
    with pytest.raises(RuntimeError, match="stop after the read"):
        asyncio.run(S.restore_bundle(db=FakeDB(), installer_dev_id=OWNER, bundle_row_id="bnd-1"))
    with pytest.raises(RuntimeError, match="stop after the read"):
        asyncio.run(S.restore_bundle(db=FakeDB(visibility="public"), installer_dev_id=STRANGER, bundle_row_id="bnd-1"))
    assert storage.reads == 2


def test_a_hidden_bundle_downloads_for_nobody_and_counts_nothing(monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr(S, "get_bundle_storage", lambda: storage)
    db = FakeDB(is_hidden=True)
    assert asyncio.run(S.download_bytes(db, "bnd-1", OWNER)) is None and not db.updates and storage.reads == 0


def test_the_routes_name_the_caller():
    from agentvault_registry.routers import bundles as R
    src = inspect.getsource(R)
    assert "bundles_svc.get_manifest(db, bundle_id, current_developer.id)" in src
    assert src.count("installer_dev_id=") >= 4, "every restore names who installs"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
