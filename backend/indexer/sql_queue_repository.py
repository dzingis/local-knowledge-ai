from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Sequence

import pyodbc

from backend.config.settings import get_settings
from backend.indexer.index_manager import ChangeSetItem, ChangeType, PersistentScanRecord, QueueStatus


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
    retry_count: int = 0

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


class SqlQueueRepository:
    """SQL Server backed queue repository for Milestone 2A.3."""

    def __init__(self, connection_string: str | None = None) -> None:
        self._settings = get_settings()
        self._connection_string = connection_string or self._build_connection_string()

    def enqueue_many(self, items: Iterable[QueueRepositoryRecord]) -> int:
        records = tuple(items)
        if not records:
            return 0

        with self._connect() as connection:
            cursor = connection.cursor()
            for record in records:
                cursor.execute(
                    """
                    MERGE AI.IngestionQueue AS target
                    USING (SELECT ? AS FullPath) AS source
                    ON target.FullPath = source.FullPath
                    WHEN MATCHED THEN
                        UPDATE SET
                            FileName = ?,
                            Extension = ?,
                            FolderPath = ?,
                            FileSizeBytes = ?,
                            ModifiedUtc = ?,
                            Sha256 = ?,
                            Status = ?,
                            ChangeType = ?,
                            EnqueuedAt = ?,
                            ProcessedAt = ?,
                            ErrorMessage = ?,
                            RetryCount = ?
                    WHEN NOT MATCHED THEN
                        INSERT (
                            FileName,
                            FullPath,
                            Extension,
                            FolderPath,
                            FileSizeBytes,
                            ModifiedUtc,
                            Sha256,
                            Status,
                            ChangeType,
                            EnqueuedAt,
                            ProcessedAt,
                            ErrorMessage,
                            RetryCount
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        record.full_path,
                        record.file_name,
                        record.extension,
                        record.folder_path,
                        record.file_size_bytes,
                        record.modified_utc,
                        record.sha256,
                        record.status.value,
                        record.change_type.value,
                        record.enqueued_at,
                        record.processed_at,
                        record.error_message,
                        record.retry_count,
                        record.file_name,
                        record.full_path,
                        record.extension,
                        record.folder_path,
                        record.file_size_bytes,
                        record.modified_utc,
                        record.sha256,
                        record.status.value,
                        record.change_type.value,
                        record.enqueued_at,
                        record.processed_at,
                        record.error_message,
                        record.retry_count,
                    ),
                )
            connection.commit()
        return len(records)

    def enqueue_changes(self, items: Sequence[ChangeSetItem]) -> int:
        records = [QueueRepositoryRecord.from_change_set_item(item) for item in items]
        return self.enqueue_many(records)

    def get_fingerprint(self, full_path: str) -> tuple[str, datetime] | None:
        with self._connect() as connection:
            row = connection.cursor().execute(
                """
                SELECT Sha256, ModifiedUtc
                FROM AI.IngestionQueue
                WHERE FullPath = ?;
                """,
                (full_path,),
            ).fetchone()
        if row is None:
            return None

        modified_utc = row.ModifiedUtc
        if modified_utc.tzinfo is None:
            modified_utc = modified_utc.replace(tzinfo=timezone.utc)
        return str(row.Sha256), modified_utc

    def get_pending(self) -> tuple[QueueRepositoryRecord, ...]:
        return self._load_by_status(QueueStatus.PENDING)

    def get_processing(self) -> tuple[QueueRepositoryRecord, ...]:
        return self._load_by_status(QueueStatus.PROCESSING)

    def get_stale_processing(self, threshold_minutes: int) -> tuple[QueueRepositoryRecord, ...]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, threshold_minutes))
        with self._connect() as connection:
            cursor = connection.cursor()
            rows = cursor.execute(
                """
                SELECT
                    FileName,
                    FullPath,
                    Extension,
                    FolderPath,
                    FileSizeBytes,
                    ModifiedUtc,
                    Sha256,
                    Status,
                    ChangeType,
                    EnqueuedAt,
                    ProcessedAt,
                    ErrorMessage,
                    RetryCount
                FROM AI.IngestionQueue
                WHERE Status = ?
                  AND EnqueuedAt <= ?
                ORDER BY EnqueuedAt ASC;
                """,
                (QueueStatus.PROCESSING.value, cutoff),
            ).fetchall()

        return tuple(
            QueueRepositoryRecord(
                file_name=row.FileName,
                full_path=row.FullPath,
                extension=row.Extension,
                folder_path=row.FolderPath,
                file_size_bytes=int(row.FileSizeBytes),
                modified_utc=row.ModifiedUtc,
                sha256=row.Sha256,
                status=QueueStatus(row.Status),
                change_type=ChangeType(row.ChangeType),
                enqueued_at=row.EnqueuedAt,
                processed_at=row.ProcessedAt,
                error_message=row.ErrorMessage,
                retry_count=int(row.RetryCount or 0),
            )
            for row in rows
        )

    def mark_processing(self, full_path: str) -> bool:
        return self._update_status(full_path, QueueStatus.PROCESSING)

    def mark_completed(self, full_path: str) -> bool:
        return self._update_status(full_path, QueueStatus.COMPLETED)

    def mark_failed(self, full_path: str, error_message: str | None = None) -> bool:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE AI.IngestionQueue
                SET Status = ?,
                    ProcessedAt = SYSUTCDATETIME(),
                    ErrorMessage = ?,
                    RetryCount = RetryCount + 1
                WHERE FullPath = ?;
                """,
                (QueueStatus.FAILED.value, error_message, full_path),
            )
            connection.commit()
            return cursor.rowcount > 0

    def retry(self, full_path: str) -> bool:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE AI.IngestionQueue
                SET Status = ?,
                    ErrorMessage = NULL,
                    ProcessedAt = NULL,
                    EnqueuedAt = SYSUTCDATETIME()
                WHERE FullPath = ?;
                """,
                (QueueStatus.PENDING.value, full_path),
            )
            connection.commit()
            return cursor.rowcount > 0

    def remove(self, full_path: str) -> bool:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM AI.IngestionQueue WHERE FullPath = ?;", (full_path,))
            connection.commit()
            return cursor.rowcount > 0

    def snapshot(self) -> QueueRepositoryState:
        return QueueRepositoryState(
            pending=self.get_pending(),
            processing=self.get_processing(),
            completed=self._load_by_status(QueueStatus.COMPLETED),
            failed=self._load_by_status(QueueStatus.FAILED),
        )

    def get_statistics(self) -> QueueRepositorySummary:
        return QueueRepositorySummary.from_state(self.snapshot())

    def _update_status(self, full_path: str, status: QueueStatus) -> bool:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE AI.IngestionQueue
                SET Status = ?,
                    ProcessedAt = SYSUTCDATETIME()
                WHERE FullPath = ?;
                """,
                (status.value, full_path),
            )
            connection.commit()
            return cursor.rowcount > 0

    def _load_by_status(self, status: QueueStatus) -> tuple[QueueRepositoryRecord, ...]:
        with self._connect() as connection:
            cursor = connection.cursor()
            rows = cursor.execute(
                """
                SELECT
                    FileName,
                    FullPath,
                    Extension,
                    FolderPath,
                    FileSizeBytes,
                    ModifiedUtc,
                    Sha256,
                    Status,
                    ChangeType,
                    EnqueuedAt,
                    ProcessedAt,
                    ErrorMessage,
                    RetryCount
                FROM AI.IngestionQueue
                WHERE Status = ?
                ORDER BY EnqueuedAt ASC;
                """,
                (status.value,),
            ).fetchall()

        return tuple(
            QueueRepositoryRecord(
                file_name=row.FileName,
                full_path=row.FullPath,
                extension=row.Extension,
                folder_path=row.FolderPath,
                file_size_bytes=int(row.FileSizeBytes),
                modified_utc=row.ModifiedUtc,
                sha256=row.Sha256,
                status=QueueStatus(row.Status),
                change_type=ChangeType(row.ChangeType),
                enqueued_at=row.EnqueuedAt,
                processed_at=row.ProcessedAt,
                error_message=row.ErrorMessage,
                retry_count=int(row.RetryCount or 0),
            )
            for row in rows
        )

    def _build_connection_string(self) -> str:
        return (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={self._settings.sql_server},{self._settings.sql_port};"
            f"DATABASE={self._settings.sql_database};"
            f"UID={self._settings.sql_user};"
            f"PWD={self._settings.sql_password};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=5;"
        )

    def _connect(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)
