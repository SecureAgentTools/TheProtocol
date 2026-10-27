"""§R55 (batch 2, 2026-09-05) — row-only state a peer gates on: developer verification.
The peer's shadow developer tracks the home's `developer_verified` on EVERY sync (it was consumed once,
at creation, and frozen); the home touches the developer's native cards when the flag flips so the
update ships on the next cycle. Structural gates + a receipt-asserting fake db for the touch.
"""
import os
import pathlib
import re

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

SRC = pathlib.Path(os.environ.get("R55_SRC", str(pathlib.Path(__file__).resolve().parent.parent / "src/agentvault_registry")))


def test_peer_update_branch_tracks_developer_verified():
    s = (SRC / "crud/crud_peer_registry.py").read_text()
    i = s.index("async def upsert_agent_cards_from_peer"); body = s[i:]
    assert "_dv_changed = bool(_shadow_dev.is_verified) != bool(agent_card.get('developer_verified'))" in body
    assert "and not _dv_changed" in body, "a flag-only change must not be reported 'unchanged'"
    assert "_shadow_dev.is_verified = bool(agent_card.get('developer_verified'))" in body


@pytest.mark.parametrize("rel,marker", [
    ("routers/auth_secure.py", "touch_developer_native_cards(db, developer.id"),
    ("routers/auth.py", "touch_developer_native_cards(db, developer.id"),
    ("routers/admin_developers.py", "touch_developer_native_cards(db, dev.id"),
])
def test_every_verification_writer_touches_the_native_cards(rel, marker):
    s = (SRC / rel).read_text()
    assert marker in s, f"{rel}: is_verified flips without touching the developer's cards"


@pytest.mark.asyncio
async def test_touch_updates_only_native_active_cards_of_that_developer():
    from agentvault_registry.services.card_touch import touch_developer_native_cards
    seen = []
    class FakeRes:
        rowcount = 3
    class FakeDB:
        async def execute(self, stmt, params=None): seen.append((str(stmt), params)); return FakeRes()
        async def commit(self): seen.append(("commit", None))
    n = await touch_developer_native_cards(FakeDB(), 42, reason="test")
    assert n == 3 and seen[-1][0] == "commit"
    sql, params = seen[0]
    assert params == {"dev": 42}
    assert "UPDATE agent_cards SET updated_at = NOW()" in sql and "developer_id = :dev" in sql
    assert "is_active = TRUE" in sql and "federation_metadata,source_registry" in sql, "never a mirror, never an inactive card"


@pytest.mark.asyncio
async def test_touch_never_raises_into_the_rail():
    from agentvault_registry.services.card_touch import touch_developer_native_cards
    class BrokenDB:
        async def execute(self, *a, **k): raise RuntimeError("db down")
        async def commit(self): pass
    assert await touch_developer_native_cards(BrokenDB(), 1) == 0
