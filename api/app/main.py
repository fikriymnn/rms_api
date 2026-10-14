from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.features.auth.router import router as auth_router
from app.features.health.router import router as health_router
from app.features.outlets.router import router as outlets_router
from app.features.users.router import router as users_router

app = FastAPI(title="RMS API")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(outlets_router)
app.include_router(users_router)
