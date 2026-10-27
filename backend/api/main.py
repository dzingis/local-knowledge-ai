from __future__ import annotations

from fastapi import FastAPI

from backend.api.routes import router as api_router
from backend.api.dependencies import get_background_worker_service

app = FastAPI(
    title="Local Knowledge AI API",
    version="0.1.0",
    description="REST API for scanning, ingestion, queue inspection, and document retrieval.",
)

app.include_router(api_router)


@app.on_event("startup")
def startup() -> None:
    get_background_worker_service().start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await get_background_worker_service().stop()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
