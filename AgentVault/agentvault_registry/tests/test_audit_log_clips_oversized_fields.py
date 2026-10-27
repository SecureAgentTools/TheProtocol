"""§MCPTEST30 (V0545) — an oversized field is clipped into the security audit row, never the reason the row is lost.

One tester sweep lost an `admin_read_mcp_audit` row on sbx-alpha (2026-10-02 04:07:41Z): the actor it asked to read was a
300-character probe value, `target_id` is varchar(255), the INSERT failed, and the writer logged the INSERT's parameters
and left the caller's session unusable (the route's next write failed with "This Session's transaction has been rolled
back due to a previous exception during flush"). Any caller could keep its own call out of the log the same way.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from agentvault_registry.security_oauth import audit_logger as A


class _Session:
    def __init__(self, fail: Exception | None = None):
        self.added, self.committed, self.rolled_back, self.fail = [], 0, 0, fail

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        if self.fail:
            raise self.fail
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


def _log(db, **over):
    kw = dict(event_type=A.SecurityEventType.ADMIN_READ_MCP_AUDIT, action="read", outcome="success", actor_type="admin",
              actor_id="2", target_type="developer_audit_log", target_id="7")
    kw.update(over)
    asyncio.run(A.SecurityAuditor().log_event(db, **kw))


def test_clipping_keeps_the_head_marks_the_cut_and_names_the_column():
    vals = {"target_id": "p" * 300, "request_id": "r" * 50, "actor_id": "2", "outcome": "success", "error_message": None}
    clipped = A.clip_to_columns(vals)
    assert len(vals["target_id"]) == 255 and vals["target_id"].endswith("…") and vals["target_id"][:254] == "p" * 254
    assert len(vals["request_id"]) == 36
    assert vals["actor_id"] == "2" and vals["outcome"] == "success" and vals["error_message"] is None
    assert clipped == [{"column": "target_id", "length": 300}, {"column": "request_id", "length": 50}]


def test_an_oversized_target_still_writes_the_row_and_says_it_was_clipped():
    db = _Session()
    _log(db, target_id="p" * 300, details={"limit": 10})
    assert db.committed == 1 and len(db.added) == 1
    row = db.added[0]
    assert len(row.target_id) == 255
    assert json.loads(row.details) == {"limit": 10, "clipped": [{"column": "target_id", "length": 300}]}


def test_a_row_that_fits_is_written_as_before():
    db = _Session()
    _log(db, details={"limit": 10})
    row = db.added[0]
    assert row.target_id == "7" and json.loads(row.details) == {"limit": 10}


def test_a_failed_write_rolls_the_session_back_and_logs_one_line_without_the_parameters(caplog):
    caplog.set_level(logging.DEBUG, logger=A.logger.name)
    boom = RuntimeError("(asyncpg.Error) the database is gone\n[SQL: INSERT INTO security_audit_logs ...]\n"
                        "[parameters: ('a-value-that-must-not-reach-the-log',)]")
    db = _Session(fail=boom)
    _log(db)
    assert db.rolled_back == 1, "the caller's session is usable again"
    errs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs == ["Failed to write security audit log (admin_read_mcp_audit): RuntimeError: (asyncpg.Error) the "
                    "database is gone"], errs


def test_details_that_json_cannot_encode_do_not_lose_the_row():
    db = _Session()

    class _Thing:
        def __str__(self):
            return "thing"
    _log(db, details={"obj": _Thing()})
    assert db.committed == 1 and json.loads(db.added[0].details) == {"obj": "thing"}


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
