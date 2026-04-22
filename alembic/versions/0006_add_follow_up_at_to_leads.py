"""add follow_up_at to leads

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('leads', sa.Column('follow_up_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('leads', 'follow_up_at')
