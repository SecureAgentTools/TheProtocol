"""§MCPTEST30 (2026-10-01) — the MCP tester reads its target database's connections against their ceiling at the end of
every complete run. agentvault2-eb measured sbx-alpha-db at 100 of 100 client backends after round 6: each registry
worker may hold pool_size + max_overflow connections (database.py: 40 + 40) against Postgres's 100, so eight workers can
hold 640, and a new connection fails as "too many clients" while every pooled one still answers."""
from __future__ import annotations

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def test_the_worker_count_is_read_off_the_masters_command_line():
    assert F.workers_from_args(["gunicorn", "app:app", "--workers", "8", "-c", "conf.py"]) == 8
    assert F.workers_from_args(["gunicorn", "-w", "4", "app:app"]) == 4
    assert F.workers_from_args(["gunicorn", "--workers=12", "app:app"]) == 12
    assert F.workers_from_args(["uvicorn", "app:app"]) is None


def test_a_database_at_its_ceiling_is_red_and_one_with_headroom_is_not():
    assert F.db_headroom_verdict(42, 100, 3, 640) == (True, None)
    healthy, sentence = F.db_headroom_verdict(100, 100, 3, 640)
    assert healthy is False and sentence.startswith("BUG-FIND: db headroom:") and "holds 100 of 100" in sentence
    assert "can hold 640" in sentence
    assert F.db_headroom_verdict(95, 100, 3, None)[0] is False, "within two of the usable ceiling is at it"
    assert F.db_headroom_verdict(94, 100, 3, None)[0] is True
