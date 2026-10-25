from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.health import router as health_router
from backend.config.logging import configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown.
    Services (SQL Server, Qdrant, Ollama) will be initialized here
    in later milestones.
    """

    print("Local Knowledge AI starting...")

    yield

    print("Local Knowledge AI stopped.")


app = FastAPI(
    title="Local Knowledge AI",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)


@app.get("/")
async def root():
    return {
        "application": "Local Knowledge AI",
        "version": "0.1.0",
        "status": "running",
    }
