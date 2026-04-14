"""
Core Message Handler
The brain of K8. Every channel funnels into handle_message().
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.conversation import Conversation, Message
from app.models.business import Business, Product
from app.services.llm import client as openrouter_client, select_model
from app.services.prompt_builder import build_system_prompt
from app.services.meta import send_reply, download_whatsapp_media

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE HELPERS
# ============================================================

def _get_db():
    """Get a fresh DB session for background tasks."""
    return SessionLocal()


def get_or_create_conversation(
    db: Session,
    business_id: str,
    external_user_id: str,
    channel: str,
    metadata: dict = None,
) -> Conversation:
    """Find existing active conversation or create a new one."""
    convo = (
        db.query(Conversation)
        .filter(
            Conversation.business_id == uuid.UUID(business_id),
            Conversation.external_user_id == external_user_id,
            Conversation.channel == channel,
            Conversation.status.in_(["active", "escalated"]),
        )
        .first()
    )

    if convo:
        convo.last_message_at = datetime.now(timezone.utc)
        db.commit()
        return convo

    source = "organic"
    if metadata and metadata.get("source") == "ctwa_ad":
        source = "ctwa_ad"

    convo = Conversation(
        id=uuid.uuid4(),
        business_id=uuid.UUID(business_id),
        external_user_id=external_user_id,
        channel=channel,
        status="active",
        source=source,
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


def save_message(
    db: Session,
    conversation_id,
    role: str,
    content: str,
    media_url: str = None,
    media_type: str = None,
    was_voice_note: bool = False,
    original_transcript: str = None,
):
    """Save a message to the database."""
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role=role,
        content=content,
        media_url=media_url,
        media_type=media_type,
        was_voice_note=was_voice_note,
        original_transcript=original_transcript,
    )
    db.add(msg)
    db.commit()
    return msg


def get_recent_messages(db: Session, conversation_id, limit: int = 10) -> list[dict]:
    """Load recent messages for conversation context."""
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {"role": m.role, "content": m.content}
        for m in reversed(messages)
    ]


def get_business(db: Session, business_id: str) -> Business:
    """Load business record."""
    return db.query(Business).filter(
        Business.id == uuid.UUID(business_id)
    ).first()


# ============================================================
# LLM CALL
# ============================================================

async def call_llm(model: str, messages: list, tools: list = None):
    """Call OpenRouter and return the response."""
    kwargs = {
        "model": model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    try:
        response = await openrouter_client.chat.completions.create(**kwargs)
        return response
    except Exception as e:
        logger.error(f"OpenRouter API error: {e}")
        return None


def extract_reply(response) -> str:
    """Extract the text reply from an OpenRouter response."""
    if not response:
        return "I'm having a little trouble right now. Please try again in a moment."

    try:
        choice = response.choices[0]
        message = choice.message

        if message.content:
            return message.content

        if message.tool_calls:
            logger.info(f"LLM returned tool calls: {[tc.function.name for tc in message.tool_calls]}")
            # TODO: Execute tool calls and feed results back to LLM
            return "Let me look into that for you..."

        return "I'm not sure how to respond to that. Let me escalate to the team."

    except Exception as e:
        logger.error(f"Error extracting reply: {e}")
        return "I'm having a little trouble right now. Please try again in a moment."


# ============================================================
# CORE MESSAGE HANDLER
# ============================================================

async def handle_message(
    business_id: str,
    channel: str,
    external_user_id: str,
    message_text: str,
    media_url: str = None,
    media_type: str = None,
    message_metadata: dict = None,
    phone_number_id: str = None,
    db: Session = None,
):
    """
    Process an incoming message from any channel.
    Called as a background task from the webhook handler.
    """
    own_db = False
    if db is None:
        db = _get_db()
        own_db = True

    try:
        # 1. Load business
        business = get_business(db, business_id)
        if not business:
            logger.error(f"Business not found: {business_id}")
            return

        # 2. Get or create conversation
        conversation = get_or_create_conversation(
            db, business_id, external_user_id, channel, message_metadata
        )

        # 3. If escalated, save message but don't auto-reply
        if conversation.status == "escalated":
            save_message(db, conversation.id, "user", message_text,
                        media_url=media_url, media_type=media_type)
            logger.info(f"Conversation {conversation.id} is escalated — skipping auto-reply")
            return

        # 4. Handle voice notes
        voice_transcript = None
        if media_type == "audio" and media_url:
            if channel == "whatsapp":
                audio_bytes = await download_whatsapp_media(media_url)
                if audio_bytes:
                    # TODO: Whisper transcription
                    voice_transcript = "[Voice note received — transcription coming soon]"
                    message_text = voice_transcript
                else:
                    message_text = "[Voice note — could not download]"
            else:
                voice_transcript = "[Voice note received — transcription coming soon]"
                message_text = voice_transcript

        # 5. Save the user's message
        save_message(
            db, conversation.id, "user", message_text,
            media_url=media_url, media_type=media_type,
            was_voice_note=(media_type == "audio"),
            original_transcript=voice_transcript,
        )

        # 6. Build dynamic system prompt
        system_prompt = await build_system_prompt(
            db, business_id, external_user_id, message_metadata
        )

        # 7. Load conversation history
        history = get_recent_messages(db, conversation.id, limit=10)

        # 8. Build messages for LLM (history already includes the latest user message)
        llm_messages = [
            {"role": "system", "content": system_prompt},
            *history,
        ]

        # 9. Select model
        model = await select_model(business_id, message_text, db)

        # 10. Call LLM
        response = await call_llm(model, llm_messages)

        # 11. Extract reply
        reply_text = extract_reply(response)

        # 12. Save assistant reply
        save_message(db, conversation.id, "assistant", reply_text)

        # 13. Send reply to customer
        await send_reply(
            channel=channel,
            sender_id=external_user_id,
            text=reply_text,
            phone_number_id=phone_number_id or business.meta_phone_number_id,
            page_access_token=business.meta_page_access_token,
        )
        logger.info(
            f"Handled message on {channel} for business={business.name}, "
            f"user={external_user_id[:8]}..."
        )

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
    finally:
        if own_db:
            db.close()
