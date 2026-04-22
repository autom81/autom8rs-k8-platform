"""add confirmed_at and delivered_at to orders

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-21
"""
from alembic import op
from sqlalchemy import text

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(text("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ NULL
    """))
    op.execute(text("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ NULL
    """))


def downgrade():
    op.execute(text("ALTER TABLE orders DROP COLUMN IF EXISTS confirmed_at"))
    op.execute(text("ALTER TABLE orders DROP COLUMN IF EXISTS delivered_at"))
