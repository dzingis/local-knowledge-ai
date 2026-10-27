from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

from backend.parsers.delphi_parser import DelphiParser
from backend.parsers.markdown_parser import MarkdownParser
from backend.parsers.pdf_parser import PdfParser
from backend.parsers.parser_models import ParsedDocument, ParserKind
from backend.parsers.sql_parser import SqlParser
from backend.parsers.text_parser import TextParser
from backend.parsers.word_parser import WordParser


class Parser(Protocol):
    def parse_file(self, path: str | Path) -> ParsedDocument:
        ...

    def parse_many(self, paths: Iterable[str | Path]) -> tuple[ParsedDocument, ...]:
        ...


@dataclass(slots=True)
class ParserService:
    """Route files to the appropriate parser implementation by extension."""

    sql_parser: SqlParser = field(default_factory=SqlParser)
    pdf_parser: PdfParser = field(default_factory=PdfParser)
    word_parser: WordParser = field(default_factory=WordParser)
    delphi_parser: DelphiParser = field(default_factory=DelphiParser)
    markdown_parser: MarkdownParser = field(default_factory=MarkdownParser)
    text_parser: TextParser = field(default_factory=TextParser)

    def parse_file(self, path: str | Path) -> ParsedDocument:
        file_path = Path(path)
        suffix = file_path.suffix.lower()

        if suffix == ".sql":
            return self.sql_parser.parse_file(file_path)
        if suffix == ".pdf":
            return self.pdf_parser.parse_file(file_path)
        if suffix == ".docx":
            return self.word_parser.parse_file(file_path)
        if suffix in {".pas", ".dfm"}:
            return self.delphi_parser.parse_file(file_path)
        if suffix in {".md", ".markdown"}:
            return self.markdown_parser.parse_file(file_path)
        return self.text_parser.parse_file(file_path)

    def parse_many(self, paths: Iterable[str | Path]) -> tuple[ParsedDocument, ...]:
        return tuple(self.parse_file(path) for path in paths)

    def parser_kind_for_path(self, path: str | Path) -> ParserKind:
        file_path = Path(path)
        suffix = file_path.suffix.lower()

        if suffix == ".sql":
            return ParserKind.SQL
        if suffix == ".pdf":
            return ParserKind.PDF
        if suffix == ".docx":
            return ParserKind.WORD
        if suffix in {".pas", ".dfm"}:
            return ParserKind.DELPHI
        if suffix in {".md", ".markdown"}:
            return ParserKind.MARKDOWN
        return ParserKind.TEXT


__all__ = ["ParserService", "Parser"]
