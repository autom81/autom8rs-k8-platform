"""add tags system

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tagtypeenum') THEN
                CREATE TYPE tagtypeenum AS ENUM ('auto', 'manual');
            END IF;
        END $$;
    """)

    op.create_table(
        'tags',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('name', sa.String(30), nullable=False),
        sa.Column('color', sa.String(7), nullable=False, server_default='#6B7280'),
        sa.Column('tag_type', sa.Enum('auto', 'manual', name='tagtypeenum'),
                  nullable=False, server_default='manual'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('business_id', 'name', name='uq_tags_business_name'),
    )
    op.create_index('ix_tags_business_id', 'tags', ['business_id'])

    op.create_table(
        'lead_tags',
        sa.Column('lead_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('leads.id'), primary_key=True),
        sa.Column('tag_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tags.id'), primary_key=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('applied_by', sa.String(50), nullable=True),
    )
    op.create_index('ix_lead_tags_lead_id', 'lead_tags', ['lead_id'])
    op.create_index('ix_lead_tags_tag_id', 'lead_tags', ['tag_id'])


def downgrade():
    op.drop_index('ix_lead_tags_tag_id', 'lead_tags')
    op.drop_index('ix_lead_tags_lead_id', 'lead_tags')
    op.drop_table('lead_tags')
    op.drop_index('ix_tags_business_id', 'tags')
    op.drop_table('tags')
    op.execute("DROP TYPE IF EXISTS tagtypeenum")
