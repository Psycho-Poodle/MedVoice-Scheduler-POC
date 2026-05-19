# """FastAPI application entrypoint."""

# from fastapi import FastAPI

# from app.routes import router

# app = FastAPI(title="MedVoice Scheduler API", version="0.1.0")
# app.include_router(router, prefix="/api/v1")


# @app.get("/health")
# def health() -> dict:
#     """Container health endpoint."""
#     return {"status": "ok"}

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import router

app = FastAPI(title="MedVoice Scheduler API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}