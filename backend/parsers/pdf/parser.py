from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(slots=True)
class PdfPageText:
    page_number: int
    text: str


@dataclass(slots=True)
class PdfParseResult:
    source_path: Path
    title: str | None
    pages: List[PdfPageText]


class PdfParser:
    """Extract structured text from PDF documents.

    The initial implementation intentionally stays lightweight so the project
    can evolve without locking into a single parsing backend.
    """

    supported_extensions: tuple[str, ...] = (".pdf",)

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_extensions

    def parse(self, path: Path) -> PdfParseResult:
        if not self.can_parse(path):
            raise ValueError(f"Unsupported PDF path: {path}")

        # Milestone 2B will extend this with a real PDF engine.
        return PdfParseResult(source_path=path, title=None, pages=[])

    def iter_page_text(self, result: PdfParseResult) -> Iterable[PdfPageText]:
        return result.pages
