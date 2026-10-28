from __future__ import annotations

import ast
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml
from sqlglot import ErrorLevel, exp, parse
from sqlglot.errors import ParseError

from backend.graph.models import EntityMention, GraphEntityType, normalize_entity_name
from backend.parsers.parser_models import ParsedDocument, ParserKind


_TECHNOLOGIES = (
    "SQL Server",
    "Microsoft SQL Server",
    "SQLSERVER",
    "Qdrant",
    "Ollama",
    "FastAPI",
    "Python",
    "Delphi",
    "PANTHEON",
    "Open WebUI",
    "Docker",
    "Tesseract",
    "SQLGlot",
    "PostgreSQL",
    "MySQL",
    "SQLite",
    "React",
    "Vue",
    "Angular",
    ".NET",
    "ASP.NET",
    "Windows",
    "Linux",
)
_TECHNOLOGY_LOOKUP = {
    "sql server": "SQL Server",
    "microsoft sql server": "SQL Server",
    "sqlserver": "SQL Server",
}
_COUNTRIES = (
    "Croatia",
    "Hrvatska",
    "Slovenia",
    "Slovenija",
    "Germany",
    "Njemačka",
    "Austria",
    "Austrija",
    "Italy",
    "Italija",
    "Serbia",
    "Srbija",
    "Bosnia and Herzegovina",
    "Bosna i Hercegovina",
    "United States",
    "United Kingdom",
)
_LOCATIONS = (
    "Zagreb",
    "Split",
    "Rijeka",
    "Osijek",
    "Zadar",
    "Pula",
    "Dubrovnik",
    "Varaždin",
    "Ljubljana",
    "Maribor",
    "Berlin",
    "Munich",
    "München",
    "Vienna",
    "Wien",
)
_PERSON_PATTERN = re.compile(
    r"(?i:\b(?:mr|mrs|ms|miss|dr|prof)\.?[ \t]+)"
    r"(?P<name>[A-ZČĆĐŠŽ][\w'-]*(?:[ \t]+[A-ZČĆĐŠŽ][\w'-]*){0,2})"
)
_LABELED_PERSON_PATTERN = re.compile(
    r"(?i:\b(?:author|created by|owner|contact|responsible|employee|"
    r"autor|kontakt|odgovorna osoba)[ \t]*[:=][ \t]*)"
    r"(?P<name>[A-ZČĆĐŠŽ][\w'-]+(?:[ \t]+[A-ZČĆĐŠŽ][\w'-]+){1,2})"
)
_LABELED_PROJECT_PATTERN = re.compile(
    r"(?i:\b(?:project|project name|projekt)[ \t]*[:=][ \t]*)"
    r"(?P<name>[A-ZČĆĐŠŽ][\w.-]*(?:[ \t]+[A-ZČĆĐŠŽ][\w.-]*){0,3})"
)
_LABELED_PRODUCT_PATTERN = re.compile(
    r"(?i:\b(?:product|proizvod)[ \t]*[:=][ \t]*)"
    r"(?P<name>[A-ZČĆĐŠŽ][\w.-]*(?:[ \t]+[A-ZČĆĐŠŽ][\w.-]*){0,3})"
)
_BUSINESS_PATTERNS = (
    (GraphEntityType.INVOICE, re.compile(r"\b(?:invoice|e-?račun|racun)\b", re.I)),
    (GraphEntityType.ORDER, re.compile(r"\b(?:order|narudžb\w*|narudzb\w*)\b", re.I)),
    (GraphEntityType.CUSTOMER, re.compile(r"\b(?:customer|kupac|korisnik)\b", re.I)),
    (GraphEntityType.SUPPLIER, re.compile(r"\b(?:supplier|dobavljač|dobavljac)\b", re.I)),
    (GraphEntityType.PRODUCT, re.compile(r"\b(?:product|proizvod)\b", re.I)),
)
_ENDPOINT_PATTERN = re.compile(
    r"(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>/[A-Za-z0-9_{}./:-]+)",
    re.IGNORECASE,
)
_VERSION_PATTERN = re.compile(r"\bv?\d+(?:\.\d+){1,3}\b", re.IGNORECASE)
_COMPANY_PATTERN = re.compile(
    r"\b[A-ZČĆĐŠŽ][\w&.-]*(?:\s+[A-ZČĆĐŠŽ][\w&.-]*){0,3}\s+"
    r"(?:d\.?\s*o\.?\s*o\.?|d\.?\s*d\.?|ltd\.?|inc\.?|llc|gmbh)\b",
    re.IGNORECASE,
)
_CODE_OBJECT_PATTERN = re.compile(
    r"\b(?:p|v|f|tr|fn|sp|tbl|vw)[A-Z][A-Za-z0-9_]*\b"
)
_ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_SQL_KEYWORDS = {
    "ADD", "ALL", "ALTER", "AND", "AS", "ASC", "BEGIN", "BETWEEN", "BY",
    "CASE", "CAST", "CHECK", "COLUMN", "COMMIT", "CONSTRAINT", "CREATE",
    "CROSS", "CURRENT", "DATABASE", "DECLARE", "DEFAULT", "DELETE", "DESC",
    "DISTINCT", "DROP", "ELSE", "END", "EXEC", "EXECUTE", "EXISTS", "FETCH",
    "FROM", "FULL", "FUNCTION", "GO", "GROUP", "HAVING", "IF", "IN",
    "INDEX", "INNER", "INSERT", "INTO", "IS", "JOIN", "KEY", "LEFT", "LIKE",
    "MERGE", "NOT", "NULL", "OF", "ON", "OR", "ORDER", "OUTER", "PROCEDURE",
    "REFERENCES", "RETURN", "RETURNS", "RIGHT", "ROLLBACK", "SCHEMA", "SELECT",
    "SET", "TABLE", "THEN", "TOP", "TRIGGER", "UNION", "UNIQUE", "UPDATE",
    "USE", "VALUES", "VIEW", "WHEN", "WHERE", "WITH",
}


class EntityExtractionService:
    """Extract normalized, provenance-ready entities from parsed documents."""

    def extract(self, document: ParsedDocument) -> tuple[EntityMention, ...]:
        mentions: list[EntityMention] = [
            EntityMention(
                name=document.title or Path(document.source_path).name,
                entity_type=GraphEntityType.DOCUMENT,
                confidence=1.0,
                properties={
                    "source_path": str(document.source_path),
                    "parser_kind": document.parser_kind.value,
                },
            )
        ]
        if document.parser_kind is ParserKind.SQL:
            mentions.extend(self._extract_sql(document))
        elif document.parser_kind is ParserKind.DELPHI:
            mentions.extend(self._extract_delphi(document))
        elif document.parser_kind is ParserKind.PDF:
            mentions.extend(self._extract_prose(document.text))
        elif document.parser_kind is ParserKind.WORD:
            mentions.extend(self._extract_prose(document.text))
        elif document.parser_kind is ParserKind.MARKDOWN:
            mentions.extend(self._extract_prose(document.text))
        else:
            mentions.extend(self._extract_language_or_structured(document))
            mentions.extend(self._extract_prose(document.text))

        deduplicated: dict[tuple[str, GraphEntityType], EntityMention] = {}
        for mention in mentions:
            key = (normalize_entity_name(mention.name), mention.entity_type)
            existing = deduplicated.get(key)
            if existing is None or mention.confidence > existing.confidence:
                deduplicated[key] = mention
        return tuple(deduplicated.values())

    def _extract_sql(self, document: ParsedDocument) -> list[EntityMention]:
        mentions: list[EntityMention] = []
        definitions = document.metadata.get("definitions", [])
        if isinstance(definitions, list):
            for definition in definitions:
                if not isinstance(definition, dict):
                    continue
                entity_type = self._entity_type(str(definition.get("object_type", "")))
                name = self._qualified_name(
                    definition.get("schema_name"),
                    definition.get("name"),
                    definition.get("database_name"),
                )
                if name:
                    mentions.append(
                        EntityMention(name, entity_type, 0.99, evidence="SQL definition")
                    )
                dependencies = definition.get("dependencies", [])
                if isinstance(dependencies, list):
                    for dependency in dependencies:
                        if not isinstance(dependency, dict):
                            continue
                        dep_name = self._qualified_name(
                            dependency.get("schema"),
                            dependency.get("name"),
                            dependency.get("database"),
                        )
                        if dep_name:
                            mentions.append(
                                EntityMention(
                                    dep_name,
                                    self._entity_type(str(dependency.get("object_type", ""))),
                                    0.96,
                                    evidence="SQL dependency",
                                )
                            )
                parameters = definition.get("parameters", [])
                if isinstance(parameters, list):
                    for parameter in parameters:
                        if isinstance(parameter, dict) and parameter.get("name"):
                            mentions.append(
                                EntityMention(
                                    str(parameter["name"]),
                                    GraphEntityType.COLUMN,
                                    0.9,
                                    properties={
                                        "data_type": str(parameter.get("data_type", ""))
                                    },
                                    evidence="SQL procedure parameter",
                                )
                            )

        if not isinstance(definitions, list) or not definitions:
            for reference in document.references:
                entity_type = self._reference_entity_type(reference.kind)
                mentions.append(
                    EntityMention(
                        self._qualified_name(reference.schema, reference.name),
                        entity_type,
                        0.92,
                        evidence=f"SQL {reference.kind}",
                    )
                )
        try:
            statements = [
                statement
                for statement in parse(
                    document.text, read="tsql", error_level=ErrorLevel.RAISE
                )
                if statement is not None
            ]
        except ParseError:
            statements = []
        seen_columns: set[str] = set()
        for statement in statements:
            for column_definition in statement.find_all(exp.ColumnDef):
                if isinstance(column_definition.this, exp.Parameter):
                    continue
                name = column_definition.this.name
                normalized = normalize_entity_name(name)
                if normalized and normalized not in seen_columns:
                    seen_columns.add(normalized)
                    mentions.append(
                        EntityMention(
                            name,
                            GraphEntityType.COLUMN,
                            0.88,
                            properties={
                                "data_type": column_definition.kind.sql(dialect="tsql")
                                if column_definition.kind
                                else "unknown"
                            },
                            evidence="SQL column definition",
                        )
                    )
            for column in statement.find_all(exp.Column):
                name = column.name
                normalized = normalize_entity_name(name)
                if normalized and normalized not in seen_columns:
                    seen_columns.add(normalized)
                    mentions.append(
                        EntityMention(
                            name,
                            GraphEntityType.COLUMN,
                            0.84,
                            evidence="SQL column reference",
                        )
                    )
        mentions.extend(
            self._extract_prose(document.text, excluded_names=seen_columns)
        )
        return mentions

    def _extract_delphi(self, document: ParsedDocument) -> list[EntityMention]:
        mentions = [
            EntityMention(
                str(document.metadata.get("unit_name") or document.title),
                GraphEntityType.MODULE,
                0.98,
                evidence="Delphi unit",
            )
        ]
        for match in re.finditer(
            r"\b(?:procedure|function|constructor|destructor)\s+"
            r"(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
            document.text,
            re.IGNORECASE,
        ):
            mentions.append(
                EntityMention(match.group("name"), GraphEntityType.METHOD, 0.9)
            )
        for match in re.finditer(
            r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*class\b",
            document.text,
            re.IGNORECASE,
        ):
            mentions.append(
                EntityMention(match.group("name"), GraphEntityType.CLASS, 0.95)
            )
        uses = re.search(r"\buses\s+(?P<names>[^;]+);", document.text, re.I)
        if uses:
            for unit in uses.group("names").split(","):
                name = re.split(r"\s+in\s+", unit, maxsplit=1, flags=re.I)[0].strip()
                if name:
                    mentions.append(
                        EntityMention(name, GraphEntityType.MODULE, 0.9)
                    )
        return mentions

    def _extract_language_or_structured(
        self, document: ParsedDocument
    ) -> list[EntityMention]:
        suffix = Path(document.source_path).suffix.casefold()
        if suffix == ".py":
            return self._extract_python(document.text, Path(document.source_path).stem)
        if suffix in {".json", ".yaml", ".yml"} or document.title.casefold().endswith(
            (".swagger", ".openapi")
        ):
            return self._extract_swagger_or_json(document.text)
        if suffix == ".xml":
            return self._extract_xml(document.text)
        if document.title.casefold().endswith((".yaml", ".yml")):
            return self._extract_swagger_or_json(document.text)
        return []

    def _extract_python(self, text: str, module_name: str) -> list[EntityMention]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        mentions = [EntityMention(module_name, GraphEntityType.MODULE, 0.95)]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mentions.extend(
                    EntityMention(alias.name, GraphEntityType.LIBRARY, 0.98)
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                mentions.append(
                    EntityMention(node.module, GraphEntityType.LIBRARY, 0.98)
                )
            elif isinstance(node, ast.ClassDef):
                mentions.append(EntityMention(node.name, GraphEntityType.CLASS, 0.99))
                for base in node.bases:
                    base_name = self._ast_name(base)
                    if base_name:
                        mentions.append(
                            EntityMention(base_name, GraphEntityType.CLASS, 0.9)
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mentions.append(EntityMention(node.name, GraphEntityType.METHOD, 0.98))
        return mentions

    def _extract_swagger_or_json(self, text: str) -> list[EntityMention]:
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            try:
                value = yaml.safe_load(text)
            except yaml.YAMLError:
                return []
        mentions: list[EntityMention] = []
        if not isinstance(value, dict):
            return mentions
        paths = value.get("paths")
        if isinstance(paths, dict):
            for path, operations in paths.items():
                if not isinstance(operations, dict):
                    continue
                for method, operation in operations.items():
                    if method.casefold() not in {
                        "get",
                        "post",
                        "put",
                        "patch",
                        "delete",
                        "options",
                        "head",
                    }:
                        continue
                    endpoint = f"{method.upper()} {path}"
                    mentions.append(
                        EntityMention(endpoint, GraphEntityType.ENDPOINT, 0.99)
                    )
                    if isinstance(operation, dict):
                        operation_id = operation.get("operationId")
                        if operation_id:
                            mentions.append(
                                EntityMention(
                                    str(operation_id), GraphEntityType.METHOD, 0.94
                                )
                            )
        components = value.get("components")
        schemas = components.get("schemas") if isinstance(components, dict) else None
        if isinstance(schemas, dict):
            mentions.extend(
                EntityMention(str(name), GraphEntityType.ERP_OBJECT, 0.95)
                for name in schemas
            )
        definitions = value.get("definitions")
        if isinstance(definitions, dict):
            mentions.extend(
                EntityMention(str(name), GraphEntityType.ERP_OBJECT, 0.92)
                for name in definitions
            )
        info = value.get("info")
        if isinstance(info, dict):
            for key, entity_type in (
                ("title", GraphEntityType.PROJECT),
                ("version", GraphEntityType.VERSION),
            ):
                if info.get(key):
                    mentions.append(
                        EntityMention(str(info[key]), entity_type, 0.97)
                    )
        return mentions

    def _extract_xml(self, text: str) -> list[EntityMention]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        names = {element.tag.rsplit("}", maxsplit=1)[-1] for element in root.iter()}
        return [
            EntityMention(name, GraphEntityType.ERP_OBJECT, 0.75)
            for name in sorted(names)
            if name and name != root.tag.rsplit("}", maxsplit=1)[-1]
        ]

    def _extract_prose(
        self, text: str, *, excluded_names: set[str] | None = None
    ) -> list[EntityMention]:
        excluded = excluded_names or set()
        mentions: list[EntityMention] = []
        for canonical in _TECHNOLOGIES:
            pattern = re.compile(rf"(?<!\w){re.escape(canonical)}(?!\w)", re.I)
            if pattern.search(text):
                normalized = normalize_entity_name(canonical)
                canonical_name = _TECHNOLOGY_LOOKUP.get(
                    normalize_entity_name(canonical), canonical
                )
                entity_type = (
                    GraphEntityType.LANGUAGE
                    if canonical in {"Python", "Delphi"}
                    else GraphEntityType.TECHNOLOGY
                )
                mentions.append(
                    EntityMention(
                        canonical_name,
                        entity_type,
                        0.94,
                        aliases=(
                            ("SQLSERVER", "Microsoft SQL Server")
                            if normalized == "sql server"
                            else ()
                        ),
                    )
                )
        for country in _COUNTRIES:
            if re.search(rf"(?<!\w){re.escape(country)}(?!\w)", text, re.I):
                mentions.append(
                    EntityMention(country, GraphEntityType.COUNTRY, 0.88)
                )
        for location in _LOCATIONS:
            if re.search(rf"(?<!\w){re.escape(location)}(?!\w)", text):
                mentions.append(
                    EntityMention(location, GraphEntityType.LOCATION, 0.84)
                )
        for pattern in (_PERSON_PATTERN, _LABELED_PERSON_PATTERN):
            mentions.extend(
                EntityMention(match.group("name"), GraphEntityType.PERSON, 0.78)
                for match in pattern.finditer(text)
            )
        for pattern, entity_type in (
            (_LABELED_PROJECT_PATTERN, GraphEntityType.PROJECT),
            (_LABELED_PRODUCT_PATTERN, GraphEntityType.PRODUCT),
        ):
            mentions.extend(
                EntityMention(match.group("name"), entity_type, 0.8)
                for match in pattern.finditer(text)
            )
        for entity_type, pattern in _BUSINESS_PATTERNS:
            for match in pattern.finditer(text):
                mentions.append(
                    EntityMention(
                        match.group(0),
                        entity_type,
                        0.62,
                        evidence=match.group(0),
                    )
                )
        for match in _COMPANY_PATTERN.finditer(text):
            mentions.append(
                EntityMention(match.group(0), GraphEntityType.COMPANY, 0.83)
            )
        for match in _ENDPOINT_PATTERN.finditer(text):
            mentions.append(
                EntityMention(
                    f"{match.group('method').upper()} {match.group('path')}",
                    GraphEntityType.ENDPOINT,
                    0.9,
                )
            )
        for match in _VERSION_PATTERN.finditer(text):
            mentions.append(
                EntityMention(match.group(), GraphEntityType.VERSION, 0.7)
            )
        for match in _CODE_OBJECT_PATTERN.finditer(text):
            mentions.append(
                EntityMention(match.group(), GraphEntityType.ERP_OBJECT, 0.74)
            )
        for match in _ACRONYM_PATTERN.finditer(text):
            if (
                match.group() not in _SQL_KEYWORDS
                and normalize_entity_name(match.group()) not in excluded
            ):
                mentions.append(
                    EntityMention(match.group(), GraphEntityType.ERP_OBJECT, 0.68)
                )
        return mentions

    def _qualified_name(self, schema: Any, name: Any, database: Any = None) -> str:
        clean_name = str(name or "").strip()
        clean_schema = str(schema or "").strip()
        clean_database = str(database or "").strip()
        parts = [part for part in (clean_database, clean_schema, clean_name) if part]
        return ".".join(parts)

    def _entity_type(self, value: str) -> GraphEntityType:
        normalized = value.casefold()
        return {
            "table": GraphEntityType.TABLE,
            "table_or_view": GraphEntityType.TABLE,
            "view": GraphEntityType.VIEW,
            "procedure": GraphEntityType.PROCEDURE,
            "function": GraphEntityType.FUNCTION,
            "trigger": GraphEntityType.TRIGGER,
            "endpoint": GraphEntityType.ENDPOINT,
            "class": GraphEntityType.CLASS,
            "method": GraphEntityType.METHOD,
            "module": GraphEntityType.MODULE,
            "library": GraphEntityType.LIBRARY,
        }.get(normalized, GraphEntityType.ERP_OBJECT if normalized else GraphEntityType.UNKNOWN)

    def _reference_entity_type(self, kind: str) -> GraphEntityType:
        lowered = kind.casefold()
        for name, entity_type in (
            ("procedure", GraphEntityType.PROCEDURE),
            ("view", GraphEntityType.VIEW),
            ("table", GraphEntityType.TABLE),
            ("function", GraphEntityType.FUNCTION),
            ("trigger", GraphEntityType.TRIGGER),
            ("endpoint", GraphEntityType.ENDPOINT),
            ("url", GraphEntityType.ENDPOINT),
        ):
            if name in lowered:
                return entity_type
        return GraphEntityType.UNKNOWN

    def _ast_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self._ast_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None