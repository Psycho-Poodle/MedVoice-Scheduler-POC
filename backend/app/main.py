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

from app.routes import router


def _parse_cors_origins(value: str | None) -> list[str]:
    if not value:
        return ["http://localhost:5173"]
    origin_list = [origin.strip() for origin in value.split(",") if origin.strip()]
    if "*" in origin_list:
        return ["*"]
    return origin_list


app = FastAPI(title="MedVoice Scheduler API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(os.getenv("BACKEND_CORS_ORIGINS")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}