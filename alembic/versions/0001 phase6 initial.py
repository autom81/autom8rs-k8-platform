"""Phase 6: Function calling tools, Instagram sync, and caching infrastructure

Revision ID: 0001_phase6_initial
Revises: 
Create Date: 2026-04-18

This migration adds all database changes needed for Phase 6:

1. Businesses: features JSONB, order_prefix, category, brand_voice
2. Products: source, ingested_at, approved_at, approved_by, pending_review status
3. Leads: classification enum, interest_area, last_updated + expanded status enum
4. Orders: order_number, delivery_address, special_instructions, 
          shipped_at, cancelled_at, cancellation_reason
5. Conversations: message_count
6. NEW TABLE: appointments (for scheduling tool)
7. NEW TABLE: media_library (for Instagram media storage)
8. Performance indexes
9. TrendyProductsTT founding member configuration
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0001_phase6_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply Phase 6 schema changes."""
    
    # ========================================================================
    # 1. BUSINESSES TABLE - Add Phase 6 columns
    # ========================================================================
    
    op.add_column(
        'businesses',
        sa.Column(
            'features',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("""
                '{"ecommerce_enabled": true, "scheduling_enabled": false, "media_sync_enabled": true}'::jsonb
            """)
        )
    )
    
    op.add_column(
        'businesses',
        sa.Column('order_prefix', sa.String(length=10), nullable=True, server_default='ORD')
    )
    
    op.add_column(
        'businesses',
        sa.Column('category', sa.String(length=100), nullable=True)
    )
    
    op.add_column(
        'businesses',
        sa.Column('brand_voice', sa.Text(), nullable=True)
    )
    
    # ========================================================================
    # 2. PRODUCTS TABLE - Add Instagram sync columns
    # ========================================================================
    
    # First, add 'pending_review' to the existing ProductStatusEnum
    op.execute("ALTER TYPE productstatusenum ADD VALUE IF NOT EXISTS 'pending_review'")
    
    # Create new ProductSourceEnum type
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'productsourceenum') THEN
                CREATE TYPE productsourceenum AS ENUM ('manual', 'instagram', 'facebook', 'api');
            END IF;
        END$$;
    """)
    
    op.add_column(
        'products',
        sa.Column(
            'source',
            postgresql.ENUM('manual', 'instagram', 'facebook', 'api', name='productsourceenum', create_type=False),
            nullable=True,
            server_default='manual'
        )
    )
    
    op.add_column(
        'products',
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    op.add_column(
        'products',
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    op.add_column(
        'products',
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), nullable=True)
    )
    
    # ========================================================================
    # 3. LEADS TABLE - Add classification and expand status enum
    # ========================================================================
    
    # Add new values to existing LeadStatusEnum
    op.execute("ALTER TYPE leadstatusenum ADD VALUE IF NOT EXISTS 'attempted_contact'")
    op.execute("ALTER TYPE leadstatusenum ADD VALUE IF NOT EXISTS 'connected'")
    op.execute("ALTER TYPE leadstatusenum ADD VALUE IF NOT EXISTS 'nurture'")
    op.execute("ALTER TYPE leadstatusenum ADD VALUE IF NOT EXISTS 'unqualified'")
    
    # Create new LeadClassificationEnum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leadclassificationenum') THEN
                CREATE TYPE leadclassificationenum AS ENUM (
                    'hot', 'warm', 'cold', 'post_purchase', 'support', 'spam'
                );
            END IF;
        END$$;
    """)
    
    op.add_column(
        'leads',
        sa.Column(
            'classification',
            postgresql.ENUM(
                'hot', 'warm', 'cold', 'post_purchase', 'support', 'spam',
                name='leadclassificationenum',
                create_type=False
            ),
            nullable=True,
            server_default='cold'
        )
    )
    
    op.add_column(
        'leads',
        sa.Column('interest_area', sa.Text(), nullable=True)
    )
    
    op.add_column(
        'leads',
        sa.Column(
            'last_updated',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True
        )
    )
    
    # ========================================================================
    # 4. ORDERS TABLE - Add order tracking columns
    # ========================================================================
    
    op.add_column(
        'orders',
        sa.Column('order_number', sa.String(length=50), nullable=True)
    )
    op.create_unique_constraint('uq_orders_order_number', 'orders', ['order_number'])
    
    op.add_column(
        'orders',
        sa.Column('delivery_address', sa.Text(), nullable=True)
    )
    
    op.add_column(
        'orders',
        sa.Column('special_instructions', sa.Text(), nullable=True)
    )
    
    op.add_column(
        'orders',
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    op.add_column(
        'orders',
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True)
    )
    
    op.add_column(
        'orders',
        sa.Column('cancellation_reason', sa.Text(), nullable=True)
    )
    
    # ========================================================================
    # 5. CONVERSATIONS TABLE - Add message counter
    # ========================================================================
    
    op.add_column(
        'conversations',
        sa.Column('message_count', sa.Integer(), nullable=True, server_default='0')
    )
    
    # ========================================================================
    # 6. CREATE APPOINTMENTS TABLE
    # ========================================================================
    
    # Create AppointmentStatusEnum
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'appointmentstatusenum') THEN
                CREATE TYPE appointmentstatusenum AS ENUM (
                    'pending', 'confirmed', 'completed', 'cancelled'
                );
            END IF;
        END$$;
    """)
    
    op.create_table(
        'appointments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('customer_name', sa.String(length=255), nullable=False),
        sa.Column('customer_phone', sa.String(length=50), nullable=True),
        sa.Column('service_type', sa.String(length=100), nullable=False),
        sa.Column('scheduled_date', sa.Date(), nullable=False),
        sa.Column('scheduled_time', sa.Time(), nullable=False),
        sa.Column(
            'status',
            postgresql.ENUM(
                'pending', 'confirmed', 'completed', 'cancelled',
                name='appointmentstatusenum',
                create_type=False
            ),
            server_default='pending',
            nullable=True
        ),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # ========================================================================
    # 7. CREATE MEDIA_LIBRARY TABLE
    # ========================================================================
    
    # Create required enums
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'mediatypeenum') THEN
                CREATE TYPE mediatypeenum AS ENUM ('image', 'video', 'carousel');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'mediastatusenum') THEN
                CREATE TYPE mediastatusenum AS ENUM ('active', 'pending', 'rejected');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sourceplatformenum') THEN
                CREATE TYPE sourceplatformenum AS ENUM ('instagram', 'facebook', 'manual');
            END IF;
        END$$;
    """)
    
    op.create_table(
        'media_library',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            'source_platform',
            postgresql.ENUM('instagram', 'facebook', 'manual', name='sourceplatformenum', create_type=False),
            nullable=True
        ),
        sa.Column('source_post_id', sa.String(length=255), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column(
            'media_type',
            postgresql.ENUM('image', 'video', 'carousel', name='mediatypeenum', create_type=False),
            nullable=True
        ),
        sa.Column('media_url', sa.Text(), nullable=False),
        sa.Column('thumbnail_url', sa.Text(), nullable=True),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('linked_product_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('auto_linked', sa.Boolean(), server_default='false', nullable=True),
        sa.Column(
            'status',
            postgresql.ENUM('active', 'pending', 'rejected', name='mediastatusenum', create_type=False),
            server_default='active',
            nullable=True
        ),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['linked_product_id'], ['products.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # ========================================================================
    # 8. PERFORMANCE INDEXES
    # ========================================================================
    
    # Leads
    op.create_index('idx_leads_classification', 'leads', ['classification'])
    op.create_index('idx_leads_business_classification', 'leads', ['business_id', 'classification'])
    
    # Orders
    op.create_index('idx_orders_status', 'orders', ['status'])
    op.create_index('idx_orders_business_status', 'orders', ['business_id', 'status'])
    op.create_index('idx_orders_number', 'orders', ['order_number'])
    
    # Products
    op.create_index('idx_products_status', 'products', ['status'])
    op.create_index('idx_products_business_status', 'products', ['business_id', 'status'])
    op.create_index('idx_products_source', 'products', ['source'])
    
    # Appointments
    op.create_index('idx_appointments_business', 'appointments', ['business_id'])
    op.create_index('idx_appointments_date', 'appointments', ['scheduled_date'])
    op.create_index('idx_appointments_status', 'appointments', ['status'])
    
    # Media Library
    op.create_index('idx_media_business', 'media_library', ['business_id'])
    op.create_index('idx_media_product', 'media_library', ['linked_product_id'])
    op.create_index('idx_media_status', 'media_library', ['status'])
    
    # ========================================================================
    # 9. TRENDYPRODUCTSTT FOUNDING MEMBER CONFIGURATION
    # ========================================================================
    
    op.execute("""
        UPDATE businesses 
        SET 
            order_prefix = 'TPT',
            features = '{
                "ecommerce_enabled": true,
                "scheduling_enabled": false,
                "media_sync_enabled": true
            }'::jsonb,
            category = 'retail',
            brand_voice = 'Friendly and efficient. Trinidad-aware: knows local geography, delivery zones, and casual vs professional tone. Uses clear, warm language without being pushy. Understands that customers often want to order quickly, not chat extensively.'
        WHERE id = 'd510b8d0-9316-4e34-8edb-bc07a7de7568'
    """)
        # Product URL for website links
        op.add_column('products',
            sa.Column('product_url', sa.String(), nullable=True)
        )

        # Integration config for external inventory sync (WooCommerce etc.)
        op.add_column('businesses',
            sa.Column('integration_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )

        # Website URL
        op.add_column('businesses',
            sa.Column('website_url', sa.String(), nullable=True)
        )

def downgrade() -> None:
    """Reverse Phase 6 schema changes."""
    
    # Drop indexes first
    op.drop_index('idx_media_status', table_name='media_library')
    op.drop_index('idx_media_product', table_name='media_library')
    op.drop_index('idx_media_business', table_name='media_library')
    op.drop_index('idx_appointments_status', table_name='appointments')
    op.drop_index('idx_appointments_date', table_name='appointments')
    op.drop_index('idx_appointments_business', table_name='appointments')
    op.drop_index('idx_products_source', table_name='products')
    op.drop_index('idx_products_business_status', table_name='products')
    op.drop_index('idx_products_status', table_name='products')
    op.drop_index('idx_orders_number', table_name='orders')
    op.drop_index('idx_orders_business_status', table_name='orders')
    op.drop_index('idx_orders_status', table_name='orders')
    op.drop_index('idx_leads_business_classification', table_name='leads')
    op.drop_index('idx_leads_classification', table_name='leads')
    
    # Drop tables
    op.drop_table('media_library')
    op.drop_table('appointments')
    
    # Drop columns from existing tables
    op.drop_column('conversations', 'message_count')
    
    op.drop_column('orders', 'cancellation_reason')
    op.drop_column('orders', 'cancelled_at')
    op.drop_column('orders', 'shipped_at')
    op.drop_column('orders', 'special_instructions')
    op.drop_column('orders', 'delivery_address')
    op.drop_constraint('uq_orders_order_number', 'orders', type_='unique')
    op.drop_column('orders', 'order_number')
    
    op.drop_column('leads', 'last_updated')
    op.drop_column('leads', 'interest_area')
    op.drop_column('leads', 'classification')
    
    op.drop_column('products', 'approved_by')
    op.drop_column('products', 'approved_at')
    op.drop_column('products', 'ingested_at')
    op.drop_column('products', 'source')
    
    op.drop_column('businesses', 'brand_voice')
    op.drop_column('businesses', 'category')
    op.drop_column('businesses', 'order_prefix')
    op.drop_column('businesses', 'features')
    op.drop_column('businesses', 'website_url')
    op.drop_column('businesses', 'integration_config')
    op.drop_column('products', 'product_url')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS mediastatusenum")
    op.execute("DROP TYPE IF EXISTS mediatypeenum")
    op.execute("DROP TYPE IF EXISTS sourceplatformenum")
    op.execute("DROP TYPE IF EXISTS appointmentstatusenum")
    op.execute("DROP TYPE IF EXISTS leadclassificationenum")
    op.execute("DROP TYPE IF EXISTS productsourceenum")
    
    # Note: Can't easily remove values from existing enums (leadstatusenum, productstatusenum)
    # Those values will remain as 'orphan' but that's safe