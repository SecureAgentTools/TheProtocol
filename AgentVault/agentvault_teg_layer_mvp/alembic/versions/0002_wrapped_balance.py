"""SF-3: Add wrapped_balance to AgentTEGProfile for cross-frame bridge

Tracks wrapped-AVT received from other sovereign frames.
Used by the Wrapped Token Bridge (SF-3) for 1:1 cross-frame transfers.
"""

revision = '0002_wrapped_balance'
down_revision = '0001_teg_squash'

from alembic import op
import sqlalchemy as sa


def upgrade():
    from sqlalchemy import inspect
    bind = op.get_bind()
    columns = [c['name'] for c in inspect(bind).get_columns('agent_teg_profiles')]
    if 'wrapped_balance' not in columns:
        op.add_column('agent_teg_profiles',
            sa.Column('wrapped_balance', sa.Numeric(precision=36, scale=18),
                       nullable=False, server_default='0'))


def downgrade():
    op.drop_column('agent_teg_profiles', 'wrapped_balance')
