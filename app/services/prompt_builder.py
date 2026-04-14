"""
Dynamic Prompt Builder
Assembles the system prompt from live database data on every message.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.business import Business, Product
from app.models.conversation import Conversation, Message
from app.models.lead import Lead

logger = logging.getLogger(__name__)


# ============================================================
# INVENTORY SECTION (DYNAMIC — generated from products table)
# ============================================================

def format_inventory_section(products: list[Product]) -> str:
    """Generate the inventory section from live product data."""
    if not products:
        return "\n\n=== INVENTORY ===\nNo products currently loaded.\n================\n"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n\n=== CURRENT INVENTORY (Updated: {now}) ===\n"]

    # Group by category
    categories = {}
    for p in products:
        cat = p.category or "General"
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(p)

    for cat, items in categories.items():
        lines.append(f"\n{cat}:")
        for p in items:
            price_str = f"${p.price} {p.currency}" if p.price else "Price TBD"

            # Handle variants (e.g., sizes) vs simple quantity
            if p.variants and isinstance(p.variants, dict):
                stock_parts = []
                for variant, qty in p.variants.items():
                    if qty == 0:
                        stock_parts.append(f"{variant}(0-OUT OF STOCK)")
                    else:
                        stock_parts.append(f"{variant}({qty})")
                stock_str = " ".join(stock_parts)
            else:
                qty = p.quantity or 0
                if qty == 0:
                    stock_str = "OUT OF STOCK"
                else:
                    stock_str = f"{qty} in stock"

            status_note = ""
            if p.status == "out_of_stock" or (p.quantity is not None and p.quantity == 0):
                status_note = " [OUT OF STOCK]"

            lines.append(f"- {p.name}: {stock_str} - {price_str}{status_note}")
            if p.description:
                lines.append(f"  {p.description}")

    lines.append("\nINVENTORY RULES:")
    lines.append("- NEVER offer items marked OUT OF STOCK. Suggest alternatives.")
    lines.append("- Always quote prices as shown above.")
    lines.append("- If asked about a product not in this list, say you'll check with the team and escalate.")
    lines.append("==========================================\n")

    return "\n".join(lines)


# ============================================================
# CUSTOMER CONTEXT (DYNAMIC — for returning customers)
# ============================================================

def format_customer_context(
    recent_messages: list[Message],
    leads: list[Lead],
) -> str:
    """Build customer context from past interactions."""
    lines = ["\n\n=== CUSTOMER CONTEXT ==="]
    lines.append("This is a returning customer.")

    if leads:
        lead = leads[0]  # Most recent lead record
        if lead.name:
            lines.append(f"Name: {lead.name}")
        if lead.phone:
            lines.append(f"Phone: {lead.phone}")
        if lead.interest:
            lines.append(f"Previous interest: {lead.interest}")

    if recent_messages:
        last_date = recent_messages[-1].timestamp
        if last_date:
            lines.append(f"Last interaction: {last_date.strftime('%Y-%m-%d')}")

    lines.append("\nUse this context to personalize. Don't ask for info you already have.")
    lines.append("===========================\n")

    return "\n".join(lines)


# ============================================================
# AD CONTEXT (DYNAMIC — injected for CTWA ad clicks)
# ============================================================

def get_ad_context_instructions() -> str:
    return """

=== AD CONTEXT ===
This customer clicked a Click-to-WhatsApp ad.
You have 72 hours of free messaging (no Meta fees).

Behavior adjustments:
- Be more proactive with product recommendations
- After answering their question, suggest related items
- Encourage them to place an order now
- You can send promotional content freely in this window
- If they mention the specific ad/product they saw, lead with that product
================
"""


# ============================================================
# MAIN PROMPT BUILDER
# ============================================================

async def build_system_prompt(
    db: Session,
    business_id: str,
    external_user_id: str,
    metadata: dict = None,
) -> str:
    """
    Dynamically assemble the full system prompt.
    Called on every incoming message.
    """
    # Load business
    business = db.query(Business).filter(
        Business.id == uuid.UUID(business_id)
    ).first()

    if not business:
        return "You are a helpful AI assistant."

    # Start with static base prompt (identity, tone, FAQ, escalation, boundaries)
    prompt = business.base_prompt or "You are a helpful AI assistant."

    # Add live inventory from products table
    products = (
        db.query(Product)
        .filter(
            Product.business_id == uuid.UUID(business_id),
            Product.status != "discontinued",
        )
        .all()
    )
    prompt += format_inventory_section(products)

    # Add customer context if returning customer
    past_convos = (
        db.query(Conversation)
        .filter(
            Conversation.business_id == uuid.UUID(business_id),
            Conversation.external_user_id == external_user_id,
        )
        .all()
    )

    if len(past_convos) > 1:  # They've been here before
        # Get recent messages across past conversations
        past_convo_ids = [c.id for c in past_convos[:-1]]  # Exclude current
        recent_msgs = (
            db.query(Message)
            .filter(Message.conversation_id.in_(past_convo_ids))
            .order_by(Message.timestamp.desc())
            .limit(5)
            .all()
        )

        # Check for existing lead records
        leads = (
            db.query(Lead)
            .filter(Lead.business_id == uuid.UUID(business_id))
            .filter(
                (Lead.phone == external_user_id) |
                (Lead.name == external_user_id)
            )
            .order_by(Lead.created_at.desc())
            .limit(1)
            .all()
        )

        if recent_msgs or leads:
            prompt += format_customer_context(recent_msgs, leads)

    # Add ad context if from CTWA ad
    if metadata and metadata.get("source") == "ctwa_ad":
        prompt += get_ad_context_instructions()

    return prompt
