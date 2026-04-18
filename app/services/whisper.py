"""
Whisper Voice Transcription Service - Phase 6
==============================================
Transcribes WhatsApp voice notes using OpenAI Whisper API.

Flow:
1. WhatsApp sends audio message with media_id
2. message_handler calls download_whatsapp_media() to get audio bytes
3. Those bytes get passed here for transcription
4. Returns text string that gets processed like a normal message
"""
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def transcribe_voice_note(audio_bytes: bytes, filename: str = "audio.ogg") -> Optional[str]:
    """
    Transcribe audio bytes using OpenAI Whisper API.

    Args:
        audio_bytes: Raw audio file bytes (downloaded from WhatsApp)
        filename: Filename hint for Whisper (helps with format detection)

    Returns:
        Transcribed text string, or None if transcription failed
    """
    if not settings.WHISPER_API_KEY:
        logger.warning("WHISPER_API_KEY not set - voice transcription disabled")
        return None

    if not audio_bytes:
        logger.warning("No audio bytes provided for transcription")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={
                    "Authorization": f"Bearer {settings.WHISPER_API_KEY}",
                },
                files={
                    "file": (filename, audio_bytes, "audio/ogg"),
                },
                data={
                    "model": "whisper-1",
                    # No language hint - let Whisper auto-detect
                    # Trinidad customers may mix English and Creole
                },
            )

            if response.status_code != 200:
                logger.error(
                    f"Whisper API error: status={response.status_code}, "
                    f"body={response.text}"
                )
                return None

            result = response.json()
            transcript = result.get("text", "").strip()

            if transcript:
                logger.info(f"Voice note transcribed: '{transcript[:50]}...'")
            else:
                logger.warning("Whisper returned empty transcript")

            return transcript or None

    except httpx.TimeoutException:
        logger.error("Whisper API timeout - audio may be too long")
        return None
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}", exc_info=True)
        return None