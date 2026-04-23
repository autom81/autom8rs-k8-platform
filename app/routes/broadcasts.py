"""
Broadcast Campaigns API
=======================
Lets businesses send a message to a filtered segment of their leads.

Endpoints:
  GET  /api/broadcasts                  — list broadcasts
  POST /api/broadcasts                  — create broadcast (draft)
  GET  /api/broadcasts/templates        — list templates
  POST /api/broadcasts/templates        — create template
  GET  /api/broadcasts/recipient-count  — count leads matching filter
  GET  /api/broadcasts/{id}/stats       — broadcast delivery stats
  POST /api/broadcasts/{id}/send        — send immediately (background)
  POST /api/broadcasts/{id}/schedule    — schedule for later
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.routes.dashboard import get_current_user
from app.models.broadcast import Broadcast, BroadcastTemplate, BroadcastRecipient
from app.models.lead import Lead, LeadClassificationEnum
from app.models.conversation import Conversation
from app.models.business import Business

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_RECIPIENTS_PER_BROADCAST = 500


# ── Helpers ───────────────────────────────────────────────────────

def _business_uuid(current_user: dict) -> uuid.UUID:
    return uuid.UUID(current_user["business_id"])


def _serialize_template(t: BroadcastTemplate) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "category": t.category or "MARKETING",
        "body": t.body_text,
        "variables": t.variables or [],
        "status": t.meta_status or "pending",
        "rejection_reason": t.meta_rejection_reason,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _serialize_broadcast(b: Broadcast) -> dict:
    af = b.audience_filter or {}
    return {
        "id": str(b.id),
        "name": b.name,
        "template_id": str(b.template_id) if b.template_id else None,
        "template_name": b.template.name if b.template else None,
        "channel": af.get("channel", "all"),
        "classification_filter": af.get("classification"),
        "recipient_count": b.recipient_count or 0,
        "status": b.status,
        "sent_count": b.sent_count or 0,
        "delivered_count": b.delivered_count or 0,
        "read_count": b.read_count or 0,
        "failed_count": b.failed_count or 0,
        "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


# ── Resolve leads matching an audience filter ─────────────────────

def _resolve_recipients(
    db: Session,
    business_id: uuid.UUID,
    audience_filter: dict,
) -> list[Lead]:
    query = db.query(Lead).filter(
        Lead.business_id == business_id,
        Lead.phone.isnot(None),
    )

    channel = audience_filter.get("channel")
    if channel and channel != "all":
        query = query.join(Conversation, Conversation.id == Lead.conversation_id).filter(
            Conversation.channel == channel
        )

    classification = audience_filter.get("classification")
    if classification:
        try:
            query = query.filter(Lead.classification == LeadClassificationEnum(classification))
        except ValueError:
            pass

    return query.limit(MAX_RECIPIENTS_PER_BROADCAST).all()


# ── Background send task ──────────────────────────────────────────

def _send_broadcast_bg(broadcast_id: uuid.UUID) -> None:
    from app.services.meta import send_whatsapp_message, send_messenger_message

    db = SessionLocal()
    try:
        broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
        if not broadcast:
            return

        template = db.query(BroadcastTemplate).filter(
            BroadcastTemplate.id == broadcast.template_id
        ).first()
        if not template:
            broadcast.status = "failed"
            db.commit()
            return

        business = db.query(Business).filter(Business.id == broadcast.business_id).first()
        if not business:
            broadcast.status = "failed"
            db.commit()
            return

        broadcast.status = "in_progress"
        db.commit()

        leads = _resolve_recipients(db, broadcast.business_id, broadcast.audience_filter or {})
        broadcast.recipient_count = len(leads)
        db.commit()

        sent = 0
        failed = 0

        for lead in leads:
            conv = db.query(Conversation).filter(
                Conversation.id == lead.conversation_id
            ).first() if lead.conversation_id else None

            channel = (conv.channel.value if hasattr(conv.channel, "value") else str(conv.channel)) if conv else "whatsapp"
            recipient_id = conv.external_user_id if conv else lead.phone

            try:
                loop = asyncio.new_event_loop()
                if channel == "whatsapp":
                    if not business.meta_phone_number_id or not lead.phone:
                        raise ValueError("Missing phone_number_id or lead phone")
                    result = loop.run_until_complete(
                        send_whatsapp_message(business.meta_phone_number_id, lead.phone, template.body_text)
                    )
                else:
                    if not business.meta_page_access_token or not recipient_id:
                        raise ValueError("Missing page token or recipient")
                    result = loop.run_until_complete(
                        send_messenger_message(recipient_id, template.body_text, business.meta_page_access_token)
                    )
                loop.close()

                status = "sent" if "error" not in result else "failed"
                meta_msg_id = (result.get("messages") or [{}])[0].get("id") if status == "sent" else None
                err = result.get("error") if status == "failed" else None
            except Exception as e:
                status = "failed"
                meta_msg_id = None
                err = str(e)

            db.add(BroadcastRecipient(
                id=uuid.uuid4(),
                broadcast_id=broadcast.id,
                lead_id=lead.id,
                phone=lead.phone,
                status=status,
                meta_message_id=meta_msg_id,
                error_message=err,
                sent_at=datetime.now(timezone.utc) if status == "sent" else None,
            ))

            if status == "sent":
                sent += 1
            else:
                failed += 1

        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.status = "completed"
        db.commit()
        logger.info(f"Broadcast {broadcast_id} completed: sent={sent} failed={failed}")

    except Exception as e:
        logger.error(f"Broadcast send error {broadcast_id}: {e}", exc_info=True)
        try:
            broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
            if broadcast:
                broadcast.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ── Routes ────────────────────────────────────────────────────────

@router.get("/api/broadcasts")
def list_broadcasts(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    q = db.query(Broadcast).filter(Broadcast.business_id == business_id)
    if status and status != "all":
        q = q.filter(Broadcast.status == status)
    broadcasts = q.order_by(Broadcast.created_at.desc()).all()
    return {
        "broadcasts": [_serialize_broadcast(b) for b in broadcasts],
        "total": len(broadcasts),
    }


class CreateBroadcastRequest(BaseModel):
    name: str
    template_id: str
    channel: str = "all"
    classification_filter: Optional[str] = None


@router.post("/api/broadcasts")
def create_broadcast(
    body: CreateBroadcastRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)

    try:
        tid = uuid.UUID(body.template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid template_id")

    template = db.query(BroadcastTemplate).filter(
        BroadcastTemplate.id == tid,
        BroadcastTemplate.business_id == business_id,
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    audience: dict = {}
    if body.channel and body.channel != "all":
        audience["channel"] = body.channel
    if body.classification_filter:
        audience["classification"] = body.classification_filter

    broadcast = Broadcast(
        id=uuid.uuid4(),
        business_id=business_id,
        template_id=tid,
        name=body.name,
        status="draft",
        audience_filter=audience,
        created_by=uuid.UUID(current_user["user_id"]) if current_user.get("user_id") else None,
    )
    db.add(broadcast)
    db.commit()
    db.refresh(broadcast)
    return _serialize_broadcast(broadcast)


@router.get("/api/broadcasts/templates")
def list_templates(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    templates = db.query(BroadcastTemplate).filter(
        BroadcastTemplate.business_id == business_id,
    ).order_by(BroadcastTemplate.name).all()
    return {"templates": [_serialize_template(t) for t in templates]}


class CreateTemplateRequest(BaseModel):
    name: str
    category: str = "MARKETING"
    body: str
    variables: list = []


@router.post("/api/broadcasts/templates")
def create_template(
    body: CreateTemplateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    template = BroadcastTemplate(
        id=uuid.uuid4(),
        business_id=business_id,
        name=body.name,
        category=body.category,
        body_text=body.body,
        variables=body.variables,
        meta_status="pending",
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _serialize_template(template)


@router.get("/api/broadcasts/recipient-count")
def recipient_count(
    channel: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    af: dict = {}
    if channel and channel != "all":
        af["channel"] = channel
    if classification and classification != "all":
        af["classification"] = classification
    leads = _resolve_recipients(db, business_id, af)
    return {"count": len(leads)}


@router.get("/api/broadcasts/{broadcast_id}/stats")
def broadcast_stats(
    broadcast_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        bid = uuid.UUID(broadcast_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid broadcast ID")

    broadcast = db.query(Broadcast).filter(
        Broadcast.id == bid,
        Broadcast.business_id == business_id,
    ).first()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    return {
        "broadcast_id": str(broadcast.id),
        "recipient_count": broadcast.recipient_count or 0,
        "sent_count": broadcast.sent_count or 0,
        "delivered_count": broadcast.delivered_count or 0,
        "read_count": broadcast.read_count or 0,
        "failed_count": broadcast.failed_count or 0,
    }


@router.post("/api/broadcasts/{broadcast_id}/send")
def send_broadcast(
    broadcast_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        bid = uuid.UUID(broadcast_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid broadcast ID")

    broadcast = db.query(Broadcast).filter(
        Broadcast.id == bid,
        Broadcast.business_id == business_id,
    ).first()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if broadcast.status not in ("draft", "scheduled"):
        raise HTTPException(status_code=400, detail=f"Cannot send a broadcast with status '{broadcast.status}'")

    background_tasks.add_task(_send_broadcast_bg, bid)
    return {"status": "sending", "broadcast_id": str(bid)}


class ScheduleBroadcastRequest(BaseModel):
    scheduled_at: str


@router.post("/api/broadcasts/{broadcast_id}/schedule")
def schedule_broadcast(
    broadcast_id: str,
    body: ScheduleBroadcastRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        bid = uuid.UUID(broadcast_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid broadcast ID")

    broadcast = db.query(Broadcast).filter(
        Broadcast.id == bid,
        Broadcast.business_id == business_id,
    ).first()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    try:
        scheduled_at = datetime.fromisoformat(body.scheduled_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid scheduled_at format")

    broadcast.scheduled_at = scheduled_at
    broadcast.status = "scheduled"
    db.commit()
    return {"status": "scheduled", "scheduled_at": scheduled_at.isoformat()}
