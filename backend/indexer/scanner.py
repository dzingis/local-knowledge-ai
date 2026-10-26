from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.indexer.hasher import sha256_file


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".sql",
    ".pas",
    ".dfm",
    ".txt",
    ".md",
}


@dataclass(frozen=True, slots=True)
class FileMetadata:
    path: Path
    name: str
    extension: str
    size_bytes: int
    modified_utc: float
    sha256: str
    is_supported: bool


@dataclass(frozen=True, slots=True)
class ScanResult:
    root: Path
    files: tuple[FileMetadata, ...]


def is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def iter_supported_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if is_supported_file(path):
            yield path


def collect_metadata(path: Path) -> FileMetadata:
    stat_result = path.stat()
    return FileMetadata(
        path=path.resolve(),
        name=path.name,
        extension=path.suffix.lower(),
        size_bytes=stat_result.st_size,
        modified_utc=stat_result.st_mtime,
        sha256=sha256_file(path),
        is_supported=True,
    )


def scan_folder(root: str | Path) -> ScanResult:
    root_path = Path(root).expanduser().resolve()
    files = tuple(collect_metadata(path) for path in iter_supported_files(root_path))
    return ScanResult(root=root_path, files=files)
