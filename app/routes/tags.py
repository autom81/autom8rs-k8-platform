"""
Tags API — /api/tags  &  /api/leads/{id}/tags
"""
import uuid
import re
import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tag import Tag, LeadTag, TagTypeEnum, TAG_PALETTE
from app.models.lead import Lead
from app.services.auth_service import decode_token
from app.services.tag_service import apply_tag_to_lead, MAX_TAGS_PER_LEAD

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Auth helper ────────────────────────────────────────────────────

def _business_id(access_token: Optional[str] = Cookie(None)) -> uuid.UUID:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    return uuid.UUID(payload["business_id"])


# ── Serialiser ─────────────────────────────────────────────────────

def _serialize(tag: Tag, lead_count: int = 0) -> dict:
    return {
        "id": str(tag.id),
        "name": tag.name,
        "color": tag.color,
        "type": tag.tag_type.value if hasattr(tag.tag_type, "value") else tag.tag_type,
        "is_active": tag.is_active,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
        "lead_count": lead_count,
    }


# ── Validators ─────────────────────────────────────────────────────

def _validate_name(v: str) -> str:
    v = v.lower().strip().replace(" ", "-")
    v = re.sub(r"[^a-z0-9-]", "", v)[:30]
    if not v:
        raise ValueError("Tag name cannot be empty")
    if v[0].isdigit():
        raise ValueError("Tag name cannot start with a number")
    return v


class CreateTagRequest(BaseModel):
    name: str
    color: str = "#6B7280"

    @validator("name")
    def validate_name(cls, v):
        return _validate_name(v)

    @validator("color")
    def validate_color(cls, v):
        if v not in TAG_PALETTE:
            raise ValueError("Color must be from the preset palette")
        return v


class UpdateTagRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

    @validator("name")
    def validate_name(cls, v):
        return _validate_name(v) if v is not None else v

    @validator("color")
    def validate_color(cls, v):
        if v is not None and v not in TAG_PALETTE:
            raise ValueError("Color must be from the preset palette")
        return v


# ── Tag library endpoints ──────────────────────────────────────────

@router.get("/api/tags")
def list_tags(
    db: Session = Depends(get_db),
    business_id: uuid.UUID = Depends(_business_id),
):
    tags = (
        db.query(Tag)
        .filter(Tag.business_id == business_id, Tag.is_active == True)
        .order_by(Tag.name)
        .all()
    )
    result = []
    for tag in tags:
        count = db.query(LeadTag).filter(LeadTag.tag_id == tag.id).count()
        result.append(_serialize(tag, count))
    return {"tags": result}


@router.post("/api/tags")
def create_tag(
    body: CreateTagRequest,
    db: Session = Depends(get_db),
    business_id: uuid.UUID = Depends(_business_id),
):
    existing = db.query(Tag).filter(
        Tag.business_id == business_id,
        Tag.name == body.name,
    ).first()

    if existing:
        if existing.is_active:
            raise HTTPException(status_code=409, detail=f"Tag '{body.name}' already exists")
        existing.is_active = True
        existing.color = body.color
        db.commit()
        db.refresh(existing)
        return _serialize(existing)

    tag = Tag(
        id=uuid.uuid4(),
        business_id=business_id,
        name=body.name,
        color=body.color,
        tag_type=TagTypeEnum.manual,
        is_active=True,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _serialize(tag)


@router.patch("/api/tags/{tag_id}")
def update_tag(
    tag_id: str,
    body: UpdateTagRequest,
    db: Session = Depends(get_db),
    business_id: uuid.UUID = Depends(_business_id),
):
    tag = db.query(Tag).filter(
        Tag.id == uuid.UUID(tag_id),
        Tag.business_id == business_id,
    ).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.tag_type == TagTypeEnum.auto:
        raise HTTPException(status_code=400, detail="Cannot modify auto tags")

    if body.name is not None:
        conflict = db.query(Tag).filter(
            Tag.business_id == business_id,
            Tag.name == body.name,
            Tag.id != tag.id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"Tag '{body.name}' already exists")
        tag.name = body.name

    if body.color is not None:
        tag.color = body.color

    db.commit()
    db.refresh(tag)
    count = db.query(LeadTag).filter(LeadTag.tag_id == tag.id).count()
    return _serialize(tag, count)


@router.delete("/api/tags/{tag_id}")
def delete_tag(
    tag_id: str,
    db: Session = Depends(get_db),
    business_id: uuid.UUID = Depends(_business_id),
):
    tag = db.query(Tag).filter(
        Tag.id == uuid.UUID(tag_id),
        Tag.business_id == business_id,
    ).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.tag_type == TagTypeEnum.auto:
        raise HTTPException(status_code=400, detail="Cannot delete auto tags")

    count = db.query(LeadTag).filter(LeadTag.tag_id == tag.id).count()
    db.query(LeadTag).filter(LeadTag.tag_id == tag.id).delete()
    tag.is_active = False
    db.commit()
    return {"deleted": True, "affected_leads": count}


# ── Lead tag endpoints ─────────────────────────────────────────────

@router.get("/api/leads/{lead_id}/tags")
def get_lead_tags(
    lead_id: str,
    db: Session = Depends(get_db),
    business_id: uuid.UUID = Depends(_business_id),
):
    lead = db.query(Lead).filter(
        Lead.id == uuid.UUID(lead_id),
        Lead.business_id == business_id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    tags = (
        db.query(Tag)
        .join(LeadTag, LeadTag.tag_id == Tag.id)
        .filter(LeadTag.lead_id == lead.id, Tag.is_active == True)
        .order_by(Tag.name)
        .all()
    )
    return {"tags": [_serialize(t) for t in tags]}


@router.post("/api/leads/{lead_id}/tags/{tag_id}")
def add_tag_to_lead(
    lead_id: str,
    tag_id: str,
    db: Session = Depends(get_db),
    business_id: uuid.UUID = Depends(_business_id),
):
    lead = db.query(Lead).filter(
        Lead.id == uuid.UUID(lead_id),
        Lead.business_id == business_id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    tag = db.query(Tag).filter(
        Tag.id == uuid.UUID(tag_id),
        Tag.business_id == business_id,
        Tag.is_active == True,
    ).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    count = db.query(LeadTag).filter(LeadTag.lead_id == lead.id).count()
    if count >= MAX_TAGS_PER_LEAD:
        raise HTTPException(
            status_code=400,
            detail=f"This contact has reached the maximum of {MAX_TAGS_PER_LEAD} tags. Remove one before adding another.",
        )

    applied = apply_tag_to_lead(db, lead.id, tag, applied_by="user")
    if applied:
        db.commit()
    return {"applied": applied}


@router.delete("/api/leads/{lead_id}/tags/{tag_id}")
def remove_tag_from_lead(
    lead_id: str,
    tag_id: str,
    db: Session = Depends(get_db),
    business_id: uuid.UUID = Depends(_business_id),
):
    lead = db.query(Lead).filter(
        Lead.id == uuid.UUID(lead_id),
        Lead.business_id == business_id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    tag = db.query(Tag).filter(
        Tag.id == uuid.UUID(tag_id),
        Tag.business_id == business_id,
    ).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if tag.tag_type == TagTypeEnum.auto:
        raise HTTPException(status_code=400, detail="Cannot remove auto tags")

    deleted = db.query(LeadTag).filter(
        LeadTag.lead_id == lead.id,
        LeadTag.tag_id == tag.id,
    ).delete()
    db.commit()
    return {"removed": deleted > 0}
