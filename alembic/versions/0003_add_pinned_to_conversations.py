"""add pinned to conversations

Revision ID: 0003
Revises: 0002_phase7_dashboard
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = '0003'
down_revision = '0002_phase7_dashboard'
branch_labels = None
depends_on = None


def upgrade():
    # Use IF NOT EXISTS so this is safe to run multiple times
    op.execute(text("""
        ALTER TABLE conversations
        ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT false
    """))


def downgrade():
    op.execute(text("""
        ALTER TABLE conversations
        DROP COLUMN IF EXISTS pinned
    """))
