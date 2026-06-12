import os
import random
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

CAFETERIA_CAPACITY = int(os.getenv("CAFETERIA_CAPACITY", "500"))
HOSPITAL_CAPACITY   = int(os.getenv("HOSPITAL_CAPACITY", "300"))
PORT                = int(os.getenv("PORT", "8010"))

app = FastAPI(title="SimpleThings Service", version="1.0")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/cafeteria/count")
async def cafeteria_count():
    return {
        "value": random.randint(0, CAFETERIA_CAPACITY),
        "capacity": CAFETERIA_CAPACITY,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/hospital/count")
async def hospital_count():
    return {
        "value": random.randint(0, HOSPITAL_CAPACITY),
        "capacity": HOSPITAL_CAPACITY,
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
