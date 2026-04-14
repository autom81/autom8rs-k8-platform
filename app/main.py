import logging

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import engine, Base, get_db
import app.models  # Forces Python to read schema files
from app.routes.webhooks import router as webhooks_router
from app.routes.admin import router as admin_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Build tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="K8 Agent Platform", version="0.1.0")

# Register routes
app.include_router(webhooks_router)
app.include_router(admin_router)


@app.get("/")
async def root():
    return {
        "status": "online",
        "platform": "K8 Agent Platform",
        "version": "0.1.0",
        "message": "Hello from api.autom8rs.com",
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        result = db.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        )
        table_count = result.scalar()
        db_status = f"connected \U0001f7e2 (Tables built: {table_count})"
    except Exception as e:
        db_status = f"disconnected \U0001f534 - {str(e)}"

    return {
        "api": "online \U0001f7e2",
        "database": db_status,
    }