from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from backend.indexer.index_manager import ChangeType
from backend.indexer.sql_queue_repository import QueueRepositoryRecord, SqlQueueRepository


class WorkerStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class WorkerOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class WorkerProgress:
    worker_id: str
    status: WorkerStatus
    started_at: datetime
    finished_at: datetime | None = None
    current_file: str | None = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    last_error: str | None = None
    average_duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class WorkerResult:
    file_path: str
    outcome: WorkerOutcome
    error_message: str | None = None
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class QueueProcessor(Protocol):
    def __call__(self, record: QueueRepositoryRecord) -> WorkerResult:
        ...


class NoOpQueueProcessor:
    """Default processor used until parser/chunking/embedding services are wired in."""

    def __call__(self, record: QueueRepositoryRecord) -> WorkerResult:
        if record.change_type == ChangeType.DELETED:
            return WorkerResult(file_path=record.full_path, outcome=WorkerOutcome.COMPLETED)
        return WorkerResult(file_path=record.full_path, outcome=WorkerOutcome.COMPLETED)


class ProcessingWorker:
    """Background worker that consumes queue rows and processes files."""

    def __init__(
        self,
        repository: SqlQueueRepository,
        processor: QueueProcessor | None = None,
        worker_id: str = "worker-1",
        max_retries: int = 3,
        logger: object | None = None,
    ) -> None:
        self._repository = repository
        self._processor = processor or NoOpQueueProcessor()
        self._worker_id = worker_id
        self._max_retries = max_retries
        self._logger = logger
        self._running = False
        self._progress = WorkerProgress(
            worker_id=worker_id,
            status=WorkerStatus.IDLE,
            started_at=datetime.now(timezone.utc),
        )

    @property
    def progress(self) -> WorkerProgress:
        return self._progress

    def start(self) -> None:
        self._running = True
        self._progress = replace(
            self._progress,
            status=WorkerStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            finished_at=None,
        )
        self._log("Worker started", worker_id=self._worker_id)

    def stop(self) -> None:
        self._running = False
        self._progress = replace(
            self._progress,
            status=WorkerStatus.STOPPED,
            finished_at=datetime.now(timezone.utc),
        )
        self._log("Worker stopped", worker_id=self._worker_id)

    def run_once(self) -> WorkerResult | None:
        if not self._running:
            self.start()

        pending = self._repository.get_pending()
        if not pending:
            self._log("No pending queue items")
            return None

        record = pending[0]
        self._progress = self._with_updates(current_file=record.full_path)
        self._log("Picked queue item", file_path=record.full_path)

        if not self._repository.mark_processing(record.full_path):
            self._log("Failed to mark item as processing", file_path=record.full_path)
            return WorkerResult(
                file_path=record.full_path,
                outcome=WorkerOutcome.FAILED,
                error_message="Failed to mark item as processing",
            )

        started_at = datetime.now(timezone.utc)
        try:
            result = self._processor(record)
            duration_ms = self._elapsed_ms(started_at)

            if result.outcome == WorkerOutcome.COMPLETED:
                self._repository.mark_completed(record.full_path)
                self._progress = self._with_updates(
                    processed=self._progress.processed + 1,
                    succeeded=self._progress.succeeded + 1,
                    current_file=None,
                    average_duration_ms=self._next_average(duration_ms),
                )
                self._log("Queue item completed", file_path=record.full_path, duration_ms=duration_ms)
                return result

            if result.outcome == WorkerOutcome.RETRY:
                self._repository.mark_failed(record.full_path, result.error_message)
                if record.retry_count < self._max_retries:
                    self._repository.retry(record.full_path)
                    self._progress = self._with_updates(
                        processed=self._progress.processed + 1,
                        retried=self._progress.retried + 1,
                        current_file=None,
                        last_error=result.error_message,
                        average_duration_ms=self._next_average(duration_ms),
                    )
                    self._log("Queue item requeued", file_path=record.full_path, duration_ms=duration_ms)
                else:
                    self._progress = self._with_updates(
                        processed=self._progress.processed + 1,
                        failed=self._progress.failed + 1,
                        current_file=None,
                        last_error=result.error_message or "Retry limit exceeded",
                        average_duration_ms=self._next_average(duration_ms),
                    )
                    self._log("Retry limit exceeded", file_path=record.full_path, duration_ms=duration_ms)
                    return WorkerResult(
                        file_path=record.full_path,
                        outcome=WorkerOutcome.FAILED,
                        error_message=result.error_message or "Retry limit exceeded",
                    )
                return result

            self._repository.mark_failed(record.full_path, result.error_message)
            self._progress = self._with_updates(
                processed=self._progress.processed + 1,
                failed=self._progress.failed + 1,
                current_file=None,
                last_error=result.error_message,
                average_duration_ms=self._next_average(duration_ms),
            )
            self._log("Queue item failed", file_path=record.full_path, error=result.error_message)
            return result

        except Exception as exc:  # pragma: no cover - defensive worker guard
            self._repository.mark_failed(record.full_path, str(exc))
            self._progress = self._with_updates(
                processed=self._progress.processed + 1,
                failed=self._progress.failed + 1,
                current_file=None,
                last_error=str(exc),
                average_duration_ms=self._next_average(self._elapsed_ms(started_at)),
            )
            self._log("Worker exception", file_path=record.full_path, error=str(exc))
            return WorkerResult(file_path=record.full_path, outcome=WorkerOutcome.FAILED, error_message=str(exc))

    def run_until_empty(self) -> list[WorkerResult]:
        results: list[WorkerResult] = []
        while True:
            result = self.run_once()
            if result is None:
                break
            results.append(result)
        self.stop()
        return results

    def process_path(self, path: str | Path) -> WorkerResult:
        target_path = str(path)
        record = next((item for item in self._repository.get_pending() if item.full_path == target_path), None)
        if record is None:
            return WorkerResult(file_path=target_path, outcome=WorkerOutcome.FAILED, error_message="Path not queued")

        if not self._repository.mark_processing(record.full_path):
            return WorkerResult(
                file_path=record.full_path,
                outcome=WorkerOutcome.FAILED,
                error_message="Failed to mark item as processing",
            )

        self._log("Processing explicit path", file_path=record.full_path)
        return self._processor(record)

    def _with_updates(self, **updates: object) -> WorkerProgress:
        return replace(self._progress, **updates)

    def _next_average(self, duration_ms: float) -> float:
        if self._progress.processed <= 0:
            return duration_ms
        total_previous = self._progress.average_duration_ms * self._progress.processed
        return (total_previous + duration_ms) / (self._progress.processed + 1)

    def _elapsed_ms(self, started_at: datetime) -> float:
        return (datetime.now(timezone.utc) - started_at).total_seconds() * 1000.0

    def _log(self, message: str, **fields: object) -> None:
        if self._logger is None:
            return
        log_method = getattr(self._logger, "info", None)
        if callable(log_method):
            log_method("%s | %s", message, fields)
