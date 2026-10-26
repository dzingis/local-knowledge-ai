from __future__ import annotations

from dataclasses import dataclass, field
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


class ProcessingWorker:
    """Background worker that consumes queue rows and processes files."""

    def __init__(
        self,
        repository: SqlQueueRepository,
        processor: QueueProcessor | None = None,
        worker_id: str = "worker-1",
        max_retries: int = 3,
    ) -> None:
        self._repository = repository
        self._processor = processor or self._default_processor
        self._worker_id = worker_id
        self._max_retries = max_retries
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
        self._progress = WorkerProgress(
            worker_id=self._worker_id,
            status=WorkerStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )

    def stop(self) -> None:
        self._running = False
        self._progress = WorkerProgress(
            worker_id=self._worker_id,
            status=WorkerStatus.STOPPED,
            started_at=self._progress.started_at,
            finished_at=datetime.now(timezone.utc),
            processed=self._progress.processed,
            succeeded=self._progress.succeeded,
            failed=self._progress.failed,
            retried=self._progress.retried,
            last_error=self._progress.last_error,
            average_duration_ms=self._progress.average_duration_ms,
        )

    def run_once(self) -> WorkerResult | None:
        if not self._running:
            self.start()

        pending = self._repository.get_pending()
        if not pending:
            return None

        record = pending[0]
        self._progress = self._replace_progress(current_file=record.full_path)
        self._repository.mark_processing(record.full_path)

        try:
            result = self._processor(record)
            if result.outcome == WorkerOutcome.COMPLETED:
                self._repository.mark_completed(record.full_path)
                self._progress = self._replace_progress(processed=1, succeeded=1, current_file=None)
            elif result.outcome == WorkerOutcome.RETRY:
                self._repository.mark_failed(record.full_path, result.error_message)
                self._repository.retry(record.full_path)
                self._progress = self._replace_progress(processed=1, retried=1, last_error=result.error_message, current_file=None)
            else:
                self._repository.mark_failed(record.full_path, result.error_message)
                self._progress = self._replace_progress(processed=1, failed=1, last_error=result.error_message, current_file=None)
            return result
        except Exception as exc:  # pragma: no cover - defensive worker guard
            self._repository.mark_failed(record.full_path, str(exc))
            self._progress = self._replace_progress(processed=1, failed=1, last_error=str(exc), current_file=None)
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
        record = next((item for item in self._repository.get_pending() if item.full_path == str(path)), None)
        if record is None:
            return WorkerResult(file_path=str(path), outcome=WorkerOutcome.FAILED, error_message="Path not queued")
        self._repository.mark_processing(record.full_path)
        return self._processor(record)

    def _default_processor(self, record: QueueRepositoryRecord) -> WorkerResult:
        # Milestone 2B+ will plug in parser, chunking, embedding, and storage here.
        if record.change_type == ChangeType.DELETED:
            return WorkerResult(file_path=record.full_path, outcome=WorkerOutcome.COMPLETED)
        return WorkerResult(file_path=record.full_path, outcome=WorkerOutcome.COMPLETED)

    def _replace_progress(self, **updates: object) -> WorkerProgress:
        data = self._progress.__dict__.copy()
        data.update(updates)
        return WorkerProgress(**data)
