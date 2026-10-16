from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.features.auth.router import router as auth_router
from app.features.health.router import router as health_router
from app.features.outlets.router import router as outlets_router
from app.features.users.router import router as users_router
from app.features.sync.router import router as sync_router
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import SessionLocal
from app.features.attendance import service as attendance_service
from app.features.attendance.router import router as attendance_router

log = logging.getLogger("rms")


def _purge_job() -> None:
    with SessionLocal() as db:
        n = attendance_service.purge_old_photos(db, settings.photo_retention_days)
    if n:
        log.info("Retensi foto: %s catatan dibersihkan", n)


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(60)  # jalan pertama 1 menit setelah start, lalu tiap 6 jam
        try:
            await asyncio.to_thread(_purge_job)
        except Exception:
            log.exception("Pembersihan foto gagal")
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_retention_loop())
    yield
    task.cancel()


app = FastAPI(title="RMS API", lifespan=lifespan)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(outlets_router)
app.include_router(users_router)
app.include_router(sync_router)
app.include_router(attendance_router)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # hanya untuk pengembangan
    allow_methods=["*"],
    allow_headers=["*"],
)
