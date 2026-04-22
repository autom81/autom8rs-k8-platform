"""
Dashboard API Routes — Phase 7A Step 2
=======================================
All endpoints require a valid autom8rs_session JWT cookie.
business_id is always taken from the token — never trusted from the client.

Sections:
  - Auth dependency (get_current_user)
  - Helpers (serialisers, pagination, CSV)
  - Conversations
  - Leads
  - Products
  - Orders
"""
import csv
import io
import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, validator
from sqlalchemy import and_, or_, desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.business import Business, Product, ProductStatusEnum, ProductSourceEnum
from app.models.conversation import Conversation, Message, ConvoStatusEnum, RoleEnum
from app.models.lead import Lead, LeadStatusEnum, LeadClassificationEnum, OrderStatusEnum, Order
from app.models.tag import Tag, LeadTag
from app.services.auth_service import decode_token
from app.services.cache import ProductCache
from app.services.meta import send_reply

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])


# ═══════════════════════════════════════════════════════════════════
# AUTH DEPENDENCY
# ═══════════════════════════════════════════════════════════════════

def get_current_user(autom8rs_session: Optional[str] = Cookie(None)) -> dict:
    """
    Read and validate the JWT from the httpOnly cookie.
    Returns the decoded payload dict — contains business_id, user_id, role, etc.
    Raises 401 if missing or invalid.
    """
    if not autom8rs_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(autom8rs_session)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return payload


def _business_uuid(current_user: dict) -> uuid.UUID:
    return uuid.UUID(current_user["business_id"])


# ═══════════════════════════════════════════════════════════════════
# SERIALISERS
# ═══════════════════════════════════════════════════════════════════

def _dt(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val)


def _decimal(val) -> Optional[float]:
    if val is None:
        return None
    return float(val)


def _serialize_message(m: Message) -> dict:
    return {
        "id": str(m.id),
        "conversation_id": str(m.conversation_id),
        "role": m.role.value if hasattr(m.role, "value") else m.role,
        "content": m.content or "",
        "media_url": m.media_url,
        "media_type": m.media_type,
        "was_voice_note": bool(m.was_voice_note),
        "timestamp": _dt(m.timestamp),
    }


def _serialize_lead(lead: Lead, tags: list = None) -> dict:
    return {
        "id": str(lead.id),
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "channel": lead.source_channel,
        "classification": lead.classification.value if lead.classification and hasattr(lead.classification, "value") else lead.classification,
        "status": lead.status.value if lead.status and hasattr(lead.status, "value") else lead.status,
        "interest_area": lead.interest_area,
        "notes": lead.notes,
        "follow_up_at": _dt(getattr(lead, 'follow_up_at', None)),
        "created_at": _dt(lead.created_at),
        "last_updated": _dt(lead.last_updated),
        "conversation_id": str(lead.conversation_id) if lead.conversation_id else None,
        "tags": tags or [],
    }


def _serialize_conversation(conv: Conversation, lead: Optional[Lead] = None,
                             last_message: Optional[Message] = None,
                             has_order: bool = False) -> dict:
    return {
        "id": str(conv.id),
        "external_user_id": conv.external_user_id,
        "channel": conv.channel.value if hasattr(conv.channel, "value") else conv.channel,
        "status": conv.status.value if hasattr(conv.status, "value") else conv.status,
        "source": conv.source,
        "message_count": conv.message_count or 0,
        "last_message_at": _dt(conv.last_message_at),
        "escalation_reason": conv.escalation_reason,
        "lead": _serialize_lead(lead) if lead else None,
        "last_message_preview": (last_message.content or "")[:120] if last_message else None,
        "last_message_role": (last_message.role.value if hasattr(last_message.role, "value") else last_message.role) if last_message else None,
        "has_order": has_order,
        "pinned": bool(getattr(conv, 'pinned', False) or False),
        "bot_paused": bool(getattr(conv, 'bot_paused', False) or False),
    }


def _serialize_product(p: Product) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "price": _decimal(p.price),
        "currency": p.currency,
        "quantity": p.quantity,
        "status": p.status.value if p.status and hasattr(p.status, "value") else p.status,
        "source": p.source.value if p.source and hasattr(p.source, "value") else p.source,
        "product_url": p.product_url,
    }


def _serialize_order(o: Order) -> dict:
    return {
        "id": str(o.id),
        "order_number": o.order_number,
        "customer_name": o.customer_name,
        "customer_phone": o.customer_phone,
        "delivery_address": o.delivery_address,
        "items": o.items or [],
        "total": _decimal(o.total),
        "status": o.status.value if o.status and hasattr(o.status, "value") else o.status,
        "special_instructions": o.special_instructions,
        "created_at": _dt(o.created_at),
        "confirmed_at": _dt(getattr(o, 'confirmed_at', None)),
        "shipped_at": _dt(o.shipped_at),
        "delivered_at": _dt(getattr(o, 'delivered_at', None)),
    }


# ═══════════════════════════════════════════════════════════════════
# PAGINATION HELPER
# ═══════════════════════════════════════════════════════════════════

def _paginate(query, page: int, page_size: int):
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


# ═══════════════════════════════════════════════════════════════════
# CONVERSATIONS
# ═══════════════════════════════════════════════════════════════════

@router.get("/conversations")
def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)

    q = db.query(Conversation).filter(Conversation.business_id == business_id)

    if status:
        try:
            q = q.filter(Conversation.status == ConvoStatusEnum(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if channel:
        q = q.filter(Conversation.channel == channel)

    if date_from:
        try:
            q = q.filter(Conversation.started_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")

    if date_to:
        try:
            q = q.filter(Conversation.started_at <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")

    if search:
        # Search against external_user_id directly; join Lead for name/phone
        lead_matches = (
            db.query(Lead.conversation_id)
            .filter(
                Lead.business_id == business_id,
                or_(
                    Lead.name.ilike(f"%{search}%"),
                    Lead.phone.ilike(f"%{search}%"),
                    Lead.email.ilike(f"%{search}%"),
                ),
            )
            .subquery()
        )
        q = q.filter(
            or_(
                Conversation.external_user_id.ilike(f"%{search}%"),
                Conversation.id.in_(lead_matches),
            )
        )

    q = q.order_by(desc(Conversation.last_message_at))
    convs, total = _paginate(q, page, page_size)

    # Bulk-fetch leads and last messages for this page
    conv_ids = [c.id for c in convs]
    leads_by_conv: dict[uuid.UUID, Lead] = {}
    if conv_ids:
        for lead in db.query(Lead).filter(Lead.conversation_id.in_(conv_ids)).all():
            leads_by_conv[lead.conversation_id] = lead

    last_msgs: dict[uuid.UUID, Message] = {}
    if conv_ids:
        # For each conversation, get the most recent message
        from sqlalchemy import func as sqlfunc
        subq = (
            db.query(Message.conversation_id, sqlfunc.max(Message.timestamp).label("max_ts"))
            .filter(Message.conversation_id.in_(conv_ids))
            .group_by(Message.conversation_id)
            .subquery()
        )
        for msg in (
            db.query(Message)
            .join(subq, and_(
                Message.conversation_id == subq.c.conversation_id,
                Message.timestamp == subq.c.max_ts,
            ))
            .all()
        ):
            last_msgs[msg.conversation_id] = msg

    # Bulk-fetch which conversations have orders
    orders_conv_ids: set[uuid.UUID] = set()
    if conv_ids:
        for row in db.query(Order.conversation_id).filter(
            Order.conversation_id.in_(conv_ids)
        ).distinct().all():
            if row.conversation_id:
                orders_conv_ids.add(row.conversation_id)

    items = [
        _serialize_conversation(c, leads_by_conv.get(c.id), last_msgs.get(c.id), c.id in orders_conv_ids)
        for c in convs
    ]

    return {"conversations": items, "total": total, "page": page, "page_size": page_size}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == cid)
        .order_by(Message.timestamp.asc())
        .all()
    )

    lead = db.query(Lead).filter(Lead.conversation_id == cid).first()
    last_msg = messages[-1] if messages else None

    return {
        "conversation": _serialize_conversation(conv, lead, last_msg),
        "messages": [_serialize_message(m) for m in messages],
    }


class ReplyRequest(BaseModel):
    text: str


@router.post("/conversations/{conversation_id}/reply")
async def reply_to_conversation(
    conversation_id: str,
    body: ReplyRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="Reply text cannot be empty")

    business = db.query(Business).filter(Business.id == business_id).first()
    if not business:
        raise HTTPException(status_code=500, detail="Business not found")

    channel = conv.channel.value if hasattr(conv.channel, "value") else str(conv.channel)

    try:
        await send_reply(
            channel=channel,
            sender_id=conv.external_user_id,
            text=body.text.strip(),
            phone_number_id=business.meta_phone_number_id,
            page_access_token=business.meta_page_access_token,
            page_id=business.instagram_account_id if channel == "instagram" else business.meta_waba_id,
        )
    except Exception as e:
        logger.error(f"Failed to send reply for conversation {cid}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to send message via Meta API")

    # Persist the agent's message
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=cid,
        role=RoleEnum.assistant,
        content=body.text.strip(),
        was_voice_note=False,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(msg)

    conv.last_message_at = datetime.now(timezone.utc)
    conv.message_count = (conv.message_count or 0) + 1

    try:
        db.commit()
        db.refresh(msg)
    except Exception as e:
        db.rollback()
        logger.error(f"DB error saving reply: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Message sent but failed to save to database")

    return {"status": "ok", "message": _serialize_message(msg)}


@router.post("/conversations/{conversation_id}/resolve")
def resolve_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.status = ConvoStatusEnum.resolved
    db.commit()

    try:
        from app.models.lead import Lead
        from app.services.workflow_engine import fire_trigger
        lead = db.query(Lead).filter(Lead.conversation_id == conv.id).first()
        fire_trigger("conversation_resolved", db, business_id, lead.id if lead else None, {
            "conversation_id": str(conv.id),
        })
    except Exception:
        pass

    return {"status": "ok", "conversation_id": conversation_id, "new_status": "resolved"}


@router.post("/conversations/{conversation_id}/reopen")
def reopen_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.status = ConvoStatusEnum.active
    db.commit()
    return {"status": "ok", "conversation_id": conversation_id, "new_status": "active"}


@router.post("/conversations/{conversation_id}/mark-spam")
def mark_conversation_spam(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.status = ConvoStatusEnum.closed
    lead = db.query(Lead).filter(Lead.conversation_id == cid).first()
    if lead:
        lead.classification = LeadClassificationEnum.spam
    db.commit()
    return {"status": "ok", "conversation_id": conversation_id}


@router.post("/conversations/{conversation_id}/pin")
def pin_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.pinned = True
    db.commit()
    return {"status": "ok", "pinned": True}


@router.post("/conversations/{conversation_id}/unpin")
def unpin_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.pinned = False
    db.commit()
    return {"status": "ok", "pinned": False}


@router.post("/conversations/{conversation_id}/pause-bot")
def pause_bot(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.bot_paused = True
    db.commit()
    return {"status": "ok", "bot_paused": True}


@router.post("/conversations/{conversation_id}/resume-bot")
def resume_bot(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.bot_paused = False
    db.commit()
    return {"status": "ok", "bot_paused": False}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID")

    conv = db.query(Conversation).filter(
        Conversation.id == cid,
        Conversation.business_id == business_id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.query(Message).filter(Message.conversation_id == cid).delete()
    # Nullify the lead's conversation_id instead of deleting the lead —
    # contacts are independent CRM records that outlive any single conversation.
    db.query(Lead).filter(Lead.conversation_id == cid).update({"conversation_id": None})
    db.delete(conv)
    db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}


# ═══════════════════════════════════════════════════════════════════
# LEADS  — /export must be defined BEFORE /{id}
# ═══════════════════════════════════════════════════════════════════

def _leads_query(db: Session, business_id: uuid.UUID,
                 status: Optional[str], classification: Optional[str],
                 channel: Optional[str], search: Optional[str],
                 date_from: Optional[str], date_to: Optional[str],
                 needs_attention: bool = False, follow_up_due: bool = False):
    q = db.query(Lead).filter(Lead.business_id == business_id)

    if needs_attention:
        now = datetime.now(timezone.utc)
        q = q.filter(
            or_(
                and_(
                    Lead.classification == LeadClassificationEnum.hot,
                    Lead.status.notin_([
                        LeadStatusEnum.converted,
                        LeadStatusEnum.lost,
                        LeadStatusEnum.unqualified,
                    ])
                ),
                and_(
                    Lead.follow_up_at.isnot(None),
                    Lead.follow_up_at <= now + timedelta(hours=24),
                )
            )
        )
    else:
        if status:
            try:
                q = q.filter(Lead.status == LeadStatusEnum(status))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

        if classification:
            try:
                q = q.filter(Lead.classification == LeadClassificationEnum(classification))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid classification: {classification}")

    if follow_up_due:
        q = q.filter(Lead.follow_up_at.isnot(None))

    if channel:
        q = q.filter(Lead.source_channel == channel)

    if search:
        q = q.filter(
            or_(
                Lead.name.ilike(f"%{search}%"),
                Lead.phone.ilike(f"%{search}%"),
                Lead.email.ilike(f"%{search}%"),
            )
        )

    if date_from:
        try:
            q = q.filter(Lead.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")

    if date_to:
        try:
            q = q.filter(Lead.created_at <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")

    return q.order_by(desc(Lead.last_updated))


@router.get("/leads/export")
def export_leads(
    status: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    needs_attention: bool = Query(False),
    follow_up_due: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    leads = _leads_query(db, business_id, status, classification, channel, search, date_from, date_to, needs_attention, follow_up_due).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Phone", "Email", "Channel", "Classification",
                     "Status", "Interest Area", "Notes", "Created At", "Last Updated"])

    for lead in leads:
        writer.writerow([
            str(lead.id),
            lead.name or "",
            lead.phone or "",
            lead.email or "",
            lead.source_channel or "",
            lead.classification.value if lead.classification and hasattr(lead.classification, "value") else "",
            lead.status.value if lead.status and hasattr(lead.status, "value") else "",
            lead.interest_area or "",
            lead.notes or "",
            _dt(lead.created_at) or "",
            _dt(lead.last_updated) or "",
        ])

    output.seek(0)
    filename = f"leads_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _bulk_tags(db: Session, lead_ids: list) -> dict:
    """Return {lead_id: [tag_dict, ...]} for a list of lead IDs."""
    if not lead_ids:
        return {}
    try:
        rows = (
            db.query(LeadTag, Tag)
            .join(Tag, Tag.id == LeadTag.tag_id)
            .filter(LeadTag.lead_id.in_(lead_ids), Tag.is_active == True)
            .all()
        )
        result: dict = {lid: [] for lid in lead_ids}
        for lt, tag in rows:
            result[lt.lead_id].append({
                "id": str(tag.id),
                "name": tag.name,
                "color": tag.color,
                "type": tag.tag_type.value if hasattr(tag.tag_type, "value") else tag.tag_type,
            })
        return result
    except Exception:
        # Tags tables may not exist yet (migration pending) — return empty gracefully
        return {lid: [] for lid in lead_ids}


@router.get("/leads")
def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    needs_attention: bool = Query(False),
    follow_up_due: bool = Query(False),
    tag_ids: Optional[str] = Query(None),
    tag_match: str = Query("any"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    q = _leads_query(db, business_id, status, classification, channel, search, date_from, date_to, needs_attention, follow_up_due)

    # Tag filtering
    if tag_ids:
        try:
            tids = [uuid.UUID(t.strip()) for t in tag_ids.split(",") if t.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid tag_ids format")
        if tids:
            if tag_match == "all":
                for tid in tids:
                    q = q.filter(
                        Lead.id.in_(
                            db.query(LeadTag.lead_id).filter(LeadTag.tag_id == tid)
                        )
                    )
            else:
                q = q.filter(
                    Lead.id.in_(
                        db.query(LeadTag.lead_id).filter(LeadTag.tag_id.in_(tids))
                    )
                )

    leads, total = _paginate(q, page, page_size)
    lead_ids = [l.id for l in leads]
    tags_map = _bulk_tags(db, lead_ids)
    return {
        "leads": [_serialize_lead(l, tags_map.get(l.id, [])) for l in leads],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/leads/{lead_id}")
def get_lead(
    lead_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead ID")

    lead = db.query(Lead).filter(Lead.id == lid, Lead.business_id == business_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    conv = None
    if lead.conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == lead.conversation_id).first()

    result = _serialize_lead(lead)
    if conv:
        result["conversation"] = _serialize_conversation(conv, lead)

    return result


class UpdateLeadRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    classification: Optional[str] = None
    notes: Optional[str] = None
    interest_area: Optional[str] = None
    follow_up_at: Optional[str] = None  # ISO string or "" to clear


@router.patch("/leads/{lead_id}")
def update_lead(
    lead_id: str,
    body: UpdateLeadRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead ID")

    lead = db.query(Lead).filter(Lead.id == lid, Lead.business_id == business_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if body.name is not None:
        lead.name = body.name
    if body.phone is not None:
        lead.phone = body.phone
    if body.email is not None:
        lead.email = body.email
    if body.notes is not None:
        lead.notes = body.notes
    if body.interest_area is not None:
        lead.interest_area = body.interest_area
    if body.status is not None:
        try:
            lead.status = LeadStatusEnum(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    if body.classification is not None:
        try:
            lead.classification = LeadClassificationEnum(body.classification)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid classification: {body.classification}")
    if body.follow_up_at is not None:
        if body.follow_up_at == "":
            lead.follow_up_at = None
        else:
            try:
                lead.follow_up_at = datetime.fromisoformat(body.follow_up_at)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid follow_up_at format")

    try:
        db.commit()
        db.refresh(lead)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating lead {lid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update lead")

    return _serialize_lead(lead)


# ═══════════════════════════════════════════════════════════════════
# PRODUCTS
# ═══════════════════════════════════════════════════════════════════

@router.get("/products")
def list_products(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    q = db.query(Product).filter(Product.business_id == business_id)

    if status:
        try:
            q = q.filter(Product.status == ProductStatusEnum(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    q = q.order_by(Product.name.asc())
    products = q.all()
    return {"products": [_serialize_product(p) for p in products]}


class CreateProductRequest(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: float
    currency: str = "TTD"
    quantity: int = 0
    product_url: Optional[str] = None

    @validator('price')
    def price_must_be_positive(cls, v):
        if v < 0:
            raise ValueError('Price cannot be negative')
        return v

    @validator('quantity')
    def quantity_must_be_non_negative(cls, v):
        if v < 0:
            raise ValueError('Quantity cannot be negative')
        return v


@router.post("/products", status_code=201)
def create_product(
    body: CreateProductRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)

    product = Product(
        id=uuid.uuid4(),
        business_id=business_id,
        name=body.name,
        description=body.description,
        category=body.category,
        price=body.price,
        currency=body.currency,
        quantity=body.quantity,
        status=ProductStatusEnum.active,
        source=ProductSourceEnum.manual,
        product_url=body.product_url,
    )
    db.add(product)
    try:
        db.commit()
        db.refresh(product)
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating product: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create product")

    ProductCache.invalidate(str(business_id))
    return _serialize_product(product)


class UpdateProductRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    quantity: Optional[int] = None
    product_url: Optional[str] = None

    @validator('price', pre=True, always=True)
    def price_must_be_positive(cls, v):
        if v is not None and v < 0:
            raise ValueError('Price cannot be negative')
        return v

    @validator('quantity', pre=True, always=True)
    def quantity_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError('Quantity cannot be negative')
        return v


@router.patch("/products/{product_id}")
def update_product(
    product_id: str,
    body: UpdateProductRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID")

    product = db.query(Product).filter(
        Product.id == pid,
        Product.business_id == business_id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if body.name is not None:
        product.name = body.name
    if body.description is not None:
        product.description = body.description
    if body.category is not None:
        product.category = body.category
    if body.price is not None:
        product.price = body.price
    if body.currency is not None:
        product.currency = body.currency
    if body.quantity is not None:
        product.quantity = body.quantity
        # Auto-update status when stock changes
        if body.quantity == 0 and product.status == ProductStatusEnum.active:
            product.status = ProductStatusEnum.out_of_stock
        elif body.quantity > 0 and product.status == ProductStatusEnum.out_of_stock:
            product.status = ProductStatusEnum.active
    if body.product_url is not None:
        product.product_url = body.product_url

    try:
        db.commit()
        db.refresh(product)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating product {pid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update product")

    ProductCache.invalidate(str(business_id))
    return _serialize_product(product)


@router.delete("/products/{product_id}")
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Soft delete — sets status to discontinued so history is preserved."""
    business_id = _business_uuid(current_user)
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID")

    product = db.query(Product).filter(
        Product.id == pid,
        Product.business_id == business_id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.status = ProductStatusEnum.discontinued
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error soft-deleting product {pid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete product")

    ProductCache.invalidate(str(business_id))
    return {"status": "ok", "product_id": product_id}


@router.post("/products/{product_id}/approve")
def approve_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Approve a pending_review product (e.g. Instagram-ingested) → sets active."""
    business_id = _business_uuid(current_user)
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID")

    product = db.query(Product).filter(
        Product.id == pid,
        Product.business_id == business_id,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if product.status != ProductStatusEnum.pending_review:
        raise HTTPException(status_code=400, detail="Product is not pending review")

    product.status = ProductStatusEnum.active
    product.approved_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(product)
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving product {pid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to approve product")

    ProductCache.invalidate(str(business_id))
    return _serialize_product(product)


# ═══════════════════════════════════════════════════════════════════
# ORDERS
# ═══════════════════════════════════════════════════════════════════

@router.get("/orders")
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    q = db.query(Order).filter(Order.business_id == business_id)

    if status:
        try:
            q = q.filter(Order.status == OrderStatusEnum(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if search:
        q = q.filter(
            or_(
                Order.customer_name.ilike(f"%{search}%"),
                Order.customer_phone.ilike(f"%{search}%"),
                Order.order_number.ilike(f"%{search}%"),
            )
        )

    if date_from:
        try:
            q = q.filter(Order.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format")

    if date_to:
        try:
            q = q.filter(Order.created_at <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format")

    q = q.order_by(desc(Order.created_at))
    orders, total = _paginate(q, page, page_size)
    return {
        "orders": [_serialize_order(o) for o in orders],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/orders/{order_id}")
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        oid = uuid.UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order ID")

    order = db.query(Order).filter(
        Order.id == oid,
        Order.business_id == business_id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return _serialize_order(order)


class UpdateOrderStatusRequest(BaseModel):
    status: str


@router.patch("/orders/{order_id}/status")
def update_order_status(
    order_id: str,
    body: UpdateOrderStatusRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    business_id = _business_uuid(current_user)
    try:
        oid = uuid.UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order ID")

    order = db.query(Order).filter(
        Order.id == oid,
        Order.business_id == business_id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        new_status = OrderStatusEnum(body.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    order.status = new_status

    now = datetime.now(timezone.utc)
    if new_status == OrderStatusEnum.confirmed and not getattr(order, 'confirmed_at', None):
        order.confirmed_at = now
    if new_status == OrderStatusEnum.shipped and not order.shipped_at:
        order.shipped_at = now
    if new_status == OrderStatusEnum.delivered and not getattr(order, 'delivered_at', None):
        order.delivered_at = now
    if new_status == OrderStatusEnum.cancelled and not order.cancelled_at:
        order.cancelled_at = now

    try:
        db.commit()
        db.refresh(order)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating order status {oid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update order status")

    return _serialize_order(order)
