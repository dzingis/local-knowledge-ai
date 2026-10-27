from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.indexer.index_manager import QueueStatus
from backend.indexer.sql_queue_repository import QueueRepositoryRecord, SqlQueueRepository
from backend.repositories.worker_heartbeat_repository import (
    WorkerHeartbeatRecord,
    WorkerHeartbeatRepository,
)
from backend.workers.processing_worker import ProcessingWorker, WorkerResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BackgroundWorkerState:
    running: bool = False
    locked: bool = False
    iterations: int = 0
    processed: int = 0
    last_result: WorkerResult | None = None
    last_heartbeat_at: datetime | None = None
    recovered_items: int = 0
    idle_iterations: int = 0
    current_interval_seconds: float = 0.0


class BackgroundWorkerService:
    """Continuously runs a ProcessingWorker in the background.

    A process-local asyncio lock ensures that only one background worker loop
    can run at a time within this application instance.
    """

    _singleton_lock: asyncio.Lock = asyncio.Lock()

    def __init__(
        self,
        worker: ProcessingWorker,
        queue_repository: SqlQueueRepository | None = None,
        heartbeat_repository: WorkerHeartbeatRepository | None = None,
        interval_seconds: float = 2.0,
        heartbeat_worker_id: str = "background-worker",
        idle_interval_seconds: float = 10.0,
        active_interval_seconds: float = 0.5,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self._worker = worker
        self._queue_repository = queue_repository
        self._heartbeat_repository = heartbeat_repository
        self._base_interval_seconds = max(0.1, interval_seconds)
        self._idle_interval_seconds = max(self._base_interval_seconds, idle_interval_seconds)
        self._active_interval_seconds = max(0.1, min(active_interval_seconds, self._base_interval_seconds))
        self._max_backoff_seconds = max(self._idle_interval_seconds, max_backoff_seconds)
        self._heartbeat_worker_id = heartbeat_worker_id
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._state = BackgroundWorkerState(current_interval_seconds=self._base_interval_seconds)

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
        self._state.current_interval_seconds = self._base_interval_seconds
        self._recover_processing_items()
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
        self._persist_heartbeat("stopped", None)
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
                            self._state.idle_iterations = 0
                            self._state.current_interval_seconds = self._active_interval_seconds
                            logger.info("Processed %s with outcome %s", result.file_path, result.outcome.value)
                            self._persist_heartbeat(status="running", current_file=result.file_path)
                        else:
                            self._state.idle_iterations += 1
                            self._state.current_interval_seconds = self._next_backoff_interval(
                                self._state.idle_iterations,
                                self._state.current_interval_seconds,
                            )
                            self._persist_heartbeat(status="idle", current_file=None)
                    except Exception:
                        logger.exception("Background worker iteration failed")
                        self._state.idle_iterations += 1
                        self._state.current_interval_seconds = self._next_backoff_interval(
                            self._state.idle_iterations,
                            self._state.current_interval_seconds,
                        )
                        self._persist_heartbeat(status="error", current_file=None)

                    await asyncio.sleep(self._state.current_interval_seconds)
            finally:
                self._state.running = False
                self._state.locked = False
                self._persist_heartbeat("stopped", None)
                logger.info("Background worker loop exited")

    def _next_backoff_interval(self, idle_iterations: int, current_interval: float) -> float:
        if idle_iterations <= 0:
            return self._active_interval_seconds

        if idle_iterations == 1:
            return self._idle_interval_seconds

        return min(self._max_backoff_seconds, max(self._active_interval_seconds, current_interval * 2.0))

    def _recover_processing_items(self) -> None:
        if self._queue_repository is None:
            return

        recovered = 0
        try:
            processing_records = self._queue_repository._load_by_status(QueueStatus.PROCESSING)  # type: ignore[attr-defined]
            for record in processing_records:
                if self._queue_repository.retry(record.full_path):
                    recovered += 1
            if recovered:
                logger.warning("Recovered %s processing queue item(s) after startup", recovered)
        except Exception:
            logger.exception("Failed to recover processing queue items")
        finally:
            self._state.recovered_items = recovered

    def _persist_heartbeat(self, status: str, current_file: str | None) -> None:
        self._state.last_heartbeat_at = datetime.now(timezone.utc)
        if self._heartbeat_repository is None:
            return

        record = WorkerHeartbeatRecord(
            worker_id=self._heartbeat_worker_id,
            status=status,
            running=self._state.running,
            locked=self._state.locked,
            iterations=self._state.iterations,
            processed=self._state.processed,
            current_file=current_file,
            last_result_file=self._state.last_result.file_path if self._state.last_result else None,
            last_result_outcome=self._state.last_result.outcome.value if self._state.last_result else None,
            last_heartbeat_at=self._state.last_heartbeat_at,
        )
        try:
            self._heartbeat_repository.upsert_heartbeat(record)
        except Exception:
            logger.exception("Failed to persist worker heartbeat")
