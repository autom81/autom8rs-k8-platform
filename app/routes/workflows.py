import uuid
import logging
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.models.user import User
from app.models.workflow import Workflow, WorkflowExecution, WorkflowStatus, ExecutionStatus

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_WORKFLOWS_PER_BUSINESS = 50
MAX_STEPS_PER_WORKFLOW = 20


# ============================================================
# SCHEMAS
# ============================================================

class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_type: str
    trigger_config: Optional[dict] = None
    steps: List[dict] = []


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None
    steps: Optional[List[dict]] = None


def _serialize_workflow(w: Workflow) -> dict:
    return {
        "id": str(w.id),
        "business_id": str(w.business_id),
        "name": w.name,
        "description": w.description,
        "trigger_type": w.trigger_type,
        "trigger_config": w.trigger_config,
        "steps": w.steps or [],
        "status": w.status.value if w.status else "draft",
        "execution_count": w.execution_count,
        "last_triggered_at": w.last_triggered_at.isoformat() if w.last_triggered_at else None,
        "created_by": str(w.created_by) if w.created_by else None,
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


def _serialize_execution(e: WorkflowExecution) -> dict:
    return {
        "id": str(e.id),
        "workflow_id": str(e.workflow_id),
        "business_id": str(e.business_id),
        "lead_id": str(e.lead_id) if e.lead_id else None,
        "trigger_event": e.trigger_event,
        "status": e.status.value if e.status else "running",
        "current_step_index": e.current_step_index,
        "resume_at": e.resume_at.isoformat() if e.resume_at else None,
        "steps_completed": e.steps_completed or [],
        "retry_count": e.retry_count,
        "error_message": e.error_message,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "completed_at": e.completed_at.isoformat() if e.completed_at else None,
    }


# ============================================================
# CRUD ROUTES
# ============================================================

@router.get("/api/workflows")
def list_workflows(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Workflow).filter(Workflow.business_id == current_user.business_id)
    if status:
        try:
            q = q.filter(Workflow.status == WorkflowStatus(status))
        except ValueError:
            pass
    workflows = q.order_by(Workflow.created_at.desc()).all()
    return [_serialize_workflow(w) for w in workflows]


@router.post("/api/workflows", status_code=201)
def create_workflow(
    body: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Tier check
    if current_user.tier not in ("pro", "ultra"):
        raise HTTPException(status_code=403, detail="Workflows require Pro or Ultra plan")

    # Active workflow limit
    active_count = db.query(Workflow).filter(
        Workflow.business_id == current_user.business_id,
        Workflow.status == WorkflowStatus.active,
    ).count()
    if active_count >= MAX_WORKFLOWS_PER_BUSINESS:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_WORKFLOWS_PER_BUSINESS} active workflows reached")

    # Steps limit
    if len(body.steps) > MAX_STEPS_PER_WORKFLOW:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_STEPS_PER_WORKFLOW} steps per workflow")

    workflow = Workflow(
        id=uuid.uuid4(),
        business_id=current_user.business_id,
        name=body.name,
        description=body.description,
        trigger_type=body.trigger_type,
        trigger_config=body.trigger_config,
        steps=body.steps,
        status=WorkflowStatus.draft,
        execution_count=0,
        created_by=current_user.id,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return _serialize_workflow(workflow)


@router.get("/api/workflows/{workflow_id}")
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == uuid.UUID(workflow_id),
        Workflow.business_id == current_user.business_id,
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _serialize_workflow(workflow)


@router.patch("/api/workflows/{workflow_id}")
def update_workflow(
    workflow_id: str,
    body: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == uuid.UUID(workflow_id),
        Workflow.business_id == current_user.business_id,
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.trigger_type is not None:
        workflow.trigger_type = body.trigger_type
    if body.trigger_config is not None:
        workflow.trigger_config = body.trigger_config
    if body.steps is not None:
        if len(body.steps) > MAX_STEPS_PER_WORKFLOW:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_STEPS_PER_WORKFLOW} steps per workflow")
        workflow.steps = body.steps

    workflow.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(workflow)
    return _serialize_workflow(workflow)


@router.delete("/api/workflows/{workflow_id}", status_code=204)
def delete_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == uuid.UUID(workflow_id),
        Workflow.business_id == current_user.business_id,
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Cancel any running executions
    db.query(WorkflowExecution).filter(
        WorkflowExecution.workflow_id == workflow.id,
        WorkflowExecution.status == ExecutionStatus.running,
    ).update({"status": ExecutionStatus.cancelled})

    db.delete(workflow)
    db.commit()


@router.patch("/api/workflows/{workflow_id}/toggle")
def toggle_workflow_status(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == uuid.UUID(workflow_id),
        Workflow.business_id == current_user.business_id,
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow.status == WorkflowStatus.active:
        workflow.status = WorkflowStatus.paused
    elif workflow.status in (WorkflowStatus.draft, WorkflowStatus.paused):
        # Tier check before activating
        if current_user.tier not in ("pro", "ultra"):
            raise HTTPException(status_code=403, detail="Workflows require Pro or Ultra plan")
        active_count = db.query(Workflow).filter(
            Workflow.business_id == current_user.business_id,
            Workflow.status == WorkflowStatus.active,
        ).count()
        if active_count >= MAX_WORKFLOWS_PER_BUSINESS:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_WORKFLOWS_PER_BUSINESS} active workflows reached")
        workflow.status = WorkflowStatus.active

    workflow.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(workflow)
    return _serialize_workflow(workflow)


@router.get("/api/workflows/{workflow_id}/executions")
def list_workflow_executions(
    workflow_id: str,
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = db.query(Workflow).filter(
        Workflow.id == uuid.UUID(workflow_id),
        Workflow.business_id == current_user.business_id,
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    q = db.query(WorkflowExecution).filter(
        WorkflowExecution.workflow_id == uuid.UUID(workflow_id)
    )
    if status:
        try:
            q = q.filter(WorkflowExecution.status == ExecutionStatus(status))
        except ValueError:
            pass
    executions = q.order_by(WorkflowExecution.started_at.desc()).limit(limit).all()
    return [_serialize_execution(e) for e in executions]
