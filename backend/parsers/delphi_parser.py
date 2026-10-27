from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import re
from typing import Iterable

from backend.parsers.parser_models import ParsedDocument, ParsedObjectType, ParserKind, ParserReference, ParserSummary


@dataclass(frozen=True, slots=True)
class DelphiSymbol:
    name: str
    kind: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class DelphiParseResult:
    source_path: Path
    unit_name: str
    symbols: tuple[DelphiSymbol, ...]
    uses_units: tuple[str, ...]
    text: str
    metadata: dict[str, str]


class DelphiParser:
    """Parse Delphi/Pascal source into a normalized, search-ready document.

    The parser focuses on extracting structural information that is useful for
    code search and knowledge graph ingestion:
    - unit/program/library names
    - uses/import clauses
    - class/procedure/function declarations
    - SQL strings and URLs where present
    """

    UNIT_PATTERN = re.compile(r"\bunit\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;", re.IGNORECASE)
    PROGRAM_PATTERN = re.compile(r"\bprogram\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;", re.IGNORECASE)
    LIBRARY_PATTERN = re.compile(r"\blibrary\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;", re.IGNORECASE)
    CLASS_PATTERN = re.compile(r"\bclass\s*\(", re.IGNORECASE)
    DECL_PATTERN = re.compile(
        r"\b(?P<kind>procedure|function|constructor|destructor)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?(?:\.[A-Za-z_][A-Za-z0-9_]*)*)",
        re.IGNORECASE,
    )
    USES_PATTERN = re.compile(r"\buses\s+(?P<uses>.*?);", re.IGNORECASE | re.DOTALL)
    SQL_PATTERN = re.compile(r"\b(?:select|insert|update|delete|merge|create|alter|drop)\b", re.IGNORECASE)
    URL_PATTERN = re.compile(r"https?://[^\s'\"]+", re.IGNORECASE)

    def parse_file(self, path: str | Path) -> ParsedDocument:
        source_path = Path(path)
        text = source_path.read_text(encoding="utf-8", errors="ignore")
        normalized = self._normalize(text)
        unit_name = self._extract_unit_name(normalized, source_path)
        uses_units = self._extract_uses_units(normalized)
        symbols = self._extract_symbols(normalized)
        references = self._extract_references(normalized)
        metadata = {
            "source_format": source_path.suffix.lower().lstrip("."),
            "unit_name": unit_name,
            "uses_count": str(len(uses_units)),
            "symbol_count": str(len(symbols)),
        }
        if self.SQL_PATTERN.search(normalized):
            metadata["contains_sql"] = "true"
        if self.URL_PATTERN.search(normalized):
            metadata["contains_url"] = "true"
        return ParsedDocument(
            source_path=source_path,
            parser_kind=ParserKind.DELPHI,
            object_type=ParsedObjectType.DOCUMENT,
            title=unit_name,
            text=normalized,
            metadata=metadata,
            references=references,
            checksum=self._checksum(normalized),
            language="delphi",
            line_count=normalized.count("\n") + (1 if normalized else 0),
            character_count=len(normalized),
        )

    def parse_many(self, paths: Iterable[str | Path]) -> tuple[ParsedDocument, ...]:
        return tuple(self.parse_file(path) for path in paths)

    def summarize(self, documents: Iterable[ParsedDocument]) -> ParserSummary:
        docs = tuple(documents)
        if not docs:
            return ParserSummary(
                source_path=Path("<empty>"),
                parser_kind=ParserKind.DELPHI,
                object_type=ParsedObjectType.DOCUMENT,
                title="",
                line_count=0,
                character_count=0,
                reference_count=0,
            )
        first = docs[0]
        return ParserSummary(
            source_path=first.source_path,
            parser_kind=ParserKind.DELPHI,
            object_type=ParsedObjectType.DOCUMENT,
            title=first.title,
            line_count=sum(doc.line_count or 0 for doc in docs),
            character_count=sum(doc.character_count for doc in docs),
            reference_count=sum(len(doc.references) for doc in docs),
        )

    def _extract_unit_name(self, text: str, source_path: Path) -> str:
        for pattern in (self.UNIT_PATTERN, self.PROGRAM_PATTERN, self.LIBRARY_PATTERN):
            match = pattern.search(text)
            if match:
                return match.group("name")
        return source_path.stem

    def _extract_uses_units(self, text: str) -> tuple[str, ...]:
        match = self.USES_PATTERN.search(text)
        if not match:
            return ()
        raw = match.group("uses")
        parts = [part.strip() for part in raw.split(",")]
        cleaned: list[str] = []
        for part in parts:
            if not part:
                continue
            token = part.split("=")[0].split(" as ")[0].strip()
            token = token.split("(")[0].strip()
            if token:
                cleaned.append(token)
        return tuple(dict.fromkeys(cleaned))

    def _extract_symbols(self, text: str) -> tuple[DelphiSymbol, ...]:
        symbols: list[DelphiSymbol] = []
        for index, line in enumerate(text.splitlines(), start=1):
            match = self.DECL_PATTERN.search(line)
            if match:
                symbols.append(DelphiSymbol(name=match.group("name"), kind=match.group("kind").lower(), line=index))
            if self.CLASS_PATTERN.search(line):
                symbols.append(DelphiSymbol(name="class", kind="type", line=index))
        return tuple(symbols)

    def _extract_references(self, text: str) -> tuple[ParserReference, ...]:
        refs: list[ParserReference] = []
        seen: set[str] = set()
        for index, line in enumerate(text.splitlines(), start=1):
            for url in self.URL_PATTERN.findall(line):
                if url in seen:
                    continue
                seen.add(url)
                refs.append(ParserReference(name=url, kind="url", line=index))
            if self.SQL_PATTERN.search(line):
                marker = f"sql-line-{index}"
                if marker not in seen:
                    seen.add(marker)
                    refs.append(ParserReference(name=marker, kind="sql", line=index))
        return tuple(refs)

    def _normalize(self, text: str) -> str:
        return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()

    def _checksum(self, text: str) -> str:
        digest = hashlib.sha256()
        digest.update(text.encode("utf-8", errors="ignore"))
        return digest.hexdigest()
