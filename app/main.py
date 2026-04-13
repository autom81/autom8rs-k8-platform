from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import engine, Base, get_db
import app.models  # This forces Python to read your new schema files

# THIS IS THE MAGIC LINE: It tells SQLAlchemy to build the tables in Postgres!
Base.metadata.create_all(bind=engine)

app = FastAPI()

@app.get("/")
async def root():
    return {
        "status": "online",
        "platform": "K8 Agent Platform",
        "message": "Hello from api.autom8rs.com"
    }

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        # Check if DB is awake
        db.execute(text("SELECT 1"))
        
        # Count the tables to prove they were created!
        result = db.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"))
        table_count = result.scalar()
        
        db_status = f"connected 🟢 (Tables built: {table_count})"
    except Exception as e:
        db_status = f"disconnected 🔴 - {str(e)}"
        
    return {
        "api": "online 🟢",
        "database": db_status
    }