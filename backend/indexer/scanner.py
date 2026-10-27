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

    @property
    def full_path(self) -> Path:
        return self.path

    @property
    def file_name(self) -> str:
        return self.name

    @property
    def file_size_bytes(self) -> int:
        return self.size_bytes

    @property
    def folder_path(self) -> Path:
        return self.path.parent


@dataclass(frozen=True, slots=True)
class ScanResult:
    root: Path
    files: tuple[FileMetadata, ...]


class FileScanner:
    """Compatibility wrapper used by IndexManager."""

    def __init__(self, supported_extensions: Iterable[str] | None = None) -> None:
        self.supported_extensions = {
            ext.lower() for ext in (supported_extensions or SUPPORTED_EXTENSIONS)
        }

    def scan(self, roots: Iterable[Path]) -> ScanResult:
        collected: list[FileMetadata] = []
        last_root: Path | None = None

        for root in roots:
            root_path = Path(root).expanduser().resolve()
            last_root = root_path
            for path in root_path.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in self.supported_extensions:
                    continue
                collected.append(self.collect_metadata(path))

        return ScanResult(root=last_root or Path.cwd(), files=tuple(collected))

    def collect_metadata(self, path: Path) -> FileMetadata:
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


def is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def iter_supported_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if is_supported_file(path):
            yield path


def collect_metadata(path: Path) -> FileMetadata:
    return FileScanner().collect_metadata(path)


def scan_folder(root: str | Path) -> ScanResult:
    root_path = Path(root).expanduser().resolve()
    scanner = FileScanner()
    return scanner.scan([root_path])
