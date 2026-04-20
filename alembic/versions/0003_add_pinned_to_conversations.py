"""add pinned to conversations

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002_phase7_dashboard'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'conversations',
        sa.Column('pinned', sa.Boolean(), nullable=True, server_default='false')
    )


def downgrade():
    op.drop_column('conversations', 'pinned')
