from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    REDIS_URL: str
    
    # API Keys (We will add these in Coolify later)
    OPENROUTER_API_KEY: str = "placeholder_for_now"
    
    # Meta (WhatsApp/IG)
    META_VERIFY_TOKEN: str = "placeholder_for_now"
    META_ACCESS_TOKEN: str = "placeholder_for_now"

    class Config:
        env_file = ".env"

settings = Settings()