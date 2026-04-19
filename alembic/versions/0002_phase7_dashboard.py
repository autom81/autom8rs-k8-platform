"""Phase 7A Step 1: Users and broadcast tables for dashboard

Revision ID: 0002_phase7_dashboard
Revises: 0001_phase6_initial
Create Date: 2026-04-18

Creates:
1. users - dashboard login accounts per business
2. broadcast_templates - WhatsApp template definitions
3. broadcasts - broadcast campaign records
4. broadcast_recipients - per-recipient delivery tracking
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0002_phase7_dashboard'
down_revision: Union[str, None] = '0001_phase6_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create Phase 7A dashboard tables."""

    # ========================================================================
    # 1. USERS TABLE
    # ========================================================================

    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('role', sa.String(length=50), nullable=True, server_default='member'),
        sa.Column(
            'permissions',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("""
                '{"can_reply": true, "can_manage_products": false, "can_manage_orders": false, "can_view_analytics": false, "can_edit_settings": false}'::jsonb
            """)
        ),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('invited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_users_email'),
    )
    # Self-referential FK added after table creation
    op.create_foreign_key(
        'fk_users_invited_by',
        'users', 'users',
        ['invited_by'], ['id'],
        ondelete='SET NULL'
    )

    op.create_index('idx_users_business', 'users', ['business_id'])
    op.create_index('idx_users_email', 'users', ['email'])

    # ========================================================================
    # 2. BROADCAST_TEMPLATES TABLE
    # ========================================================================

    op.create_table(
        'broadcast_templates',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('body_text', sa.Text(), nullable=False),
        sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('meta_template_name', sa.String(length=255), nullable=True),
        sa.Column('meta_status', sa.String(length=50), nullable=True, server_default='pending'),
        sa.Column('meta_rejection_reason', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('idx_broadcast_templates_business', 'broadcast_templates', ['business_id'])

    # ========================================================================
    # 3. BROADCASTS TABLE
    # ========================================================================

    op.create_table(
        'broadcasts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=True, server_default='draft'),
        sa.Column('audience_filter', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('recipient_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('sent_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('delivered_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('read_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['broadcast_templates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('idx_broadcasts_business', 'broadcasts', ['business_id'])
    op.create_index('idx_broadcasts_status', 'broadcasts', ['status'])

    # ========================================================================
    # 4. BROADCAST_RECIPIENTS TABLE
    # ========================================================================

    op.create_table(
        'broadcast_recipients',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('broadcast_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, server_default='pending'),
        sa.Column('meta_message_id', sa.String(length=255), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['broadcast_id'], ['broadcasts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('idx_broadcast_recipients_broadcast', 'broadcast_recipients', ['broadcast_id'])
    op.create_index('idx_broadcast_recipients_status', 'broadcast_recipients', ['status'])


def downgrade() -> None:
    """Drop Phase 7A dashboard tables."""

    # Drop in reverse dependency order
    op.drop_index('idx_broadcast_recipients_status', table_name='broadcast_recipients')
    op.drop_index('idx_broadcast_recipients_broadcast', table_name='broadcast_recipients')
    op.drop_table('broadcast_recipients')

    op.drop_index('idx_broadcasts_status', table_name='broadcasts')
    op.drop_index('idx_broadcasts_business', table_name='broadcasts')
    op.drop_table('broadcasts')

    op.drop_index('idx_broadcast_templates_business', table_name='broadcast_templates')
    op.drop_table('broadcast_templates')

    op.drop_index('idx_users_email', table_name='users')
    op.drop_index('idx_users_business', table_name='users')
    op.drop_constraint('fk_users_invited_by', 'users', type_='foreignkey')
    op.drop_table('users')
