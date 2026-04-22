import uuid
import enum
from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime
from sqlalchemy import Uuid, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class WorkflowStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    paused = "paused"


class ExecutionStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    trigger_type = Column(String(100), nullable=False)
    trigger_config = Column(JSONB, nullable=True)       # optional filter conditions
    steps = Column(JSONB, nullable=False, default=list) # ordered step definitions
    status = Column(SAEnum(WorkflowStatus), nullable=False, default=WorkflowStatus.draft)
    execution_count = Column(Integer, nullable=False, default=0)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(Uuid(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    lead_id = Column(Uuid(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    trigger_event = Column(String(100), nullable=True)
    trigger_data = Column(JSONB, nullable=True)           # snapshot at trigger time
    status = Column(SAEnum(ExecutionStatus), nullable=False, default=ExecutionStatus.running)
    current_step_index = Column(Integer, nullable=False, default=0)
    resume_at = Column(DateTime(timezone=True), nullable=True)
    steps_completed = Column(JSONB, nullable=True, default=list)
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
