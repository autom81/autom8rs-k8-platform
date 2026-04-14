"""
OpenRouter LLM Integration
Handles model selection and client initialization.
"""
import logging
import uuid

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.models.business import Business

logger = logging.getLogger(__name__)

# Initialize the OpenRouter client
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENROUTER_API_KEY,
)

# Model constants
MODEL_GEMMA = "google/gemma-4-26b-a4b-it"
MODEL_CLAUDE = "anthropic/claude-sonnet-4-5-20250514"


def _has_image_indicator(text: str) -> bool:
    """Check if the message indicates an image was sent."""
    indicators = ["[Image]", "[Document]", "image", "photo", "picture", "screenshot"]
    return any(ind.lower() in text.lower() for ind in indicators)


def _needs_complex_reasoning(text: str) -> bool:
    """
    Simple heuristic for routing to Claude.
    Can be made more sophisticated over time.
    """
    complex_indicators = [
        "compare", "analyze", "calculate", "summarize this document",
        "what does this image show", "read this receipt",
        "create a detailed", "step by step plan",
    ]
    text_lower = text.lower()
    return any(ind in text_lower for ind in complex_indicators)


async def select_model(business_id: str, message_text: str, db: Session = None) -> str:
    """
    Select the appropriate model based on business tier and message content.
    Starter/Pro always use Gemma (cheap).
    Ultra/Custom route complex tasks to Claude.
    """
    if db:
        business = db.query(Business).filter(
            Business.id == uuid.UUID(business_id)
        ).first()
    else:
        business = None

    tier = business.tier if business else "pro"

    if tier in ("starter", "pro"):
        return MODEL_GEMMA

    # Ultra/Custom: check if we should upgrade to Claude
    if _has_image_indicator(message_text):
        logger.info(f"Routing to Claude (image detected) for business={business_id[:8]}")
        return MODEL_CLAUDE

    if _needs_complex_reasoning(message_text):
        logger.info(f"Routing to Claude (complex reasoning) for business={business_id[:8]}")
        return MODEL_CLAUDE

    return MODEL_GEMMA  # Default to cheap model
