from fastapi import FastAPI

from app.features.health.router import router as health_router
from app.features.outlets.router import router as outlets_router

app = FastAPI(title="RMS API")

app.include_router(health_router)
app.include_router(outlets_router)
