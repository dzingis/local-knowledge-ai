from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Sequence

from backend.indexer.index_manager import ChangeSetItem, ChangeType, PersistentScanRecord, QueueItem, QueueStatus


class RepositoryOperation(str, Enum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class QueueRepositoryRecord:
    file_name: str
    full_path: str
    extension: str
    folder_path: str
    file_size_bytes: int
    modified_utc: datetime
    sha256: str
    status: QueueStatus
    change_type: ChangeType
    enqueued_at: datetime
    processed_at: datetime | None = None
    error_message: str | None = None

    @classmethod
    def from_change_set_item(cls, item: ChangeSetItem) -> "QueueRepositoryRecord":
        status = QueueStatus.PENDING
        if item.change_type == ChangeType.DELETED:
            status = QueueStatus.COMPLETED
        return cls(
            file_name=item.file_name,
            full_path=item.full_path,
            extension=item.extension,
            folder_path=item.folder_path,
            file_size_bytes=item.file_size_bytes,
            modified_utc=item.modified_utc,
            sha256=item.sha256,
            status=status,
            change_type=item.change_type,
            enqueued_at=datetime.now(timezone.utc),
        )

    @classmethod
    def from_persistent_record(cls, record: PersistentScanRecord, change_type: ChangeType) -> "QueueRepositoryRecord":
        return cls(
            file_name=record.file_name,
            full_path=record.full_path,
            extension=record.extension,
            folder_path=record.folder_path,
            file_size_bytes=record.file_size_bytes,
            modified_utc=record.modified_utc,
            sha256=record.sha256,
            status=record.status,
            change_type=change_type,
            enqueued_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True, slots=True)
class QueueRepositoryState:
    pending: tuple[QueueRepositoryRecord, ...] = ()
    processing: tuple[QueueRepositoryRecord, ...] = ()
    completed: tuple[QueueRepositoryRecord, ...] = ()
    failed: tuple[QueueRepositoryRecord, ...] = ()

    def all_records(self) -> tuple[QueueRepositoryRecord, ...]:
        return self.pending + self.processing + self.completed + self.failed


class SqlQueueRepository:
    """In-memory repository facade that mirrors the SQL Server queue shape.

    The implementation is intentionally SQL-friendly: the record model maps 1:1 to
    the queue table we will persist in Milestone 2F.
    """

    def __init__(self) -> None:
        self._pending: list[QueueRepositoryRecord] = []
        self._processing: list[QueueRepositoryRecord] = []
        self._completed: list[QueueRepositoryRecord] = []
        self._failed: list[QueueRepositoryRecord] = []

    def enqueue_many(self, items: Iterable[QueueRepositoryRecord]) -> int:
        count = 0
        for item in items:
            self._pending.append(item)
            count += 1
        return count

    def enqueue_changes(self, items: Sequence[ChangeSetItem]) -> int:
        records = [QueueRepositoryRecord.from_change_set_item(item) for item in items]
        return self.enqueue_many(records)

    def get_pending(self) -> tuple[QueueRepositoryRecord, ...]:
        return tuple(self._pending)

    def mark_processing(self, full_path: str) -> bool:
        return self._move_record(full_path, self._pending, self._processing, QueueStatus.PROCESSING)

    def mark_completed(self, full_path: str) -> bool:
        return self._move_record(full_path, self._processing, self._completed, QueueStatus.COMPLETED)

    def mark_failed(self, full_path: str, error_message: str | None = None) -> bool:
        moved = self._move_record(full_path, self._processing, self._failed, QueueStatus.FAILED)
        if moved and error_message:
            self._failed[-1] = QueueRepositoryRecord(
                **{**self._failed[-1].__dict__, "error_message": error_message}
            )
        return moved

    def remove(self, full_path: str) -> bool:
        for bucket in (self._pending, self._processing, self._completed, self._failed):
            for index, record in enumerate(bucket):
                if record.full_path == full_path:
                    del bucket[index]
                    return True
        return False

    def snapshot(self) -> QueueRepositoryState:
        return QueueRepositoryState(
            pending=tuple(self._pending),
            processing=tuple(self._processing),
            completed=tuple(self._completed),
            failed=tuple(self._failed),
        )

    def _move_record(
        self,
        full_path: str,
        source: list[QueueRepositoryRecord],
        target: list[QueueRepositoryRecord],
        new_status: QueueStatus,
    ) -> bool:
        for index, record in enumerate(source):
            if record.full_path == full_path:
                source.pop(index)
                target.append(
                    QueueRepositoryRecord(
                        file_name=record.file_name,
                        full_path=record.full_path,
                        extension=record.extension,
                        folder_path=record.folder_path,
                        file_size_bytes=record.file_size_bytes,
                        modified_utc=record.modified_utc,
                        sha256=record.sha256,
                        status=new_status,
                        change_type=record.change_type,
                        enqueued_at=record.enqueued_at,
                        processed_at=datetime.now(timezone.utc),
                        error_message=record.error_message,
                    )
                )
                return True
        return False


@dataclass(frozen=True, slots=True)
class QueueRepositorySummary:
    pending: int
    processing: int
    completed: int
    failed: int

    @classmethod
    def from_state(cls, state: QueueRepositoryState) -> "QueueRepositorySummary":
        return cls(
            pending=len(state.pending),
            processing=len(state.processing),
            completed=len(state.completed),
            failed=len(state.failed),
        )
