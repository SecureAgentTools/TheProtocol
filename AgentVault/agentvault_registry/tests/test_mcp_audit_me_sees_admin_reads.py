"""An admin read of a developer's MCP audit log is written with the ADMIN as actor and the developer as
target. `/me/mcp-audit-log` used to filter on the actor alone, so the row the privacy model promised the
developer ("admin reads are visible to the developer being read") was stored and never returned. The query
is now a pure builder; these tests compile it, so the ordering and both branches are pinned without a DB."""
import datetime
import json
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import mcp_audit_log as mal
from agentvault_registry.security_oauth.audit_logger import SecurityAuditLog, SecurityEventType


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_me_query_returns_my_calls_and_admin_reads_of_me():
    sql = _sql(mal.my_mcp_audit_stmt("42", 50))
    # my own MCP rows, by actor
    assert "security_audit_logs.actor_id = '42'" in sql
    # and every admin read that names me as its target
    assert "security_audit_logs.target_id = '42'" in sql
    assert "security_audit_logs.target_type = 'developer_audit_log'" in sql
    assert "ADMIN_READ_MCP_AUDIT" in sql.upper()
    assert " OR " in sql
    assert "ORDER BY security_audit_logs.timestamp DESC" in sql


def test_the_cursor_narrows_both_branches():
    before = datetime.datetime(2026, 9, 25, 12, 0, 0)
    sql = _sql(mal.my_mcp_audit_stmt("42", 50, before))
    assert "security_audit_logs.timestamp <" in sql
    # the timestamp bound sits outside the OR, so it narrows my calls and the admin reads alike
    assert sql.index("security_audit_logs.timestamp <") > sql.index(" OR ")


def test_control_the_old_actor_only_filter_cannot_see_an_admin_read():
    """The shape the endpoint had before: an admin read of developer 42 is written with actor 7 and never matches."""
    from sqlalchemy import select
    old_where = _sql(select(SecurityAuditLog).where(SecurityAuditLog.actor_id == "42")).split("WHERE ", 1)[1]
    assert "target_id" not in old_where
    new_where = _sql(mal.my_mcp_audit_stmt("42", 50)).split("WHERE ", 1)[1]
    assert "security_audit_logs.target_id = '42'" in new_where


def _row(actor_id, target_id, event_type, details):
    return SimpleNamespace(
        id="r1", timestamp=datetime.datetime(2026, 9, 25, 12, 0, 0), event_type=event_type,
        actor_type="admin", actor_id=actor_id, actor_ip=None, target_type="developer_audit_log",
        target_id=target_id, outcome="success", severity="info", request_id=None, user_agent=None,
        details=json.dumps(details), error_message=None,
    )


def test_the_subject_sees_who_and_when_but_not_the_admins_email():
    row = _row("7", "42", SecurityEventType.ADMIN_READ_MCP_AUDIT, {"admin_email": "ops@example.com", "requested_limit": 50})
    out = mal._serialize_for_subject(row, "42")
    assert out["actor_id"] == "7" and out["target_id"] == "42"
    assert "admin_email" not in out["details"]
    assert out["details"]["requested_limit"] == 50


def test_my_own_rows_keep_their_details():
    row = _row("42", "tool", SecurityEventType.MCP_TOOL_INVOKED, {"tier": "T2", "admin_email": "kept-because-mine"})
    out = mal._serialize_for_subject(row, "42")
    assert out["details"]["admin_email"] == "kept-because-mine"
