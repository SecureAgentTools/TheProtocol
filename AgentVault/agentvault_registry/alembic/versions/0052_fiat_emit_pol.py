"""Add event_emission_policies rows for PB-3 new event types.

Revision ID: 0052_fiat_emit_pol
Revises: 0051_fiat_webhook_logs
Create Date: 2026-05-12

PB-3 (BL-2) Webhook Fiat Layer — W1 emission policy seed rows.

Adds explicit emission policies for three new event types introduced by PB-3:

  - FiatPurchaseDisputed       counted   emit_from_registry=true
  - FiatPurchaseFailed         counted   emit_from_registry=true
  - FiatProviderSignatureFailed counted  emit_from_registry=true (security audit)

Default emission policy is permissive (allow), but being explicit here
makes the audit trail intent visible in the policy table.

All three are counted (skip_in_projection=false) since they don't
correspond to AVT motion (which is already counted via TokensTransferred
when relevant). Strategy §5.4 + §A.3 cross-table sync invariants.

Raw SQL + ON CONFLICT DO NOTHING for idempotency.

Revision-id length: 18 chars.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0052_fiat_emit_pol"
down_revision: Union[str, None] = "0051_fiat_webhook_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # FiatPurchaseDisputed — chargeback / dispute opened.
    # Counted because dispute is a real audit event (not a TokensTransferred wrapper).
    bind.execute(text("""
        INSERT INTO event_emission_policies (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('FiatPurchaseDisputed', false, true, false)
        ON CONFLICT (event_type) DO NOTHING;
    """))

    # FiatPurchaseFailed — PSP rejected / expired / anonymous-flow collision.
    # Counted as audit trail.
    bind.execute(text("""
        INSERT INTO event_emission_policies (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('FiatPurchaseFailed', false, true, false)
        ON CONFLICT (event_type) DO NOTHING;
    """))

    # FiatProviderSignatureFailed — security audit trail when a PSP signature
    # verification fails. Counted because it's an attack-detection event.
    bind.execute(text("""
        INSERT INTO event_emission_policies (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('FiatProviderSignatureFailed', false, true, false)
        ON CONFLICT (event_type) DO NOTHING;
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type IN (
            'FiatPurchaseDisputed',
            'FiatPurchaseFailed',
            'FiatProviderSignatureFailed'
        );
    """))
