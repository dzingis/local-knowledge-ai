from __future__ import annotations

import time
from datetime import datetime, timezone
from threading import Event

from backend.indexer.index_manager import ChangeType, QueueStatus
from backend.indexer.sql_queue_repository import QueueRepositoryRecord
from backend.workers.processing_worker import (
    ProcessingWorker,
    WorkerOutcome,
    WorkerResult,
    WorkerStatus,
)


class InMemoryQueueRepository:
    def __init__(self, record: QueueRepositoryRecord) -> None:
        self._pending = [record]
        self.completed: list[str] = []

    def get_pending(self) -> tuple[QueueRepositoryRecord, ...]:
        return tuple(self._pending)

    def mark_processing(self, full_path: str) -> bool:
        return True

    def mark_completed(self, full_path: str) -> bool:
        self.completed.append(full_path)
        self._pending = [record for record in self._pending if record.full_path != full_path]
        return True

    def mark_failed(self, full_path: str, error_message: str | None = None) -> bool:
        return True

    def retry(self, full_path: str) -> bool:
        return True


def test_worker_loop_consumes_pending_queue_and_stops() -> None:
    record = QueueRepositoryRecord(
        file_name="queued.txt",
        full_path="/knowledge/queued.txt",
        extension="txt",
        folder_path="/knowledge",
        file_size_bytes=12,
        modified_utc=datetime.now(timezone.utc),
        sha256="test-hash",
        status=QueueStatus.PENDING,
        change_type=ChangeType.NEW,
        enqueued_at=datetime.now(timezone.utc),
    )
    repository = InMemoryQueueRepository(record)
    processed = Event()

    def processor(item: QueueRepositoryRecord) -> WorkerResult:
        processed.set()
        return WorkerResult(file_path=item.full_path, outcome=WorkerOutcome.COMPLETED)

    worker = ProcessingWorker(
        repository=repository,  # type: ignore[arg-type]
        processor=processor,
        poll_interval_seconds=0.05,
    )
    worker.start()
    try:
        assert processed.wait(timeout=2)
        deadline = time.monotonic() + 2
        while worker.progress.processed != 1 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert repository.completed == [record.full_path]
        assert worker.progress.processed == 1
        assert worker.progress.succeeded == 1
        assert worker.progress.status == WorkerStatus.RUNNING
    finally:
        worker.stop()

    assert worker.progress.status == WorkerStatus.STOPPED


def test_worker_start_is_idempotent() -> None:
    record = QueueRepositoryRecord(
        file_name="queued.txt",
        full_path="/knowledge/queued.txt",
        extension="txt",
        folder_path="/knowledge",
        file_size_bytes=12,
        modified_utc=datetime.now(timezone.utc),
        sha256="test-hash",
        status=QueueStatus.PENDING,
        change_type=ChangeType.NEW,
        enqueued_at=datetime.now(timezone.utc),
    )
    worker = ProcessingWorker(
        repository=InMemoryQueueRepository(record),  # type: ignore[arg-type]
        poll_interval_seconds=0.05,
    )

    worker.start()
    first_thread = worker._thread
    worker.start()
    try:
        assert worker._thread is first_thread
    finally:
        worker.stop()
