from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"

    # LLM
    OPENROUTER_API_KEY: str

    # Meta / WhatsApp / IG / Messenger
    META_VERIFY_TOKEN: str = "autom8rs_verify_2026"
    META_ACCESS_TOKEN: str = ""
    META_APP_SECRET: str = ""  # For webhook signature verification

    # Whisper (voice notes)
    WHISPER_API_KEY: Optional[str] = None  # OpenAI API key for Whisper

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    class Config:
        env_file = ".env"


settings = Settings()