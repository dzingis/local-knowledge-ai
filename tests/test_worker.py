from __future__ import annotations

from pathlib import Path

import pytest

from backend.indexer.index_manager import ChangeSetItem, ChangeType
from backend.indexer.sql_queue_repository import QueueRepositoryRecord, SqlQueueRepository
from backend.workers.processing_worker import ProcessingWorker


@pytest.mark.integration
def test_end_to_end_ingestion_pipeline(tmp_path: Path) -> None:
    """Verify that a document can move through queue processing end to end."""
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Hello world. This is a sample document for the ingestion pipeline.", encoding="utf-8")

    queue_repository = SqlQueueRepository()
    worker = ProcessingWorker(repository=queue_repository)

    record = QueueRepositoryRecord(
        file_name=sample_file.name,
        full_path=str(sample_file),
        extension=sample_file.suffix.lstrip("."),
        folder_path=str(sample_file.parent),
        file_size_bytes=sample_file.stat().st_size,
        modified_utc=sample_file.stat().st_mtime_ns and __import__("datetime").datetime.utcnow(),
        sha256="integration-test-sha",
        status=ChangeType.INSERTED,
        change_type=ChangeType.INSERTED,
        enqueued_at=__import__("datetime").datetime.utcnow(),
    )

    queue_repository.enqueue_many([record])

    result = worker.run_once()

    assert result is not None, "Expected the worker to process the queued document"
    assert result.file_path == str(sample_file)
    assert result.outcome.value in {"completed", "processed"}
