from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from backend.api import dependencies
from backend.api.health import router as health_router
from backend.api.routes import router as api_router
from backend.config.logging import configure_logging
from backend.watchers.watch_service import WatchService
from backend.workers.processing_worker import ProcessingWorker

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup / shutdown.
    """

    print("======================================")
    print("Starting Local Knowledge AI...")
    print("======================================")

    background_worker = dependencies.get_background_worker_service()
    watch_service = dependencies.get_watch_service()

    background_worker.start()
    watch_service.start()

    try:
        yield

    finally:
        print("Stopping Local Knowledge AI...")

        await watch_service.stop()
        background_worker.stop()

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


@app.get("/watcher", tags=["health"])
def get_watcher_status(
    watch_service: WatchService = Depends(dependencies.get_watch_service),
    worker: ProcessingWorker = Depends(dependencies.get_processing_worker),
) -> dict[str, object]:
    return watch_service.health_status(worker.progress.processed)


@app.get("/", tags=["system"])
async def root():
    return {
        "application": "Local Knowledge AI",
        "version": "0.1.0",
        "status": "running",
    }
