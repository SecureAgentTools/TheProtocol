"""SF-3: Token Bridge — cross-frame wrapped token transfers

Creates bridge_transactions table to track cross-frame AVT transfers
using the escrow + mint model (Option B).

State machine: INITIATED → LOCKED → MINTED → COMPLETED | FAILED | EXPIRED
"""

revision = '0005_token_bridge'
down_revision = '0004_agent_mtls'

from alembic import op
import sqlalchemy as sa


def upgrade():
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bridge_transactions' in inspector.get_table_names():
        return  # Table already exists (idempotent)
    op.create_table(
        'bridge_transactions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('source_frame_id', sa.String(), nullable=False),
        sa.Column('target_frame_id', sa.String(), nullable=False),
        sa.Column('source_agent_did', sa.String(), nullable=False),
        sa.Column('target_agent_did', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=30, scale=6), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='INITIATED'),
        sa.Column('direction', sa.String(20), nullable=False, server_default='outbound'),
        sa.Column('lock_tx_id', sa.String(), nullable=True),
        sa.Column('mint_tx_id', sa.String(), nullable=True),
        sa.Column('unlock_tx_id', sa.String(), nullable=True),
        sa.Column('burn_tx_id', sa.String(), nullable=True),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.String(1000), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bridge_tx_status', 'bridge_transactions', ['status'])
    op.create_index('ix_bridge_tx_source_agent', 'bridge_transactions', ['source_agent_did'])
    op.create_index('ix_bridge_tx_target_agent', 'bridge_transactions', ['target_agent_did'])
    op.create_index('ix_bridge_tx_idempotency', 'bridge_transactions', ['idempotency_key'],
                     unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"))


def downgrade():
    op.drop_table('bridge_transactions')
