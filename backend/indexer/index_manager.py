from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from backend.indexer.hasher import hash_file
from backend.indexer.scanner import FileMetadata, FileScanner, ScanResult


class QueueStatus(str, Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"


@dataclass(frozen=True)
class QueueItem:
    """Represents a single file queued for later parsing and indexing."""

    source_path: Path
    status: QueueStatus = QueueStatus.PENDING
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str | None = None


@dataclass(frozen=True)
class PersistentScanRecord:
    """A SQL-friendly representation of a scanned file."""

    file_name: str
    full_path: str
    extension: str
    folder_path: str
    file_size_bytes: int
    modified_utc: datetime
    sha256: str
    status: QueueStatus = QueueStatus.PENDING

    @classmethod
    def from_metadata(cls, metadata: FileMetadata, status: QueueStatus = QueueStatus.PENDING) -> "PersistentScanRecord":
        return cls(
            file_name=metadata.file_name,
            full_path=str(metadata.full_path),
            extension=metadata.extension,
            folder_path=str(metadata.folder_path),
            file_size_bytes=metadata.file_size_bytes,
            modified_utc=metadata.modified_utc,
            sha256=metadata.sha256,
            status=status,
        )


@dataclass
class ScanQueueResult:
    records: list[PersistentScanRecord] = field(default_factory=list)
    pending_items: list[QueueItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)


class IndexManager:
    """Coordinates scanning and queue preparation for Milestone 2A."""

    def __init__(self, supported_extensions: Sequence[str] | None = None) -> None:
        self.scanner = FileScanner(supported_extensions=supported_extensions)

    def build_queue(self, roots: Iterable[Path]) -> ScanQueueResult:
        scan_result: ScanResult = self.scanner.scan(roots)
        records = [PersistentScanRecord.from_metadata(item) for item in scan_result.files]
        pending_items = [QueueItem(source_path=item.full_path) for item in scan_result.files]
        return ScanQueueResult(records=records, pending_items=pending_items)

    def fingerprint(self, path: Path) -> str:
        return hash_file(path)
