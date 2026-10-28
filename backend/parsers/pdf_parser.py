from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from backend.parsers.parser_models import ParsedDocument, ParsedObjectType, ParserKind, ParserReference, ParserSummary


@dataclass(frozen=True, slots=True)
class PdfPage:
    page_number: int
    text: str
    ocr_used: bool = False


@dataclass(frozen=True, slots=True)
class PdfParseResult:
    source_path: Path
    pages: tuple[PdfPage, ...]
    title: str
    text: str
    metadata: dict[str, Any]
    checksum: str | None = None
    page_count: int | None = None
    language: str | None = None

    def to_parsed_document(self) -> ParsedDocument:
        return ParsedDocument(
            source_path=self.source_path,
            parser_kind=ParserKind.PDF,
            object_type=ParsedObjectType.DOCUMENT,
            title=self.title,
            text=self.text,
            metadata={**self.metadata, "pages": len(self.pages)},
            references=(),
            checksum=self.checksum,
            language=self.language,
            page_count=self.page_count or len(self.pages),
            line_count=self.text.count("\n") + (1 if self.text else 0),
            character_count=len(self.text),
        )


class PdfParser:
    """Parse PDF documents into the shared parser model."""

    _MIN_IMAGE_PAGE_AREA_RATIO = 0.2

    def parse_text(self, text: str, source_path: str | Path = "<memory>") -> PdfParseResult:
        source = Path(source_path)
        pages = tuple(PdfPage(page_number=1, text=text.strip()))
        return PdfParseResult(
            source_path=source,
            pages=pages,
            title=source.stem,
            text=text.strip(),
            metadata={"source": str(source)},
            page_count=len(pages),
        )

    def parse_file(self, path: str | Path) -> PdfParseResult:
        source = Path(path)
        with pymupdf.open(source) as doc:
            pages: list[PdfPage] = []
            texts: list[str] = []
            ocr_pages: list[int] = []
            for index, page in enumerate(doc, start=1):
                page_text = page.get_text("text").strip()
                ocr_used = self._has_picture_content(page)
                if ocr_used:
                    text_page = page.get_textpage_ocr(language="eng+hrv", dpi=300, full=False)
                    page_text = page.get_text("text", textpage=text_page).strip()
                    ocr_pages.append(index)
                pages.append(PdfPage(page_number=index, text=page_text, ocr_used=ocr_used))
                if page_text:
                    texts.append(page_text)
            metadata = {
                "page_count": len(pages),
                "ocr_pages": ocr_pages,
                "file_size": source.stat().st_size if source.exists() else None,
                "title": doc.metadata.get("title") if getattr(doc, "metadata", None) else None,
            }

        return PdfParseResult(
            source_path=source,
            pages=tuple(pages),
            title=(metadata.get("title") or source.stem),
            text="\n\n".join(texts).strip(),
            metadata=metadata,
            page_count=len(pages),
        )

    def _has_picture_content(self, page: pymupdf.Page) -> bool:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return False

        return any(
            (image_bbox := pymupdf.Rect(image["bbox"])).width
            * image_bbox.height
            / page_area
            >= self._MIN_IMAGE_PAGE_AREA_RATIO
            for image in page.get_image_info(xrefs=True)
        )

    def summarize(self, result: PdfParseResult) -> ParserSummary:
        parsed = result.to_parsed_document()
        return ParserSummary(
            source_path=parsed.source_path,
            parser_kind=parsed.parser_kind,
            object_type=parsed.object_type,
            title=parsed.title,
            line_count=parsed.line_count or 0,
            character_count=parsed.character_count,
            reference_count=len(parsed.references),
        )
