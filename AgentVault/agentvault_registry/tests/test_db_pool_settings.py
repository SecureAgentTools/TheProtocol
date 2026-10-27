"""§MCPTEST30 (V0527, 2026-10-01) — the database pool per process comes from DB_POOL_SIZE / DB_MAX_OVERFLOW.

Round 9 on sbx-alpha (V0525): 9 workers x pool_size 40 (a literal) held all 100 of the database's connections idle and
it refused new ones ("too many clients"). The defaults are unchanged; a frame can now size its pool.
"""
from __future__ import annotations

import logging

from agentvault_registry.database import pool_settings


def test_the_defaults_are_unchanged():
    assert pool_settings({}) == (40, 40)


def test_a_frame_sizes_its_pool():
    assert pool_settings({"DB_POOL_SIZE": "5", "DB_MAX_OVERFLOW": "5"}) == (5, 5)
    assert pool_settings({"DB_POOL_SIZE": " 8 ", "DB_MAX_OVERFLOW": "0"}) == (8, 0)


def test_a_bad_value_falls_back_loudly(caplog):
    with caplog.at_level(logging.ERROR):
        assert pool_settings({"DB_POOL_SIZE": "lots", "DB_MAX_OVERFLOW": "-3"}) == (40, 40)
        assert pool_settings({"DB_POOL_SIZE": "0"}) == (40, 40)   # a pool that keeps nothing
    assert sum("is not a whole number" in r.message for r in caplog.records) == 2
    assert any("keeps no connection" in r.message for r in caplog.records)
