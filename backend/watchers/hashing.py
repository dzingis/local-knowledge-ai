from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from backend.indexer.hasher import sha256_file


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    sha256: str
    modified_utc: datetime


class FingerprintCache:
    def __init__(self) -> None:
        self._fingerprints: dict[str, FileFingerprint] = {}
        self._lock = Lock()

    def is_duplicate(self, path: str | Path, fingerprint: FileFingerprint) -> bool:
        key = str(path)
        with self._lock:
            return self._fingerprints.get(key) == fingerprint

    def remember(self, path: str | Path, fingerprint: FileFingerprint) -> None:
        with self._lock:
            self._fingerprints[str(path)] = fingerprint


def fingerprint_file(path: str | Path, modified_timestamp: float) -> FileFingerprint:
    return FileFingerprint(
        sha256=sha256_file(path),
        modified_utc=datetime.fromtimestamp(modified_timestamp, timezone.utc),
    )
