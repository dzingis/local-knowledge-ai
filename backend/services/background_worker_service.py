from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from backend.workers.processing_worker import ProcessingWorker, WorkerResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BackgroundWorkerState:
    running: bool = False
    locked: bool = False
    iterations: int = 0
    processed: int = 0
    last_result: WorkerResult | None = None


class BackgroundWorkerService:
    """Continuously runs a ProcessingWorker in the background.

    A process-local asyncio lock ensures that only one background worker loop
    can run at a time within this application instance.
    """

    _singleton_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, worker: ProcessingWorker, interval_seconds: float = 2.0) -> None:
        self._worker = worker
        self._interval_seconds = max(0.1, interval_seconds)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._state = BackgroundWorkerState()

    @property
    def state(self) -> BackgroundWorkerState:
        return self._state

    @property
    def running(self) -> bool:
        return self._state.running

    @classmethod
    def is_locked(cls) -> bool:
        return cls._singleton_lock.locked()

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return True
        if self._singleton_lock.locked():
            logger.info("Background worker start skipped: singleton lock is already held")
            self._state.running = False
            self._state.locked = True
            return False
        self._stop_event.clear()
        self._state.running = True
        self._state.locked = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Background worker service started")
        return True

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None
        self._state.running = False
        self._state.locked = False
        logger.info("Background worker service stopped")

    async def _run_loop(self) -> None:
        logger.info("Background worker loop started")
        async with self._singleton_lock:
            try:
                while not self._stop_event.is_set():
                    self._state.iterations += 1
                    try:
                        result = self._worker.run_once()
                        self._state.last_result = result
                        if result is not None:
                            self._state.processed += 1
                            logger.info("Processed %s with outcome %s", result.file_path, result.outcome.value)
                    except Exception:
                        logger.exception("Background worker iteration failed")
                    await asyncio.sleep(self._interval_seconds)
            finally:
                self._state.running = False
                self._state.locked = False
                logger.info("Background worker loop exited")
