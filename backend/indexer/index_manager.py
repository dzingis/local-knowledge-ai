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


class ChangeType(str, Enum):
    NEW = "New"
    MODIFIED = "Modified"
    DELETED = "Deleted"
    UNCHANGED = "Unchanged"


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


@dataclass(frozen=True)
class ChangeSetItem:
    """Represents one file change detected during an incremental scan."""

    file_name: str
    full_path: str
    extension: str
    folder_path: str
    file_size_bytes: int
    modified_utc: datetime
    sha256: str
    change_type: ChangeType

    @classmethod
    def from_record(cls, record: PersistentScanRecord, change_type: ChangeType) -> "ChangeSetItem":
        return cls(
            file_name=record.file_name,
            full_path=record.full_path,
            extension=record.extension,
            folder_path=record.folder_path,
            file_size_bytes=record.file_size_bytes,
            modified_utc=record.modified_utc,
            sha256=record.sha256,
            change_type=change_type,
        )


@dataclass
class ScanQueueResult:
    records: list[PersistentScanRecord] = field(default_factory=list)
    pending_items: list[QueueItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)


@dataclass
class IncrementalScanResult:
    """Classifies files discovered in the current scan against previous fingerprints."""

    new_files: list[ChangeSetItem] = field(default_factory=list)
    modified_files: list[ChangeSetItem] = field(default_factory=list)
    deleted_files: list[ChangeSetItem] = field(default_factory=list)
    unchanged_files: list[ChangeSetItem] = field(default_factory=list)

    @property
    def pending_changes(self) -> list[ChangeSetItem]:
        return self.new_files + self.modified_files


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

    def compare_with_previous(
        self,
        current_records: Sequence[PersistentScanRecord],
        previous_fingerprints: dict[str, str],
        previously_known_paths: Iterable[str] | None = None,
    ) -> IncrementalScanResult:
        known_paths = set(previously_known_paths or previous_fingerprints.keys())
        current_paths = {record.full_path for record in current_records}

        new_files: list[ChangeSetItem] = []
        modified_files: list[ChangeSetItem] = []
        unchanged_files: list[ChangeSetItem] = []

        for record in current_records:
            previous_sha = previous_fingerprints.get(record.full_path)
            if previous_sha is None:
                new_files.append(ChangeSetItem.from_record(record, ChangeType.NEW))
            elif previous_sha != record.sha256:
                modified_files.append(ChangeSetItem.from_record(record, ChangeType.MODIFIED))
            else:
                unchanged_files.append(ChangeSetItem.from_record(record, ChangeType.UNCHANGED))

        deleted_files: list[ChangeSetItem] = []
        missing_paths = known_paths - current_paths
        for missing_path in missing_paths:
            deleted_files.append(
                ChangeSetItem(
                    file_name=Path(missing_path).name,
                    full_path=missing_path,
                    extension=Path(missing_path).suffix.lower(),
                    folder_path=str(Path(missing_path).parent),
                    file_size_bytes=0,
                    modified_utc=datetime.now(timezone.utc),
                    sha256=previous_fingerprints.get(missing_path, ""),
                    change_type=ChangeType.DELETED,
                )
            )

        return IncrementalScanResult(
            new_files=new_files,
            modified_files=modified_files,
            deleted_files=deleted_files,
            unchanged_files=unchanged_files,
        )
