from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.features.auth.router import router as auth_router
from app.features.health.router import router as health_router
from app.features.outlets.router import router as outlets_router
from app.features.users.router import router as users_router
from app.features.sync.router import router as sync_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="RMS API")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(outlets_router)
app.include_router(users_router)
app.include_router(sync_router)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # hanya untuk pengembangan
    allow_methods=["*"],
    allow_headers=["*"],
)
