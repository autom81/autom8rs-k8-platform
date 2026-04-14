"""
Meta Cloud API Service
Handles sending messages to WhatsApp, Instagram, and Messenger.
Also handles parsing incoming webhook payloads from all three channels.
"""
import hashlib
import hmac
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

META_GRAPH_URL = "https://graph.facebook.com/v21.0"


# ============================================================
# WEBHOOK SIGNATURE VERIFICATION
# ============================================================

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify that the webhook payload came from Meta, not a spoofer."""
    if not settings.META_APP_SECRET:
        logger.warning("META_APP_SECRET not set — skipping signature verification")
        return True

    expected = hmac.new(
        settings.META_APP_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


# ============================================================
# PARSE INCOMING WEBHOOK PAYLOADS
# ============================================================

def parse_whatsapp_webhook(body: dict) -> list[dict]:
    """
    Parse a WhatsApp Cloud API webhook payload.
    Returns a list of message dicts with normalized fields.
    """
    messages_out = []

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id", "")

            for msg in value.get("messages", []):
                parsed = {
                    "channel": "whatsapp",
                    "phone_number_id": phone_number_id,
                    "sender_id": msg.get("from", ""),
                    "message_id": msg.get("id", ""),
                    "timestamp": msg.get("timestamp", ""),
                    "message_text": "",
                    "media_url": None,
                    "media_type": None,
                    "referral": None,
                }

                msg_type = msg.get("type", "")

                if msg_type == "text":
                    parsed["message_text"] = msg.get("text", {}).get("body", "")

                elif msg_type == "audio":
                    audio = msg.get("audio", {})
                    parsed["media_type"] = "audio"
                    parsed["media_url"] = audio.get("id", "")
                    parsed["message_text"] = "[Voice Note]"

                elif msg_type == "image":
                    image = msg.get("image", {})
                    parsed["media_type"] = "image"
                    parsed["media_url"] = image.get("id", "")
                    parsed["message_text"] = image.get("caption", "[Image]")

                elif msg_type == "document":
                    doc = msg.get("document", {})
                    parsed["media_type"] = "document"
                    parsed["media_url"] = doc.get("id", "")
                    parsed["message_text"] = doc.get("caption", "[Document]")

                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        parsed["message_text"] = interactive.get("button_reply", {}).get("title", "")
                    elif interactive.get("type") == "list_reply":
                        parsed["message_text"] = interactive.get("list_reply", {}).get("title", "")

                # Check for CTWA ad referral
                if "referral" in msg.get("context", {}):
                    parsed["referral"] = msg["context"]["referral"]
                elif "referral" in msg:
                    parsed["referral"] = msg["referral"]

                if parsed["message_text"] or parsed["media_url"]:
                    messages_out.append(parsed)

    return messages_out


def parse_messenger_webhook(body: dict) -> list[dict]:
    """
    Parse a Messenger / Instagram DM webhook payload.
    Returns a list of message dicts with normalized fields.
    """
    messages_out = []

    for entry in body.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            sender_id = messaging_event.get("sender", {}).get("id", "")
            recipient_id = messaging_event.get("recipient", {}).get("id", "")

            message = messaging_event.get("message", {})
            if not message:
                continue

            # Skip echo messages (messages sent BY the page)
            if message.get("is_echo"):
                continue

            parsed = {
                "channel": "facebook",
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "message_id": message.get("mid", ""),
                "message_text": message.get("text", ""),
                "media_url": None,
                "media_type": None,
                "referral": None,
            }

            # Check for attachments
            attachments = message.get("attachments", [])
            if attachments:
                att = attachments[0]
                att_type = att.get("type", "")
                payload_url = att.get("payload", {}).get("url", "")
                if att_type == "audio":
                    parsed["media_type"] = "audio"
                    parsed["media_url"] = payload_url
                    parsed["message_text"] = parsed["message_text"] or "[Voice Note]"
                elif att_type == "image":
                    parsed["media_type"] = "image"
                    parsed["media_url"] = payload_url
                    parsed["message_text"] = parsed["message_text"] or "[Image]"

            # Check for referral (ads)
            if "referral" in messaging_event:
                parsed["referral"] = messaging_event["referral"]

            if parsed["message_text"] or parsed["media_url"]:
                messages_out.append(parsed)

    return messages_out


# ============================================================
# DOWNLOAD MEDIA (WhatsApp uses media IDs, not direct URLs)
# ============================================================

async def download_whatsapp_media(media_id: str) -> Optional[bytes]:
    """Download media from WhatsApp (two-step: get URL, then download)."""
    try:
        async with httpx.AsyncClient() as http:
            # Step 1: Get the media URL
            url_resp = await http.get(
                f"{META_GRAPH_URL}/{media_id}",
                headers={"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"},
            )
            url_resp.raise_for_status()
            media_url = url_resp.json().get("url")
            if not media_url:
                return None

            # Step 2: Download the actual file
            media_resp = await http.get(
                media_url,
                headers={"Authorization": f"Bearer {settings.META_ACCESS_TOKEN}"},
            )
            media_resp.raise_for_status()
            return media_resp.content
    except Exception as e:
        logger.error(f"Failed to download media {media_id}: {e}")
        return None


# ============================================================
# SEND MESSAGES
# ============================================================

async def send_whatsapp_message(phone_number_id: str, to: str, text: str) -> dict:
    """Send a text message via WhatsApp Cloud API."""
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{META_GRAPH_URL}/{phone_number_id}/messages",
                headers={
                    "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text},
                },
            )

            # Log the full response for debugging
            if resp.status_code != 200:
                logger.error(
                    f"WhatsApp API error sending to {to}: "
                    f"status={resp.status_code}, "
                    f"response={resp.text}"
                )
            resp.raise_for_status()

            data = resp.json()
            logger.info(f"WhatsApp message sent to {to}")
            return data

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Failed to send WhatsApp message to {to}: "
            f"status={e.response.status_code}, "
            f"body={e.response.text}"
        )
        return {"error": str(e), "details": e.response.text}
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message to {to}: {e}")
        return {"error": str(e)}


async def send_messenger_message(recipient_id: str, text: str) -> dict:
    """Send a text message via Messenger or Instagram DM."""
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{META_GRAPH_URL}/me/messages",
                headers={
                    "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "recipient": {"id": recipient_id},
                    "message": {"text": text},
                },
            )

            if resp.status_code != 200:
                logger.error(
                    f"Messenger API error sending to {recipient_id}: "
                    f"status={resp.status_code}, "
                    f"response={resp.text}"
                )
            resp.raise_for_status()

            data = resp.json()
            logger.info(f"Messenger message sent to {recipient_id}")
            return data

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Failed to send Messenger message to {recipient_id}: "
            f"status={e.response.status_code}, "
            f"body={e.response.text}"
        )
        return {"error": str(e), "details": e.response.text}
    except Exception as e:
        logger.error(f"Failed to send Messenger message to {recipient_id}: {e}")
        return {"error": str(e)}


# ============================================================
# UNIFIED SEND (Routes to correct channel)
# ============================================================

async def send_reply(channel: str, sender_id: str, text: str, phone_number_id: str = None) -> dict:
    """Send a reply on the same channel the customer used."""
    logger.info(f"send_reply called: channel={channel}, to={sender_id}, phone_number_id={phone_number_id}")

    if channel == "whatsapp":
        if not phone_number_id:
            logger.error("Cannot send WhatsApp reply without phone_number_id")
            return {"error": "missing phone_number_id"}
        return await send_whatsapp_message(phone_number_id, sender_id, text)
    elif channel in ("facebook", "instagram"):
        return await send_messenger_message(sender_id, text)
    else:
        logger.warning(f"send_reply called for unsupported channel: {channel}")
        return {"error": f"unsupported channel: {channel}"}
