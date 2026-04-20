"""
Analytics API Routes — Phase 7A Step 4
=======================================
All endpoints are scoped to business_id from the JWT cookie.
All queries use the synchronous SQLAlchemy ORM.

Endpoints:
  GET /api/analytics/overview          — summary cards + 30-day charts + recent items
  GET /api/analytics/conversations     — conversations over time (param: days)
  GET /api/analytics/leads             — lead funnel with conversion + drop-off rates
  GET /api/analytics/orders            — orders + revenue over time (param: days)
  GET /api/analytics/heatmap           — message volume by hour × day-of-week
  GET /api/analytics/channels          — conversation counts by channel
"""
import uuid
import logging
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, cast, and_, Date as SADate
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.conversation import Conversation, Message, ConvoStatusEnum
from app.models.lead import Lead, LeadStatusEnum, Order, OrderStatusEnum
from app.routes.dashboard import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# ═══════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════

def _biz_uuid(current_user: dict) -> uuid.UUID:
    return uuid.UUID(current_user["business_id"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_start() -> datetime:
    n = _now()
    return datetime(n.year, n.month, n.day, tzinfo=timezone.utc)


def _month_start() -> datetime:
    n = _now()
    return datetime(n.year, n.month, 1, tzinfo=timezone.utc)


def _days_ago(days: int) -> datetime:
    return _now() - timedelta(days=days)


def _flt(val) -> float:
    """Convert Decimal or None to float."""
    if val is None:
        return 0.0
    return float(val)


def _date_series(days: int) -> list[str]:
    """Return ISO date strings for the last `days` days, oldest first."""
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def _fill_chart(raw_rows, date_key: str, days: int, *value_keys: str) -> list[dict]:
    """
    Merge DB rows into a zero-filled series for every day in the window.
    raw_rows: list of SQLAlchemy Row objects with a `date_key` attribute
              and one or more `value_keys` attributes.
    """
    series = _date_series(days)
    # Build lookup: date_str → row
    lookup: dict[str, object] = {}
    for row in raw_rows:
        d = row[0]
        # d is a Python date object from cast(…, SADate)
        lookup[str(d)] = row

    result = []
    for ds in series:
        row = lookup.get(ds)
        entry: dict = {date_key: ds}
        for i, vk in enumerate(value_keys):
            raw = row[i + 1] if row is not None else None
            entry[vk] = _flt(raw)
        result.append(entry)
    return result


# ═══════════════════════════════════════════════════════════════════
# GET /api/analytics/overview
# ═══════════════════════════════════════════════════════════════════

@router.get("/overview")
def analytics_overview(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = _biz_uuid(current_user)
    today = _today_start()
    month = _month_start()
    thirty_days_ago = _days_ago(30)
    since = _days_ago(days)
    prev_since = _days_ago(days * 2)

    # ── Today counts ─────────────────────────────────────────────

    conversations_today = db.query(func.count(Conversation.id)).filter(
        Conversation.business_id == biz_id,
        Conversation.started_at >= today,
    ).scalar() or 0

    leads_today = db.query(func.count(Lead.id)).filter(
        Lead.business_id == biz_id,
        Lead.created_at >= today,
    ).scalar() or 0

    orders_today = db.query(func.count(Order.id)).filter(
        Order.business_id == biz_id,
        Order.created_at >= today,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar() or 0

    revenue_today = db.query(func.sum(Order.total)).filter(
        Order.business_id == biz_id,
        Order.created_at >= today,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar()

    # ── This-month counts ─────────────────────────────────────────

    conversations_this_month = db.query(func.count(Conversation.id)).filter(
        Conversation.business_id == biz_id,
        Conversation.started_at >= month,
    ).scalar() or 0

    orders_this_month = db.query(func.count(Order.id)).filter(
        Order.business_id == biz_id,
        Order.created_at >= month,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar() or 0

    revenue_this_month = db.query(func.sum(Order.total)).filter(
        Order.business_id == biz_id,
        Order.created_at >= month,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar()

    # ── Avg response time (seconds) ───────────────────────────────
    # Computed as: mean of (last_message_at - started_at) / (message_count - 1)
    # for conversations this month that have at least 2 messages.
    convs_for_rt = db.query(
        Conversation.started_at,
        Conversation.last_message_at,
        Conversation.message_count,
    ).filter(
        Conversation.business_id == biz_id,
        Conversation.started_at >= month,
        Conversation.message_count > 1,
        Conversation.last_message_at.isnot(None),
    ).limit(500).all()

    avg_response_time_seconds = 0.0
    if convs_for_rt:
        gaps = []
        for row in convs_for_rt:
            started = row.started_at
            last = row.last_message_at
            count = row.message_count or 2
            if last and started and last > started:
                gap = (last - started).total_seconds() / (count - 1)
                gaps.append(gap)
        if gaps:
            avg_response_time_seconds = round(sum(gaps) / len(gaps), 1)

    # ── 30-day conversations chart ────────────────────────────────

    conv_date_col = cast(func.date_trunc("day", Conversation.started_at), SADate)
    conv_chart_rows = (
        db.query(conv_date_col.label("date"), func.count(Conversation.id).label("count"))
        .filter(
            Conversation.business_id == biz_id,
            Conversation.started_at >= thirty_days_ago,
        )
        .group_by(conv_date_col)
        .all()
    )
    conversations_chart = _fill_chart(conv_chart_rows, "date", 30, "count")

    # ── 30-day orders + revenue chart ────────────────────────────

    ord_date_col = cast(func.date_trunc("day", Order.created_at), SADate)
    ord_chart_rows = (
        db.query(
            ord_date_col.label("date"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total), 0).label("revenue"),
        )
        .filter(
            Order.business_id == biz_id,
            Order.created_at >= thirty_days_ago,
            Order.status != OrderStatusEnum.cancelled,
        )
        .group_by(ord_date_col)
        .all()
    )
    orders_revenue_chart = _fill_chart(ord_chart_rows, "date", 30, "orders", "revenue")

    # ── Recent orders (last 5) ────────────────────────────────────

    recent_orders_rows = (
        db.query(Order)
        .filter(Order.business_id == biz_id)
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )
    recent_orders = [
        {
            "id": str(o.id),
            "order_number": o.order_number,
            "customer_name": o.customer_name,
            "total": _flt(o.total),
            "status": o.status.value if hasattr(o.status, "value") else o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in recent_orders_rows
    ]

    # ── Recent escalations (last 5) ──────────────────────────────

    recent_esc_rows = (
        db.query(Conversation)
        .filter(
            Conversation.business_id == biz_id,
            Conversation.status == ConvoStatusEnum.escalated,
        )
        .order_by(Conversation.last_message_at.desc())
        .limit(5)
        .all()
    )

    # Bulk-fetch leads for these conversations
    esc_ids = [c.id for c in recent_esc_rows]
    leads_by_conv: dict[uuid.UUID, Lead] = {}
    if esc_ids:
        for lead in db.query(Lead).filter(Lead.conversation_id.in_(esc_ids)).all():
            leads_by_conv[lead.conversation_id] = lead

    recent_escalations = [
        {
            "id": str(c.id),
            "channel": c.channel.value if hasattr(c.channel, "value") else c.channel,
            "escalation_reason": c.escalation_reason,
            "lead_name": leads_by_conv[c.id].name if c.id in leads_by_conv else None,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        }
        for c in recent_esc_rows
    ]

    # ── Reports: comparison-period counts ─────────────────────────
    conv_current = db.query(func.count(Conversation.id)).filter(
        Conversation.business_id == biz_id,
        Conversation.started_at >= since,
    ).scalar() or 0

    conv_prev = db.query(func.count(Conversation.id)).filter(
        Conversation.business_id == biz_id,
        Conversation.started_at >= prev_since,
        Conversation.started_at < since,
    ).scalar() or 0

    orders_current = db.query(func.count(Order.id)).filter(
        Order.business_id == biz_id,
        Order.created_at >= since,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar() or 0

    orders_prev = db.query(func.count(Order.id)).filter(
        Order.business_id == biz_id,
        Order.created_at >= prev_since,
        Order.created_at < since,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar() or 0

    revenue_current = _flt(db.query(func.sum(Order.total)).filter(
        Order.business_id == biz_id,
        Order.created_at >= since,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar())

    revenue_prev = _flt(db.query(func.sum(Order.total)).filter(
        Order.business_id == biz_id,
        Order.created_at >= prev_since,
        Order.created_at < since,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar())

    total_leads_current = db.query(func.count(Lead.id)).filter(
        Lead.business_id == biz_id,
        Lead.created_at >= since,
    ).scalar() or 0

    converted_leads_current = db.query(func.count(Lead.id)).filter(
        Lead.business_id == biz_id,
        Lead.created_at >= since,
        Lead.status == LeadStatusEnum.converted,
    ).scalar() or 0

    total_leads_prev = db.query(func.count(Lead.id)).filter(
        Lead.business_id == biz_id,
        Lead.created_at >= prev_since,
        Lead.created_at < since,
    ).scalar() or 0

    converted_leads_prev = db.query(func.count(Lead.id)).filter(
        Lead.business_id == biz_id,
        Lead.created_at >= prev_since,
        Lead.created_at < since,
        Lead.status == LeadStatusEnum.converted,
    ).scalar() or 0

    lcr_current = round(converted_leads_current / total_leads_current * 100, 1) if total_leads_current else 0.0
    lcr_prev = round(converted_leads_prev / total_leads_prev * 100, 1) if total_leads_prev else 0.0

    return {
        # Today
        "conversations_today": conversations_today,
        "leads_today": leads_today,
        "orders_today": orders_today,
        "revenue_today": _flt(revenue_today),
        "avg_response_time_seconds": avg_response_time_seconds,
        # This month
        "conversations_this_month": conversations_this_month,
        "orders_this_month": orders_this_month,
        "revenue_this_month": _flt(revenue_this_month),
        # Charts
        "conversations_chart": conversations_chart,
        "orders_revenue_chart": orders_revenue_chart,
        # Recent items
        "recent_orders": recent_orders,
        "recent_escalations": recent_escalations,
        # Dashboard summary alias (matches AnalyticsOverview TypeScript interface)
        "summary": {
            "customers_served": conversations_this_month,
            "revenue_ttd": _flt(revenue_this_month),
            "orders_placed": orders_this_month,
            "avg_response_time_minutes": round(avg_response_time_seconds / 60, 2),
        },
        # Reports-page shape: current period vs previous period
        "conversations": {
            "current": conv_current,
            "previous": conv_prev,
            "trend_pct": _trend_pct(conv_current, conv_prev) or 0.0,
        },
        "orders": {
            "current": orders_current,
            "previous": orders_prev,
            "trend_pct": _trend_pct(orders_current, orders_prev) or 0.0,
        },
        "revenue": {
            "current": revenue_current,
            "previous": revenue_prev,
            "trend_pct": _trend_pct(revenue_current, revenue_prev) or 0.0,
        },
        "lead_conversion_rate": {
            "current": lcr_current,
            "previous": lcr_prev,
            "trend_pct": _trend_pct(lcr_current, lcr_prev) or 0.0,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# GET /api/analytics/conversations
# ═══════════════════════════════════════════════════════════════════

@router.get("/conversations")
def analytics_conversations(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = _biz_uuid(current_user)
    since = _days_ago(days)

    date_col = cast(func.date_trunc("day", Conversation.started_at), SADate)
    rows = (
        db.query(date_col.label("date"), func.count(Conversation.id).label("count"))
        .filter(
            Conversation.business_id == biz_id,
            Conversation.started_at >= since,
        )
        .group_by(date_col)
        .all()
    )

    chart = _fill_chart(rows, "date", days, "count")

    total = sum(p["count"] for p in chart)
    prev_total = db.query(func.count(Conversation.id)).filter(
        Conversation.business_id == biz_id,
        Conversation.started_at >= _days_ago(days * 2),
        Conversation.started_at < since,
    ).scalar() or 0

    return {
        "chart": chart,
        "data": chart,
        "total": int(total),
        "previous_period_total": int(prev_total),
        "trend_pct": _trend_pct(total, prev_total),
        "days": days,
    }


# ═══════════════════════════════════════════════════════════════════
# GET /api/analytics/leads
# ═══════════════════════════════════════════════════════════════════

# Ordered funnel stages — top to bottom of the sales funnel
_FUNNEL_STAGES = [
    LeadStatusEnum.new,
    LeadStatusEnum.attempted_contact,
    LeadStatusEnum.connected,
    LeadStatusEnum.qualified,
    LeadStatusEnum.converted,
]

_SIDE_STAGES = [
    LeadStatusEnum.nurture,
    LeadStatusEnum.unqualified,
    LeadStatusEnum.lost,
]


_FUNNEL_LABELS = {
    "new": "New Lead",
    "attempted_contact": "Contacted",
    "connected": "Connected",
    "qualified": "Qualified",
    "converted": "Converted",
}


@router.get("/leads/funnel")
def analytics_leads_funnel(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = _biz_uuid(current_user)
    since = _days_ago(days)

    rows = (
        db.query(Lead.status, func.count(Lead.id).label("count"))
        .filter(Lead.business_id == biz_id, Lead.created_at >= since)
        .group_by(Lead.status)
        .all()
    )
    counts: dict[str, int] = {
        (r.status.value if hasattr(r.status, "value") else r.status): r.count
        for r in rows
    }

    top_count = counts.get("new", 0) or 1
    stages = []
    for i, stage in enumerate(_FUNNEL_STAGES):
        stage_val = stage.value
        count = counts.get(stage_val, 0)
        prev_count = counts.get(_FUNNEL_STAGES[i - 1].value, 0) if i > 0 else count
        stages.append({
            "stage": stage_val,
            "label": _FUNNEL_LABELS.get(stage_val, stage_val.replace("_", " ").title()),
            "count": count,
            "conversion_rate": round(count / top_count * 100, 1) if top_count else 0.0,
            "avg_days_in_stage": 0,
            "drop_off_rate": round((prev_count - count) / prev_count * 100, 1) if prev_count and i > 0 else 0.0,
        })

    return {"stages": stages}


@router.get("/leads")
def analytics_leads(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = _biz_uuid(current_user)

    # Count leads at every status in one query
    rows = (
        db.query(Lead.status, func.count(Lead.id).label("count"))
        .filter(Lead.business_id == biz_id)
        .group_by(Lead.status)
        .all()
    )
    counts: dict[str, int] = {
        (r.status.value if hasattr(r.status, "value") else r.status): r.count
        for r in rows
    }

    total_leads = sum(counts.values())

    # Build funnel (ordered stages)
    funnel = []
    top_count = counts.get(LeadStatusEnum.new.value, 0) or 1  # avoid div-by-zero

    for i, stage in enumerate(_FUNNEL_STAGES):
        stage_val = stage.value
        count = counts.get(stage_val, 0)
        prev_count = counts.get(_FUNNEL_STAGES[i - 1].value, 0) if i > 0 else count

        conversion_rate = round(count / top_count * 100, 1) if top_count else 0.0
        drop_off_rate = round((prev_count - count) / prev_count * 100, 1) if prev_count and i > 0 else 0.0

        funnel.append({
            "status": stage_val,
            "count": count,
            "conversion_rate": conversion_rate,    # % of top-of-funnel that reached this stage
            "drop_off_rate": drop_off_rate,         # % lost from previous stage to this one
        })

    # Side stages (not part of the main funnel flow)
    side = [
        {"status": s.value, "count": counts.get(s.value, 0)}
        for s in _SIDE_STAGES
    ]

    # Classification breakdown
    classification_rows = (
        db.query(Lead.classification, func.count(Lead.id).label("count"))
        .filter(Lead.business_id == biz_id)
        .group_by(Lead.classification)
        .all()
    )
    classification_breakdown = [
        {
            "classification": r.classification.value if hasattr(r.classification, "value") else r.classification,
            "count": r.count,
        }
        for r in classification_rows
        if r.classification is not None
    ]

    return {
        "funnel": funnel,
        "side_stages": side,
        "classification_breakdown": classification_breakdown,
        "total_leads": total_leads,
    }


# ═══════════════════════════════════════════════════════════════════
# GET /api/analytics/orders
# ═══════════════════════════════════════════════════════════════════

@router.get("/orders")
def analytics_orders(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = _biz_uuid(current_user)
    since = _days_ago(days)

    date_col = cast(func.date_trunc("day", Order.created_at), SADate)
    rows = (
        db.query(
            date_col.label("date"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total), 0).label("revenue"),
        )
        .filter(
            Order.business_id == biz_id,
            Order.created_at >= since,
            Order.status != OrderStatusEnum.cancelled,
        )
        .group_by(date_col)
        .all()
    )

    chart = _fill_chart(rows, "date", days, "orders", "revenue")

    total_orders = int(sum(p["orders"] for p in chart))
    total_revenue = round(sum(p["revenue"] for p in chart), 2)

    # Status breakdown for the period
    status_rows = (
        db.query(Order.status, func.count(Order.id).label("count"))
        .filter(
            Order.business_id == biz_id,
            Order.created_at >= since,
        )
        .group_by(Order.status)
        .all()
    )
    status_breakdown = [
        {
            "status": r.status.value if hasattr(r.status, "value") else r.status,
            "count": r.count,
        }
        for r in status_rows
    ]

    # Previous period for trend
    prev_revenue = db.query(func.sum(Order.total)).filter(
        Order.business_id == biz_id,
        Order.created_at >= _days_ago(days * 2),
        Order.created_at < since,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar() or 0

    return {
        "chart": chart,
        "data": chart,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "previous_period_revenue": _flt(prev_revenue),
        "revenue_trend_pct": _trend_pct(total_revenue, float(prev_revenue)),
        "status_breakdown": status_breakdown,
        "days": days,
    }


# ═══════════════════════════════════════════════════════════════════
# GET /api/analytics/heatmap
# ═══════════════════════════════════════════════════════════════════

@router.get("/heatmap")
def analytics_heatmap(
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Message volume grouped by hour-of-day (0–23) and day-of-week (0–6).
    PostgreSQL EXTRACT('dow', ...) returns 0=Sunday … 6=Saturday.
    """
    biz_id = _biz_uuid(current_user)
    since = _days_ago(days)

    hour_col = func.extract("hour", Message.timestamp).label("hour")
    dow_col = func.extract("dow", Message.timestamp).label("day_of_week")

    rows = (
        db.query(
            hour_col,
            dow_col,
            func.count(Message.id).label("count"),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.business_id == biz_id,
            Message.timestamp >= since,
        )
        .group_by(hour_col, dow_col)
        .all()
    )

    # Build a complete 24×7 grid with 0 fill
    grid: dict[tuple[int, int], int] = {}
    for row in rows:
        grid[(int(row.hour), int(row.day_of_week))] = row.count

    heatmap = [
        {
            "hour": h,
            "day_of_week": d,
            "count": grid.get((h, d), 0),
        }
        for h in range(24)
        for d in range(7)
    ]

    peak = max(heatmap, key=lambda x: x["count"]) if heatmap else None

    # Build 2D grid [day_of_week 0-6][hour 0-23] for frontend HeatmapGrid component
    _DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    grid_lookup: dict[tuple[int, int], int] = {(e["day_of_week"], e["hour"]): e["count"] for e in heatmap}
    grid = [
        [grid_lookup.get((dow, h), 0) for h in range(24)]
        for dow in range(7)
    ]
    max_value = max((max(row) for row in grid if row), default=0)

    return {
        "heatmap": heatmap,
        "peak": peak,
        "days_sampled": days,
        "grid": grid,
        "max_value": max_value,
        "days": _DAY_LABELS,
    }


# ═══════════════════════════════════════════════════════════════════
# GET /api/analytics/channels
# ═══════════════════════════════════════════════════════════════════

@router.get("/channels")
def analytics_channels(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = _biz_uuid(current_user)
    since = _days_ago(days)

    rows = (
        db.query(Conversation.channel, func.count(Conversation.id).label("count"))
        .filter(
            Conversation.business_id == biz_id,
            Conversation.started_at >= since,
        )
        .group_by(Conversation.channel)
        .all()
    )

    total = sum(r.count for r in rows) or 1  # avoid div-by-zero

    channels = [
        {
            "channel": r.channel.value if hasattr(r.channel, "value") else r.channel,
            "count": r.count,
            "percentage": round(r.count / total * 100, 1),
        }
        for r in rows
    ]
    channels.sort(key=lambda x: x["count"], reverse=True)

    return {
        "channels": channels,
        "total": total,
        "days": days,
    }


# ═══════════════════════════════════════════════════════════════════
# INTERNAL UTIL
# ═══════════════════════════════════════════════════════════════════

def _trend_pct(current: float, previous: float) -> Optional[float]:
    """Percentage change from previous to current period. None if no prior data."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)
