from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.dependencies import get_background_worker_service
from backend.api.health import router as health_router
from backend.api.routes import router as api_router
from backend.config.logging import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup / shutdown.

    Initializes all background services required by
    Local Knowledge AI.
    """

    print("======================================")
    print("Starting Local Knowledge AI...")
    print("======================================")

    background_worker = get_background_worker_service()

    background_worker.start()

    try:
        yield

    finally:
        print("Stopping Local Knowledge AI...")

        await background_worker.stop()

        print("Local Knowledge AI stopped.")


app = FastAPI(
    title="Local Knowledge AI",
    version="0.1.0",
    description="REST API for Local Knowledge AI",
    lifespan=lifespan,
)

#
# Routers
#

app.include_router(health_router)
app.include_router(api_router)


#
# Root endpoint
#

@app.get("/", tags=["system"])
async def root():
    return {
        "application": "Local Knowledge AI",
        "version": "0.1.0",
        "status": "running",
    }