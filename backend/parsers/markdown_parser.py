from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable

from backend.parsers.parser_models import (
    ParsedDocument,
    ParsedObjectType,
    ParserKind,
    ParserReference,
    ParserSummary,
)


@dataclass(frozen=True, slots=True)
class MarkdownHeading:
    level: int
    text: str
    line: int


@dataclass(frozen=True, slots=True)
class MarkdownParseResult:
    source_path: Path
    title: str
    headings: tuple[MarkdownHeading, ...]
    text: str
    line_count: int
    character_count: int
    references: tuple[ParserReference, ...]


class MarkdownParser:
    """Parse Markdown documents into a normalized, search-ready representation."""

    def parse_file(self, path: str | Path) -> ParsedDocument:
        source_path = Path(path)
        text = source_path.read_text(encoding="utf-8", errors="ignore")
        result = self._parse_markdown_text(text, source_path)
        return self._to_parsed_document(result)

    def parse_text(self, text: str, source_path: str | Path = "<memory>") -> ParsedDocument:
        result = self._parse_markdown_text(text, Path(source_path))
        return self._to_parsed_document(result)

    def parse_many(self, paths: Iterable[str | Path]) -> tuple[ParsedDocument, ...]:
        return tuple(self.parse_file(path) for path in paths)

    def summarize(self, documents: Iterable[ParsedDocument]) -> ParserSummary:
        docs = tuple(documents)
        if not docs:
            return ParserSummary(
                source_path=Path("<empty>"),
                parser_kind=ParserKind.MARKDOWN,
                object_type=ParsedObjectType.DOCUMENT,
                title="",
                line_count=0,
                character_count=0,
                reference_count=0,
            )

        first = docs[0]
        return ParserSummary(
            source_path=first.source_path,
            parser_kind=ParserKind.MARKDOWN,
            object_type=ParsedObjectType.DOCUMENT,
            title=first.title,
            line_count=sum(doc.line_count or 0 for doc in docs),
            character_count=sum(doc.character_count for doc in docs),
            reference_count=sum(len(doc.references) for doc in docs),
        )

    def _parse_markdown_text(self, text: str, source_path: Path) -> MarkdownParseResult:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        headings: list[MarkdownHeading] = []
        references: list[ParserReference] = []
        seen_references: set[str] = set()
        title = source_path.stem

        in_code_block = False
        for index, raw_line in enumerate(lines, start=1):
            line = raw_line.rstrip()
            stripped = line.strip()

            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = not in_code_block
                continue

            if not in_code_block and stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                heading_text = stripped[level:].strip()
                if heading_text:
                    headings.append(MarkdownHeading(level=level, text=heading_text, line=index))
                    if level == 1 and title == source_path.stem:
                        title = heading_text

            for candidate in self._extract_links(stripped):
                if candidate in seen_references:
                    continue
                seen_references.add(candidate)
                references.append(ParserReference(name=candidate, kind="link", line=index))

            for candidate in self._extract_markers(stripped):
                if candidate in seen_references:
                    continue
                seen_references.add(candidate)
                references.append(ParserReference(name=candidate, kind="marker", line=index))

        cleaned_text = self._normalize_text(normalized)
        return MarkdownParseResult(
            source_path=source_path,
            title=title,
            headings=tuple(headings),
            text=cleaned_text,
            line_count=len(lines),
            character_count=len(cleaned_text),
            references=tuple(references),
        )

    def _to_parsed_document(self, result: MarkdownParseResult) -> ParsedDocument:
        return ParsedDocument(
            source_path=result.source_path,
            parser_kind=ParserKind.MARKDOWN,
            object_type=ParsedObjectType.DOCUMENT,
            title=result.title,
            text=result.text,
            metadata={
                "source_format": "markdown",
                "heading_count": len(result.headings),
            },
            references=result.references,
            checksum=self._checksum_text(result.text),
            language="markdown",
            line_count=result.line_count,
            character_count=result.character_count,
        )

    def _extract_links(self, text: str) -> list[str]:
        links: list[str] = []
        start = 0
        while True:
            open_bracket = text.find("[", start)
            if open_bracket == -1:
                break
            close_bracket = text.find("]", open_bracket + 1)
            open_paren = text.find("(", close_bracket + 1)
            close_paren = text.find(")", open_paren + 1)
            if close_bracket != -1 and open_paren != -1 and close_paren != -1:
                candidate = text[open_bracket + 1 : close_bracket].strip()
                if candidate:
                    links.append(candidate)
                start = close_paren + 1
            else:
                break
        return links

    def _extract_markers(self, text: str) -> list[str]:
        markers: list[str] = []
        for token in text.replace("/", " ").replace("-", " ").split():
            token = token.strip("[](){}.,:;\"'")
            if token and len(token) > 2 and token[0].isupper():
                markers.append(token)
        return markers

    def _normalize_text(self, text: str) -> str:
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    def _checksum_text(self, text: str) -> str:
        digest = hashlib.sha256()
        digest.update(text.encode("utf-8", errors="ignore"))
        return digest.hexdigest()
