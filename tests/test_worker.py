from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pytest

from backend.indexer.index_manager import ChangeType
from backend.indexer.sql_queue_repository import QueueRepositoryRecord
from backend.workers.processing_worker import ProcessingWorker, WorkerOutcome


@dataclass
class InMemoryQueueRepository:
    """Deterministic in-memory queue repository used by the integration test."""

    records: list[QueueRepositoryRecord]
    completed: list[str]
    failed: list[str]
    processing: list[str]
    retried: list[str]

    def __init__(self, records: Iterable[QueueRepositoryRecord] | None = None) -> None:
        self.records = list(records or [])
        self.completed = []
        self.failed = []
        self.processing = []
        self.retried = []

    def enqueue_many(self, items: Iterable[QueueRepositoryRecord]) -> int:
        new_items = list(items)
        self.records.extend(new_items)
        return len(new_items)

    def get_pending(self) -> tuple[QueueRepositoryRecord, ...]:
        return tuple(record for record in self.records if record.status == ChangeType.INSERTED)

    def mark_processing(self, full_path: str) -> bool:
        self.processing.append(full_path)
        return True

    def mark_completed(self, full_path: str) -> bool:
        self.completed.append(full_path)
        return True

    def mark_failed(self, full_path: str, error_message: str | None = None) -> bool:
        self.failed.append(full_path)
        return True

    def retry(self, full_path: str) -> bool:
        self.retried.append(full_path)
        return True


@pytest.mark.integration
def test_end_to_end_ingestion_pipeline(tmp_path: Path) -> None:
    """Verify that a document can move through queue processing end to end.

    This test is intentionally self-contained and does not depend on SQL Server,
    Qdrant, or other external services.
    """
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text(
        "Hello world. This is a sample document for the ingestion pipeline.",
        encoding="utf-8",
    )

    record = QueueRepositoryRecord(
        file_name=sample_file.name,
        full_path=str(sample_file),
        extension=sample_file.suffix.lstrip("."),
        folder_path=str(sample_file.parent),
        file_size_bytes=sample_file.stat().st_size,
        modified_utc=datetime.now(timezone.utc),
        sha256="integration-test-sha",
        status=ChangeType.INSERTED,
        change_type=ChangeType.INSERTED,
        enqueued_at=datetime.now(timezone.utc),
    )

    queue_repository = InMemoryQueueRepository([record])
    worker = ProcessingWorker(repository=queue_repository)  # type: ignore[arg-type]

    result = worker.run_once()

    assert result is not None, "Expected the worker to process the queued document"
    assert result.file_path == str(sample_file)
    assert result.outcome == WorkerOutcome.COMPLETED
    assert str(sample_file) in queue_repository.processing
    assert str(sample_file) in queue_repository.completed
    assert str(sample_file) not in queue_repository.failed
