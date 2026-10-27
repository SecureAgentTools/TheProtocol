"""§LEGALKIT (F5): the purge statement is the cap Privacy § 4.2 publishes, bounded per batch, bound by parameter."""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.background_tasks import audit_retention_worker as w  # noqa: E402


def test_purge_statement_shape():
    sql = str(w.purge_statement())
    assert sql.startswith("DELETE FROM security_audit_logs WHERE id IN (")
    assert 'WHERE "timestamp" < :cutoff' in sql and "LIMIT :batch" in sql and 'ORDER BY "timestamp" ASC' in sql
    # bound, never formatted: no date literal can sit in the text
    assert "2026" not in sql and "now()" not in sql.lower()


def test_cutoff_is_the_published_cap(monkeypatch):
    monkeypatch.delenv("AUDIT_LOG_RETENTION_DAYS", raising=False)
    now = datetime(2027, 5, 19, tzinfo=timezone.utc)
    naive_now = datetime(2027, 5, 19)  # the cutoff is bound in the column's shape (naive UTC), see the test below
    assert w.cutoff_for(now) == naive_now - timedelta(days=365)
    monkeypatch.setenv("AUDIT_LOG_RETENTION_DAYS", "30")
    assert w.cutoff_for(now) == naive_now - timedelta(days=30)
    monkeypatch.setenv("AUDIT_LOG_RETENTION_DAYS", "junk")
    assert w.retention_days() == 365  # a broken value falls back to the cap the policy states, never to zero


def test_control_a_row_inside_the_window_is_not_past_the_cutoff():
    now = datetime(2027, 5, 19)  # the column's shape: naive UTC, like every row the registry writes there
    cutoff = w.cutoff_for(now)
    inside = now - timedelta(days=364)
    outside = now - timedelta(days=366)
    assert not (inside < cutoff) and (outside < cutoff)


def test_cutoff_takes_the_shape_of_the_column():
    """asyncpg binds a datetime in the column's shape or not at all (measured on EU, V0412's first cycle). The
    model is the source: a naive column gets a naive UTC cutoff; if the column ever becomes timezone-aware this
    test names the second place to change."""
    # The column is `timestamp without time zone` on every frame (0001_squash_initial; measured on EU, 55 rows), and
    # the model in security_oauth/audit_logger.py declares it naive on purpose (§pass47 C4). A text()-bound parameter
    # takes the column's shape (asyncpg infers it and refuses an aware value); a typed ORM bind would be cast.
    from agentvault_registry.security_oauth.audit_logger import SecurityAuditLog
    assert w.TIMESTAMP_COLUMN in SecurityAuditLog.__table__.c
    aware = datetime(2027, 5, 19, 12, 0, tzinfo=timezone.utc)
    cut = w.cutoff_for(aware, days=1)
    assert cut.tzinfo is None and cut == datetime(2027, 5, 18, 12, 0)
    assert w.cutoff_for().tzinfo is None
