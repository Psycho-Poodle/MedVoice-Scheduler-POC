# """FastAPI application entrypoint."""

# from fastapi import FastAPI

# from app.routes import router

# app = FastAPI(title="MedVoice Scheduler API", version="0.1.0")
# app.include_router(router, prefix="/api/v1")


# @app.get("/health")
# def health() -> dict:
#     """Container health endpoint."""
#     return {"status": "ok"}

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap import bootstrap_database
from app.routes import router


def _parse_cors_origins(value: str | None) -> list[str]:
    if not value:
        return [
            "http://localhost:5173",
            "https://medvoice-scheduler-poc-1.onrender.com",
        ]
    origin_list = [origin.strip() for origin in value.split(",") if origin.strip()]
    if "*" in origin_list:
        return ["*"]
    return origin_list


cors_origins = _parse_cors_origins(os.getenv("BACKEND_CORS_ORIGINS"))

app = FastAPI(title="MedVoice Scheduler API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
async def startup() -> None:
    bootstrap_database()
