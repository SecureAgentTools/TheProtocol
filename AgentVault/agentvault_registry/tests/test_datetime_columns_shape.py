"""§LEGALKIT (2026-09-20, measured on EU): asyncpg binds a datetime in the shape the SERVER parameter has. A typed ORM
bind (`DateTime(timezone=True)`) is sent as timestamptz and Postgres casts it into a naive column; an untyped `text()`
bind infers the column's type and REFUSES an aware value on a naive column (the V0412 retention worker). The live
database holds five naive columns (developers.two_fa_verified_at, developers.two_fa_last_failure,
security_audit_logs.timestamp, token_revocations.revoked_at, token_revocations.token_exp) against 414 timestamptz.

This pins the convention going forward: every DateTime column an ORM model in the registry's metadata declares is
timezone-aware, so a new naive model cannot appear unnoticed; the two `developers.two_fa_*` columns are aware in the
model and naive in the database (harmless through the ORM's typed bind), a migration for another day, named here."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from sqlalchemy import DateTime  # noqa: E402

from agentvault_registry import models  # noqa: E402,F401
from agentvault_registry.database import Base  # noqa: E402

KNOWN_NAIVE_IN_DB = {"developers.two_fa_verified_at", "developers.two_fa_last_failure"}


def test_every_model_datetime_column_is_timezone_aware():
    naive = sorted(f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in t.columns
                   if isinstance(c.type, DateTime) and not c.type.timezone)
    assert naive == [], f"naive DateTime columns declared by models (the convention is timezone=True): {naive}"


def test_the_named_naive_db_columns_exist_in_the_model():
    cols = {f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in t.columns}
    assert KNOWN_NAIVE_IN_DB <= cols


def test_the_audit_log_model_is_naive_on_purpose_and_its_worker_agrees():
    from agentvault_registry.security_oauth.audit_logger import SecurityAuditLog
    from agentvault_registry.background_tasks import audit_retention_worker as w
    col = SecurityAuditLog.__table__.c["timestamp"]
    assert col.type.timezone is False          # §pass47 C4: the column is TIMESTAMP WITHOUT TIME ZONE, written naive UTC
    assert w.cutoff_for().tzinfo is None       # the text()-bound cutoff takes the column's shape
