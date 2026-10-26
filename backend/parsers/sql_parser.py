from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from pathlib import Path
from typing import Iterable, Sequence


class SqlObjectType(str, Enum):
    TABLE = "table"
    VIEW = "view"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TRIGGER = "trigger"
    INDEX = "index"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SqlReference:
    name: str
    schema: str | None = None
    kind: str = "object"


@dataclass(frozen=True, slots=True)
class SqlParseResult:
    source_path: Path
    object_name: str
    schema_name: str | None
    object_type: SqlObjectType
    sql_text: str
    normalized_sql: str
    referenced_objects: tuple[SqlReference, ...] = ()
    created_objects: tuple[SqlReference, ...] = ()
    line_count: int = 0


@dataclass(frozen=True, slots=True)
class SqlParseSummary:
    total_objects: int = 0
    object_types: tuple[SqlObjectType, ...] = ()


class SqlParser:
    """Parse SQL Server scripts into a structured, search-ready representation."""

    CREATE_PATTERNS: tuple[tuple[SqlObjectType, re.Pattern[str]], ...] = (
        (SqlObjectType.TABLE, re.compile(r"\bCREATE\s+TABLE\s+(?P<name>(?:\[[^\]]+\]|\w+)(?:\.(?:\[[^\]]+\]|\w+))?)", re.IGNORECASE | re.MULTILINE)),
        (SqlObjectType.VIEW, re.compile(r"\bCREATE\s+VIEW\s+(?P<name>(?:\[[^\]]+\]|\w+)(?:\.(?:\[[^\]]+\]|\w+))?)", re.IGNORECASE | re.MULTILINE)),
        (SqlObjectType.PROCEDURE, re.compile(r"\bCREATE\s+(?:PROCEDURE|PROC)\s+(?P<name>(?:\[[^\]]+\]|\w+)(?:\.(?:\[[^\]]+\]|\w+))?)", re.IGNORECASE | re.MULTILINE)),
        (SqlObjectType.FUNCTION, re.compile(r"\bCREATE\s+FUNCTION\s+(?P<name>(?:\[[^\]]+\]|\w+)(?:\.(?:\[[^\]]+\]|\w+))?)", re.IGNORECASE | re.MULTILINE)),
        (SqlObjectType.TRIGGER, re.compile(r"\bCREATE\s+TRIGGER\s+(?P<name>(?:\[[^\]]+\]|\w+)(?:\.(?:\[[^\]]+\]|\w+))?)", re.IGNORECASE | re.MULTILINE)),
        (SqlObjectType.INDEX, re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?P<name>(?:\[[^\]]+\]|\w+))", re.IGNORECASE | re.MULTILINE)),
    )

    REFERENCE_PATTERN = re.compile(
        r"\b(?:FROM|JOIN|UPDATE|INTO|MERGE\s+INTO|DELETE\s+FROM|EXEC(?:UTE)?|CALL)\s+(?P<name>(?:\[[^\]]+\]|\w+)(?:\.(?:\[[^\]]+\]|\w+))?(?:\.(?:\[[^\]]+\]|\w+))?)",
        re.IGNORECASE | re.MULTILINE,
    )

    def __init__(self, default_schema: str = "dbo") -> None:
        self.default_schema = default_schema

    def parse_text(self, sql_text: str, source_path: str | Path = "<memory>") -> SqlParseResult:
        source = Path(source_path)
        normalized = self._normalize_sql(sql_text)
        object_type, object_name = self._detect_primary_object(sql_text)
        schema_name, short_name = self._split_object_name(object_name)
        references = self._extract_references(sql_text)
        created = tuple(SqlReference(name=short_name, schema=schema_name, kind="created"))
        return SqlParseResult(
            source_path=source,
            object_name=short_name,
            schema_name=schema_name,
            object_type=object_type,
            sql_text=sql_text,
            normalized_sql=normalized,
            referenced_objects=references,
            created_objects=created,
            line_count=sql_text.count("\n") + (1 if sql_text else 0),
        )

    def parse_file(self, path: str | Path) -> SqlParseResult:
        source = Path(path)
        return self.parse_text(source.read_text(encoding="utf-8", errors="ignore"), source_path=source)

    def parse_many(self, paths: Iterable[str | Path]) -> tuple[SqlParseResult, ...]:
        return tuple(self.parse_file(path) for path in paths)

    def summarize(self, results: Sequence[SqlParseResult]) -> SqlParseSummary:
        object_types = tuple(sorted({result.object_type for result in results}, key=lambda item: item.value))
        return SqlParseSummary(total_objects=len(results), object_types=object_types)

    def _detect_primary_object(self, sql_text: str) -> tuple[SqlObjectType, str]:
        for object_type, pattern in self.CREATE_PATTERNS:
            match = pattern.search(sql_text)
            if match:
                return object_type, self._clean_identifier(match.group("name"))
        return SqlObjectType.UNKNOWN, "unknown"

    def _extract_references(self, sql_text: str) -> tuple[SqlReference, ...]:
        references: list[SqlReference] = []
        seen: set[tuple[str | None, str]] = set()
        for match in self.REFERENCE_PATTERN.finditer(sql_text):
            raw_name = self._clean_identifier(match.group("name"))
            schema_name, object_name = self._split_object_name(raw_name)
            key = (schema_name, object_name)
            if key in seen:
                continue
            seen.add(key)
            references.append(SqlReference(name=object_name, schema=schema_name))
        return tuple(references)

    def _normalize_sql(self, sql_text: str) -> str:
        text = sql_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    def _split_object_name(self, qualified_name: str) -> tuple[str | None, str]:
        parts = [part for part in qualified_name.split(".") if part]
        cleaned = [self._clean_identifier(part) for part in parts]
        if len(cleaned) == 1:
            return self.default_schema, cleaned[0]
        if len(cleaned) >= 2:
            return cleaned[-2], cleaned[-1]
        return None, qualified_name

    def _clean_identifier(self, identifier: str) -> str:
        ident = identifier.strip()
        if ident.startswith("[") and ident.endswith("]"):
            ident = ident[1:-1]
        if ident.startswith('"') and ident.endswith('"'):
            ident = ident[1:-1]
        return ident.strip()
