from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db

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
        # Try to run a basic command on the database
        db.execute(text("SELECT 1"))
        db_status = "connected 🟢"
    except Exception as e:
        db_status = f"disconnected 🔴 - {str(e)}"
        
    return {
        "api": "online 🟢",
        "database": db_status
    }