"""
Tag Service
===========
Shared helpers for applying tags from both bot tools and API routes.
All functions are silent-fail safe — tag errors never crash core flows.
"""
import uuid
import logging
import re

from sqlalchemy.orm import Session

from app.models.tag import Tag, LeadTag, TagTypeEnum, AUTO_TAG_COLORS

logger = logging.getLogger(__name__)

MAX_TAGS_PER_LEAD = 10


def _normalize_name(name: str) -> str:
    name = name.lower().strip().replace(" ", "-")
    name = re.sub(r"[^a-z0-9-]", "", name)
    return name[:30]


def get_or_create_tag(
    db: Session,
    business_id: uuid.UUID,
    name: str,
    tag_type: str = "auto",
) -> "Tag | None":
    """Return an active Tag for this business, creating it if it doesn't exist."""
    try:
        name = _normalize_name(name)
        if not name:
            return None

        tag = db.query(Tag).filter(
            Tag.business_id == business_id,
            Tag.name == name,
        ).first()

        if tag:
            if not tag.is_active:
                tag.is_active = True
                db.flush()
            return tag

        color = AUTO_TAG_COLORS.get(name, "#6B7280")
        tag = Tag(
            id=uuid.uuid4(),
            business_id=business_id,
            name=name,
            color=color,
            tag_type=TagTypeEnum(tag_type),
            is_active=True,
        )
        db.add(tag)
        db.flush()
        return tag

    except Exception as e:
        logger.error(f"Error getting/creating tag '{name}': {e}")
        return None


def apply_tag_to_lead(
    db: Session,
    lead_id: uuid.UUID,
    tag: Tag,
    applied_by: str = "bot",
) -> bool:
    """Apply a tag to a lead. Silent-skip if already at limit or duplicate."""
    try:
        count = db.query(LeadTag).filter(LeadTag.lead_id == lead_id).count()
        if count >= MAX_TAGS_PER_LEAD:
            logger.info(f"Lead {lead_id} at max tags, skipping '{tag.name}'")
            return False

        existing = db.query(LeadTag).filter(
            LeadTag.lead_id == lead_id,
            LeadTag.tag_id == tag.id,
        ).first()
        if existing:
            return False

        db.add(LeadTag(lead_id=lead_id, tag_id=tag.id, applied_by=applied_by))
        db.flush()

        try:
            from app.models.lead import Lead
            from app.services.workflow_engine import fire_trigger
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                fire_trigger("lead_tag_applied", db, lead.business_id, lead_id, {
                    "tag_id": str(tag.id),
                    "tag_name": tag.name,
                    "applied_by": applied_by,
                })
        except Exception:
            pass

        return True

    except Exception as e:
        logger.error(f"Error applying tag '{tag.name}' to lead {lead_id}: {e}")
        return False


def auto_tag_lead(
    db: Session,
    business_id: uuid.UUID,
    lead_id: uuid.UUID,
    tag_names: list,
) -> None:
    """Convenience: get-or-create + apply a list of auto tags in one call."""
    for name in tag_names:
        try:
            tag = get_or_create_tag(db, business_id, name, tag_type="auto")
            if tag:
                apply_tag_to_lead(db, lead_id, tag, applied_by="bot")
        except Exception as e:
            logger.error(f"auto_tag_lead failed for '{name}': {e}")
