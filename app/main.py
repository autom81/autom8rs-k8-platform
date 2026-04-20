"""
FastAPI Main Application
UPDATED for Phase 6: Uses Alembic for migrations instead of Base.metadata.create_all()
 
WHY THE CHANGE:
- Base.metadata.create_all() only CREATES new tables, can't modify existing ones
- Alembic properly tracks schema changes with version history
- Production-safe migrations with rollback capability
 
STARTUP FLOW:
1. App starts
2. Alembic runs pending migrations (upgrade to head)
3. App serves requests
"""
import logging
import subprocess
import os
 
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
 
from app.database import engine, get_db
import app.models  # Forces Python to read all schema files
 
from app.routes.webhooks import router as webhooks_router
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.dashboard import router as dashboard_router
from app.routes.analytics import router as analytics_router
from app.routes.settings import router as settings_router
 
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
 
 
# ============================================================
# ALEMBIC MIGRATION RUNNER
# ============================================================
 
def run_migrations():
    """
    Run pending Alembic migrations on startup.
    This ensures the database schema is always up-to-date.
    """
    try:
        logger.info("Running database migrations...")
        
        # Check if alembic is configured
        alembic_dir = os.path.join(os.getcwd(), "alembic")
        if not os.path.exists(alembic_dir):
            logger.warning(
                "Alembic directory not found. "
                "Database migrations will not run. "
                "Run 'alembic init alembic' to set up migrations."
            )
            return
        
        # Run: alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=False,
        )
        
        if result.returncode == 0:
            logger.info("✅ Database migrations applied successfully")
            if result.stdout:
                logger.info(f"Alembic output: {result.stdout.strip()}")
        else:
            logger.error(f"❌ Migration failed: {result.stderr}")
            # Don't crash the app - log and continue
            # In production, you might want to raise here to prevent startup
            
    except FileNotFoundError:
        logger.error(
            "Alembic not installed. Run: pip install alembic"
        )
    except Exception as e:
        logger.error(f"Error running migrations: {e}", exc_info=True)
 
 
# ============================================================
# FASTAPI APP SETUP
# ============================================================
 
# Run migrations BEFORE the app starts accepting requests
run_migrations()
 
app = FastAPI(title="K8 Agent Platform", version="0.2.0")  # Bumped for Phase 6

# ============================================================
# CORS
# allow_credentials=True is required for the httpOnly JWT cookie
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dashboard.autom8rs.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Cookie", "X-Requested-With"],
    expose_headers=["Set-Cookie"],
    max_age=3600,
)

# Register routes
app.include_router(webhooks_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(analytics_router)
app.include_router(settings_router)
 
 
# ============================================================
# HEALTH CHECK ENDPOINTS
# ============================================================
 
@app.get("/")
async def root():
    return {
        "status": "online",
        "platform": "K8 Agent Platform",
        "version": "0.2.0",
        "message": "Hello from api.autom8rs.com",
    }
 
 
@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Comprehensive health check - database + cache."""
    from app.services.cache import cache_health_check
    
    # Check database
    try:
        db.execute(text("SELECT 1"))
        result = db.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        )
        table_count = result.scalar()
        db_status = {
            "status": "healthy",
            "tables": table_count,
        }
    except Exception as e:
        db_status = {
            "status": "unhealthy",
            "error": str(e),
        }
    
    # Check cache
    cache_status = cache_health_check()
    
    # Check migration state
    try:
        result = db.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        )
        current_version = result.scalar()
        migration_status = {
            "current_revision": current_version,
            "status": "up_to_date" if current_version else "no_migrations_applied"
        }
    except Exception:
        migration_status = {
            "status": "alembic_not_initialized",
        }
    
    return {
        "api": "online",
        "database": db_status,
        "cache": cache_status,
        "migrations": migration_status,
    }