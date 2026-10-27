from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.health import router as health_router
from backend.api.routes import router as api_router
from backend.config.logging import configure_logging
from backend.api.dependencies import get_background_worker_service

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown.
    Services (SQL Server, Qdrant, Ollama) will be initialized here
    in later milestones.
    """

    print("Local Knowledge AI starting...")

    background_worker = get_background_worker_service()
    background_worker.start()

    try:
        yield
    finally:
        await background_worker.stop()
        print("Local Knowledge AI stopped.")


app = FastAPI(
    title="Local Knowledge AI",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "application": "Local Knowledge AI",
        "version": "0.1.0",
        "status": "running",
    }
