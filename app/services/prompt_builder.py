"""
Dynamic Prompt Builder - UPDATED for Phase 6
=============================================

Changes from original:
- Uses Redis cache for business + product data (faster)
- Adds tool usage guidelines section to every prompt
- Condensed product format (saves tokens)
- Conditional product inclusion (skips for smalltalk)
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message
from app.models.lead import Lead
from app.services.cache import BusinessCache, ProductCache

logger = logging.getLogger(__name__)


# ============================================================
# TOOL USAGE GUIDELINES
# Added to every prompt so LLM knows when/how to use tools
# ============================================================

TOOL_GUIDELINES = """
=== TOOL USAGE GUIDELINES ===
You have access to tools. Use them proactively - don't describe what you'll do, just do it.

ALWAYS use tools when:
- Customer asks about a product → check_stock()
- Customer wants to know total cost → calculate_total()
- Customer provides name + address + phone (any order) → place_order() IMMEDIATELY
- Customer says "cancel" + has an order → cancel_order()
- Customer asks to see product photo/video → send_product_media()
- Customer asks to speak to a human → escalate_to_human()
- Customer is clearly frustrated or angry → escalate_to_human()
- You can tell what kind of conversation this is → update_lead_status()

ORDERING RULES (CRITICAL):
- Required to place order: customer_name AND delivery_address AND customer_phone
- If all 3 provided → place_order() IMMEDIATELY. Do NOT ask "are you sure?"
- If missing 1 piece → ask ONLY for that specific missing piece
- Product comes from conversation context (what they said they want)
- After placing order → send the confirmation_message from the result

LEAD CLASSIFICATION:
- Update early and often as the conversation reveals intent
- hot = they ordered or are about to order
- warm = asking about specific products
- cold = general browsing
- post_purchase = asking about an existing order
- support = has a problem or complaint
- spam = irrelevant/abusive
==============================
"""


# ============================================================
# INVENTORY SECTION
# Condensed format to save tokens
# ============================================================

def format_inventory_section(products: list) -> str:
    """
    Format product list into condensed prompt section.
    Uses pipe-separated format to minimize token usage.
    """
    if not products:
        return "\n\n=== INVENTORY ===\nNo products currently loaded.\n================\n"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n\n=== CURRENT INVENTORY (Updated: {now}) ==="]

    # Group by category
    categories = {}
    for p in products:
        cat = p.get('category') or 'General'
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(p)

    for cat, items in categories.items():
        lines.append(f"\n{cat}:")
        for p in items:
            price = p.get('price', 'TBD')
            qty = p.get('quantity', 0) or 0
            status = p.get('status', 'active')

            # Condensed format: Name | Price | Stock
            if status == 'out_of_stock' or qty == 0:
                stock_str = "OUT OF STOCK"
            else:
                stock_str = f"{qty} available"

            # Handle variants
            variants = p.get('variants')
            if variants and isinstance(variants, dict):
                variant_parts = []
                for variant, variant_qty in variants.items():
                    if variant_qty == 0:
                        variant_parts.append(f"{variant}(out)")
                    else:
                        variant_parts.append(f"{variant}({variant_qty})")
                stock_str = " ".join(variant_parts)

            line = f"- {p['name']} | ${price} TTD | {stock_str}"
            if p.get('description'):
                # Truncate description to save tokens
                desc = p['description'][:80]
                line += f" | {desc}"
            lines.append(line)

    lines.append("\nINVENTORY RULES:")
    lines.append("- NEVER offer OUT OF STOCK items. Suggest alternatives.")
    lines.append("- Always quote prices as shown. Currency is TTD.")
    lines.append("- If asked about a product not listed, use check_stock() then escalate if not found.")
    lines.append("==========================================\n")

    return "\n".join(lines)


# ============================================================
# CUSTOMER CONTEXT (for returning customers)
# ============================================================

def format_customer_context(
    recent_messages: list,
    leads: list,
) -> str:
    lines = ["\n\n=== CUSTOMER CONTEXT ==="]
    lines.append("This is a returning customer.")

    if leads:
        lead = leads[0]
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
# AD CONTEXT
# ============================================================

def get_ad_context_instructions() -> str:
    return """
=== AD CONTEXT ===
This customer clicked a Click-to-WhatsApp ad.
You have 72 hours of free messaging (no Meta fees).

Behavior:
- Be proactive with product recommendations
- If they provide name + address + phone → place_order() immediately
- You can send promotional content freely in this window
- Lead with whatever product/offer they clicked on
================
"""


# ============================================================
# SHOULD INCLUDE PRODUCTS?
# Skip product list for pure smalltalk to save tokens
# ============================================================

def _should_include_products(message_text: str, message_count: int) -> bool:
    """Only skip products for pure smalltalk to save tokens."""
    # Always include on first message
    if message_count <= 1:
        return True

    # Skip for pure smalltalk
    smalltalk = {'hi', 'hello', 'hey', 'thanks', 'thank you', 'ok',
                 'okay', 'bye', 'goodbye', 'yes', 'no', 'k', 'lol'}
    if message_text.lower().strip() in smalltalk:
        return False

    # Default: include (safer for accuracy)
    return True


# ============================================================
# MAIN PROMPT BUILDER
# ============================================================

async def build_system_prompt(
    db: Session,
    business_id: str,
    external_user_id: str,
    metadata: dict = None,
    message_count: int = 1,
) -> str:
    """
    Dynamically assemble the full system prompt.
    Called on every incoming message.

    Phase 6 changes:
    - Uses BusinessCache + ProductCache (faster, less DB load)
    - Adds TOOL_GUIDELINES section
    - Condensed product format
    - Conditional product inclusion
    """
    # Load business from cache
    business_dict = BusinessCache.get(db, business_id)

    if not business_dict:
        return "You are a helpful AI assistant."

    # Start with the business base_prompt
    prompt = business_dict.get('base_prompt') or "You are a helpful AI assistant."

    # Add tool usage guidelines
    prompt += TOOL_GUIDELINES

    # Add live inventory (from cache)
    if _should_include_products("", message_count):
        products = ProductCache.get_products(db, business_id)
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

    if len(past_convos) > 1:
        past_convo_ids = [c.id for c in past_convos[:-1]]
        recent_msgs = (
            db.query(Message)
            .filter(Message.conversation_id.in_(past_convo_ids))
            .order_by(Message.timestamp.desc())
            .limit(5)
            .all()
        )

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