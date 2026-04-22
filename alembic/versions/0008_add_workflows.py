"""add workflows system

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'workflowstatus') THEN
                CREATE TYPE workflowstatus AS ENUM ('draft', 'active', 'paused');
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'executionstatus') THEN
                CREATE TYPE executionstatus AS ENUM ('running', 'completed', 'failed', 'cancelled');
            END IF;
        END $$;
    """)

    op.create_table(
        'workflows',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('businesses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('trigger_type', sa.String(100), nullable=False),
        sa.Column('trigger_config', postgresql.JSONB, nullable=True),
        sa.Column('steps', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('status', sa.Enum('draft', 'active', 'paused', name='workflowstatus'),
                  nullable=False, server_default='draft'),
        sa.Column('execution_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_workflows_business_id', 'workflows', ['business_id'])
    op.create_index('ix_workflows_status', 'workflows', ['status'])

    op.create_table(
        'workflow_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('business_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('lead_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('leads.id'), nullable=True),
        sa.Column('trigger_event', sa.String(100), nullable=True),
        sa.Column('trigger_data', postgresql.JSONB, nullable=True),
        sa.Column('status', sa.Enum('running', 'completed', 'failed', 'cancelled',
                                    name='executionstatus'),
                  nullable=False, server_default='running'),
        sa.Column('current_step_index', sa.Integer, nullable=False, server_default='0'),
        sa.Column('resume_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('steps_completed', postgresql.JSONB, nullable=True, server_default='[]'),
        sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_wf_exec_workflow_id', 'workflow_executions', ['workflow_id'])
    op.create_index('ix_wf_exec_lead_id', 'workflow_executions', ['lead_id'])
    op.create_index('ix_wf_exec_resume_at', 'workflow_executions', ['resume_at'])
    op.create_index('ix_wf_exec_status', 'workflow_executions', ['status'])


def downgrade():
    op.drop_index('ix_wf_exec_status', 'workflow_executions')
    op.drop_index('ix_wf_exec_resume_at', 'workflow_executions')
    op.drop_index('ix_wf_exec_lead_id', 'workflow_executions')
    op.drop_index('ix_wf_exec_workflow_id', 'workflow_executions')
    op.drop_table('workflow_executions')
    op.drop_index('ix_workflows_status', 'workflows')
    op.drop_index('ix_workflows_business_id', 'workflows')
    op.drop_table('workflows')
    op.execute("DROP TYPE IF EXISTS executionstatus")
    op.execute("DROP TYPE IF EXISTS workflowstatus")
