"""
Workflow Execution Engine
=========================
Handles firing workflows on trigger events and stepping through
Wait/Action steps. Designed to be safe: failures never crash the bot.

Entry points:
  fire_trigger(trigger_type, db, business_id, lead_id, trigger_data)
    — called from tool executors and route handlers when an event occurs

  resume_waiting_executions(db)
    — called by APScheduler every 5 minutes to resume paused executions
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.workflow import Workflow, WorkflowExecution, WorkflowStatus, ExecutionStatus
from app.models.lead import Lead, LeadStatusEnum, LeadClassificationEnum
from app.models.business import Business

logger = logging.getLogger(__name__)

MAX_DAILY_EXECUTIONS = 500
MAX_MSGS_PER_CUSTOMER_24H = 10
MAX_RETRIES = 3
DUPLICATE_WINDOW_SECONDS = 3600  # 1 hour


# ── Entry point: fire from tool executors ─────────────────────────

def fire_trigger(
    trigger_type: str,
    db: Session,
    business_id: uuid.UUID,
    lead_id: Optional[uuid.UUID],
    trigger_data: dict,
) -> None:
    """Called from ordering/escalation/tag tools when an event occurs."""
    try:
        _fire_trigger_impl(trigger_type, db, business_id, lead_id, trigger_data)
    except Exception as e:
        logger.error(f"workflow fire_trigger error ({trigger_type}): {e}", exc_info=True)


def _fire_trigger_impl(
    trigger_type: str,
    db: Session,
    business_id: uuid.UUID,
    lead_id: Optional[uuid.UUID],
    trigger_data: dict,
) -> None:
    # Daily execution cap
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = db.query(WorkflowExecution).filter(
        WorkflowExecution.business_id == business_id,
        WorkflowExecution.started_at >= today_start,
    ).count()
    if daily_count >= MAX_DAILY_EXECUTIONS:
        logger.warning(f"Business {business_id} hit daily execution cap ({MAX_DAILY_EXECUTIONS})")
        return

    # Find matching active workflows
    workflows = db.query(Workflow).filter(
        Workflow.business_id == business_id,
        Workflow.trigger_type == trigger_type,
        Workflow.status == WorkflowStatus.active,
    ).all()

    for wf in workflows:
        try:
            _start_execution(wf, db, lead_id, trigger_type, trigger_data)
        except Exception as e:
            logger.error(f"Error starting execution for workflow {wf.id}: {e}", exc_info=True)


def _start_execution(
    wf: Workflow,
    db: Session,
    lead_id: Optional[uuid.UUID],
    trigger_event: str,
    trigger_data: dict,
) -> None:
    # Duplicate prevention: same workflow + lead + trigger within 1 hour
    if lead_id:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
        duplicate = db.query(WorkflowExecution).filter(
            WorkflowExecution.workflow_id == wf.id,
            WorkflowExecution.lead_id == lead_id,
            WorkflowExecution.trigger_event == trigger_event,
            WorkflowExecution.started_at >= cutoff,
        ).first()
        if duplicate:
            logger.info(f"Skipping duplicate execution for workflow {wf.id} lead {lead_id}")
            return

    execution = WorkflowExecution(
        id=uuid.uuid4(),
        workflow_id=wf.id,
        business_id=wf.business_id,
        lead_id=lead_id,
        trigger_event=trigger_event,
        trigger_data=trigger_data,
        status=ExecutionStatus.running,
        current_step_index=1,  # step 0 is the trigger, start at 1
        steps_completed=[],
        retry_count=0,
    )
    db.add(execution)

    # Update workflow stats
    wf.execution_count = (wf.execution_count or 0) + 1
    wf.last_triggered_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(execution)

    # Execute steps synchronously (in the same request context)
    _run_execution(execution, wf, db)


# ── Step execution ────────────────────────────────────────────────

def _run_execution(
    execution: WorkflowExecution,
    wf: Workflow,
    db: Session,
) -> None:
    steps = wf.steps or []

    while execution.current_step_index < len(steps):
        step = steps[execution.current_step_index]
        step_type = step.get("type")

        if step_type == "wait":
            resume_at = _calculate_resume_at(step, execution.trigger_data or {})
            if resume_at:
                execution.resume_at = resume_at
                execution.status = ExecutionStatus.running
                db.commit()
                return  # Paused — scheduler will resume
            # If resume_at couldn't be calculated, skip the wait
            execution.current_step_index += 1
            continue

        if step_type == "action":
            success = _execute_action(step, execution, wf, db)
            log_entry = {
                "step_index": execution.current_step_index,
                "action_type": step.get("action_type"),
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            completed = list(execution.steps_completed or [])
            completed.append(log_entry)
            execution.steps_completed = completed

        execution.current_step_index += 1
        db.commit()

    # All steps done
    execution.status = ExecutionStatus.completed
    execution.completed_at = datetime.now(timezone.utc)
    execution.resume_at = None
    db.commit()
    logger.info(f"Workflow execution {execution.id} completed")


def _calculate_resume_at(step: dict, trigger_data: dict) -> Optional[datetime]:
    now = datetime.now(timezone.utc)
    wait_type = step.get("wait_type", "fixed_duration")

    if wait_type == "fixed_duration":
        duration = int(step.get("duration", 1))
        unit = step.get("unit", "hours")
        delta = {
            "minutes": timedelta(minutes=duration),
            "hours": timedelta(hours=duration),
            "days": timedelta(days=duration),
        }.get(unit, timedelta(hours=duration))
        # Enforce minimum 5 minutes, maximum 90 days
        delta = max(delta, timedelta(minutes=5))
        delta = min(delta, timedelta(days=90))
        return now + delta

    if wait_type == "until_time_of_day":
        target_time = step.get("time", "09:00")
        try:
            h, m = map(int, target_time.split(":"))
        except Exception:
            h, m = 9, 0
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if wait_type == "until_before_event":
        event_dt_str = trigger_data.get("appointment_datetime") or trigger_data.get("event_datetime")
        if not event_dt_str:
            return None
        try:
            event_dt = datetime.fromisoformat(event_dt_str)
            hours_before = int(step.get("hours", 24))
            return event_dt - timedelta(hours=hours_before)
        except Exception:
            return None

    if wait_type == "until_after_event":
        event_dt_str = trigger_data.get("appointment_datetime") or trigger_data.get("event_datetime")
        if not event_dt_str:
            return None
        try:
            event_dt = datetime.fromisoformat(event_dt_str)
            hours_after = int(step.get("hours", 2))
            return event_dt + timedelta(hours=hours_after)
        except Exception:
            return None

    if wait_type == "until_next_business_day":
        candidate = now + timedelta(days=1)
        while candidate.weekday() >= 5:  # Saturday=5, Sunday=6
            candidate += timedelta(days=1)
        return candidate.replace(hour=9, minute=0, second=0, microsecond=0)

    return now + timedelta(hours=1)


def _execute_action(
    step: dict,
    execution: WorkflowExecution,
    wf: Workflow,
    db: Session,
) -> bool:
    action_type = step.get("action_type")
    try:
        if action_type == "send_template":
            return _action_send_template(step, execution, db)
        if action_type == "send_notification":
            return _action_send_notification(step, execution, db)
        if action_type == "apply_tag":
            return _action_apply_tag(step, execution, db)
        if action_type == "remove_tag":
            return _action_remove_tag(step, execution, db)
        if action_type == "update_lead_status":
            return _action_update_lead_status(step, execution, db)
        if action_type == "update_lead_classification":
            return _action_update_lead_classification(step, execution, db)
        if action_type == "update_order_status":
            return _action_update_order_status(step, execution, db)
        logger.warning(f"Unknown action type: {action_type}")
        return False
    except Exception as e:
        logger.error(f"Action {action_type} failed in execution {execution.id}: {e}", exc_info=True)
        return False


def _action_send_template(step: dict, execution: WorkflowExecution, db: Session) -> bool:
    """Send a Meta-approved template to the customer or owner."""
    from app.models.broadcast import BroadcastTemplate
    from app.models.conversation import Conversation

    template_id = step.get("template_id")
    recipient = step.get("recipient", "customer")

    template = db.query(BroadcastTemplate).filter(
        BroadcastTemplate.id == uuid.UUID(template_id)
    ).first() if template_id else None

    if not template:
        logger.warning(f"Template {template_id} not found for execution {execution.id}")
        return False

    business = db.query(Business).filter(Business.id == execution.business_id).first()
    if not business or not business.meta_phone_number_id:
        logger.warning(f"Business {execution.business_id} missing phone_number_id")
        return False

    # Determine recipient phone number
    if recipient == "owner":
        to_phone = business.owner_phone
    else:
        # Customer — get their phone from the lead
        lead = db.query(Lead).filter(Lead.id == execution.lead_id).first() if execution.lead_id else None
        to_phone = lead.phone if lead else None

    if not to_phone:
        logger.warning(f"No phone number for recipient '{recipient}' in execution {execution.id}")
        return False

    # Check per-customer 24h rate limit
    if recipient == "customer" and execution.lead_id:
        if not _check_customer_rate_limit(execution.lead_id, execution.business_id, db):
            logger.info(f"Rate limit hit for lead {execution.lead_id}, skipping send")
            return False

    # Send via Meta API (async call in sync context)
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            _send_whatsapp_template(
                phone_number_id=business.meta_phone_number_id,
                to=to_phone,
                template_name=template.meta_template_name or template.name,
                language_code="en",
            )
        )
        loop.close()
        return result.get("messages") is not None
    except Exception as e:
        logger.error(f"Template send failed: {e}")
        return False


def _action_send_notification(step: dict, execution: WorkflowExecution, db: Session) -> bool:
    """Send a WhatsApp notification to the business owner."""
    step["recipient"] = "owner"
    return _action_send_template(step, execution, db)


def _action_apply_tag(step: dict, execution: WorkflowExecution, db: Session) -> bool:
    if not execution.lead_id:
        return False
    from app.services.tag_service import get_or_create_tag, apply_tag_to_lead
    from app.models.tag import Tag
    tag_id = step.get("tag_id")
    tag = db.query(Tag).filter(Tag.id == uuid.UUID(tag_id)).first() if tag_id else None
    if not tag:
        return False
    result = apply_tag_to_lead(db, execution.lead_id, tag, applied_by="workflow")
    if result:
        db.flush()
    return True


def _action_remove_tag(step: dict, execution: WorkflowExecution, db: Session) -> bool:
    if not execution.lead_id:
        return False
    from app.models.tag import LeadTag
    tag_id = step.get("tag_id")
    if not tag_id:
        return False
    db.query(LeadTag).filter(
        LeadTag.lead_id == execution.lead_id,
        LeadTag.tag_id == uuid.UUID(tag_id),
    ).delete()
    db.flush()
    return True


def _action_update_lead_status(step: dict, execution: WorkflowExecution, db: Session) -> bool:
    if not execution.lead_id:
        return False
    new_status = step.get("status")
    if not new_status:
        return False
    lead = db.query(Lead).filter(Lead.id == execution.lead_id).first()
    if not lead:
        return False
    try:
        lead.status = LeadStatusEnum(new_status)
        db.flush()
        return True
    except ValueError:
        return False


def _action_update_lead_classification(step: dict, execution: WorkflowExecution, db: Session) -> bool:
    if not execution.lead_id:
        return False
    new_class = step.get("classification")
    if not new_class:
        return False
    lead = db.query(Lead).filter(Lead.id == execution.lead_id).first()
    if not lead:
        return False
    try:
        lead.classification = LeadClassificationEnum(new_class)
        db.flush()
        return True
    except ValueError:
        return False


def _action_update_order_status(step: dict, execution: WorkflowExecution, db: Session) -> bool:
    from app.models.lead import Order, OrderStatusEnum
    order_id = (execution.trigger_data or {}).get("order_id")
    new_status = step.get("status")
    if not order_id or not new_status:
        return False
    order = db.query(Order).filter(Order.id == uuid.UUID(order_id)).first()
    if not order:
        return False
    try:
        order.status = OrderStatusEnum(new_status)
        db.flush()
        return True
    except ValueError:
        return False


# ── Rate limiting ─────────────────────────────────────────────────

def _check_customer_rate_limit(
    lead_id: uuid.UUID,
    business_id: uuid.UUID,
    db: Session,
) -> bool:
    """Return True if the customer can receive another message in the next 24h."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    # Count completed send_template actions for this lead in the past 24h
    recent = db.query(WorkflowExecution).filter(
        WorkflowExecution.business_id == business_id,
        WorkflowExecution.lead_id == lead_id,
        WorkflowExecution.started_at >= cutoff,
        WorkflowExecution.status == ExecutionStatus.completed,
    ).count()
    return recent < MAX_MSGS_PER_CUSTOMER_24H


# ── Meta template send helper ─────────────────────────────────────

async def _send_whatsapp_template(
    phone_number_id: str,
    to: str,
    template_name: str,
    language_code: str = "en",
) -> dict:
    import httpx
    from app.config import settings

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://graph.facebook.com/v19.0/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"},
            json=payload,
            timeout=10,
        )
        return resp.json()


# ── Scheduler: resume waiting executions ─────────────────────────

def resume_waiting_executions() -> None:
    """Called by APScheduler every 5 minutes."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = db.query(WorkflowExecution).filter(
            WorkflowExecution.status == ExecutionStatus.running,
            WorkflowExecution.resume_at.isnot(None),
            WorkflowExecution.resume_at <= now,
        ).all()

        for execution in due:
            try:
                execution.resume_at = None
                wf = db.query(Workflow).filter(Workflow.id == execution.workflow_id).first()
                if not wf:
                    execution.status = ExecutionStatus.failed
                    execution.error_message = "Workflow not found"
                    db.commit()
                    continue
                _run_execution(execution, wf, db)
            except Exception as e:
                logger.error(f"Error resuming execution {execution.id}: {e}", exc_info=True)
                execution.status = ExecutionStatus.failed
                execution.error_message = str(e)
                db.commit()

        if due:
            logger.info(f"Workflow scheduler: resumed {len(due)} executions")

    except Exception as e:
        logger.error(f"Workflow scheduler error: {e}", exc_info=True)
    finally:
        db.close()


# ── Cancel executions for a lead/order ───────────────────────────

def cancel_executions_for_lead(db: Session, lead_id: uuid.UUID) -> None:
    """Cancel all running executions when a lead is deleted."""
    db.query(WorkflowExecution).filter(
        WorkflowExecution.lead_id == lead_id,
        WorkflowExecution.status == ExecutionStatus.running,
    ).update({
        "status": ExecutionStatus.cancelled,
        "completed_at": datetime.now(timezone.utc),
    })
    db.flush()
