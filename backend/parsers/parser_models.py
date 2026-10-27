from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ParserKind(str, Enum):
    SQL = "sql"
    PDF = "pdf"
    WORD = "word"
    DELPHI = "delphi"
    MARKDOWN = "markdown"
    TEXT = "text"


class ParsedObjectType(str, Enum):
    UNKNOWN = "unknown"
    TABLE = "table"
    VIEW = "view"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TRIGGER = "trigger"
    INDEX = "index"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class ParserReference:
    name: str
    kind: str
    schema: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_path: Path
    parser_kind: ParserKind
    object_type: ParsedObjectType
    title: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    references: tuple[ParserReference, ...] = ()
    checksum: str | None = None
    language: str | None = None
    page_count: int | None = None
    line_count: int | None = None
    character_count: int = 0


@dataclass(frozen=True, slots=True)
class ParserSummary:
    source_path: Path
    parser_kind: ParserKind
    object_type: ParsedObjectType
    title: str
    line_count: int
    character_count: int
    reference_count: int
