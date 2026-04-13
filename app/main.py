from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {
        "status": "online",
        "platform": "K8 Agent Platform",
        "message": "Hello from api.autom8rs.com"
    }