"""add bot_paused to conversations

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-21
"""
from alembic import op
from sqlalchemy import text

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(text("""
        ALTER TABLE conversations
        ADD COLUMN IF NOT EXISTS bot_paused BOOLEAN NOT NULL DEFAULT false
    """))


def downgrade():
    op.execute(text("""
        ALTER TABLE conversations
        DROP COLUMN IF EXISTS bot_paused
    """))
