"""Add event_emission_policies rows for the CI/CD service (§pass47 A1).

Revision ID: 0064_cicd_events
Revises: 0063_agent_signing_keys
Create Date: 2026-05-19

Background
----------
`AGENTS/agentvault_registry/src/agentvault_registry/services/agent_cicd_service.py`
now emits 8 audit events for its lifecycle operations (pipeline create/
update/delete, version create/activate/rollback, deployment trigger/status).

All 8 are emit_from_registry=true · emit_from_teg=false · skip_in_projection=true
because the CI/CD service touches no balances — these rows are pure audit
trail for downstream reactors (B5 drift-remediation, future approval flows).

The event_emitter.py policy gate is currently **fail-open** for unknown
event types (see CLAUDE.md PART 3 "Gate behavior"), so these rows aren't
strictly required for emission to function; they are required for the
emission to be **policy-recorded** (audit consistency) and for future
when the gate becomes fail-closed.

Idempotent via ON CONFLICT DO NOTHING. Downgrade removes the rows.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0064_cicd_events"
down_revision: Union[str, None] = "0063_agent_signing_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TYPES = (
    "PipelineCreated",
    "PipelineUpdated",
    "PipelineDeleted",
    "VersionCreated",
    "VersionActivated",
    "VersionRolledBack",
    "DeploymentTriggered",
    "DeploymentStatusUpdated",
    "DeploymentWebhookExhausted",  # §pass47 A7 — fires when retry exhausted
)


def upgrade() -> None:
    bind = op.get_bind()
    for evt in _NEW_TYPES:
        bind.execute(text("""
            INSERT INTO event_emission_policies
                (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
            VALUES (:evt, false, true, true)
            ON CONFLICT (event_type) DO NOTHING;
        """), {"evt": evt})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "DELETE FROM event_emission_policies WHERE event_type IN ("
        + ",".join(f"'{t}'" for t in _NEW_TYPES)
        + ");"
    ))
