from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from sqlglot import ErrorLevel, exp, parse
from sqlglot.errors import ParseError

from backend.parsers.parser_models import (
    ParsedDocument,
    ParsedObjectType,
    ParserKind,
    ParserReference,
)


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
    kind: str = "read"
    object_type: str = "table_or_view"
    database: str | None = None


@dataclass(frozen=True, slots=True)
class SqlParameter:
    name: str
    data_type: str
    default: str | None = None
    output: bool = False


@dataclass(frozen=True, slots=True)
class SqlObjectDefinition:
    name: str
    schema: str | None
    object_type: SqlObjectType
    operation: str
    parameters: tuple[SqlParameter, ...] = ()
    referenced_objects: tuple[SqlReference, ...] = ()
    dynamic_sql: bool = False
    database: str | None = None


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
    definitions: tuple[SqlObjectDefinition, ...] = ()
    line_count: int = 0

    def to_parsed_document(self) -> ParsedDocument:
        metadata = {
            "schema_name": self.schema_name,
            "object_name": self.object_name,
            "object_type": self.object_type.value,
            "line_count": self.line_count,
            "parser": ParserKind.SQL.value,
            "source_path": str(self.source_path),
            "definitions": [
                {
                    "name": definition.name,
                    "schema_name": definition.schema,
                    "database_name": definition.database,
                    "object_type": definition.object_type.value,
                    "operation": definition.operation,
                    "parameters": [
                        {
                            "name": parameter.name,
                            "data_type": parameter.data_type,
                            "default": parameter.default,
                            "output": parameter.output,
                        }
                        for parameter in definition.parameters
                    ],
                    "dependencies": [
                        _reference_metadata(reference)
                        for reference in definition.referenced_objects
                    ],
                    "dynamic_sql": definition.dynamic_sql,
                }
                for definition in self.definitions
            ],
        }
        references = tuple(
            ParserReference(
                name=reference.name,
                schema=reference.schema,
                kind=f"{reference.kind}_{reference.object_type}",
            )
            for reference in self.referenced_objects
        )
        title = (
            self.object_name
            if self.schema_name is None
            else f"{self.schema_name}.{self.object_name}"
        )
        if len(self.definitions) > 1:
            title = f"SQL script ({len(self.definitions)} objects)"
        return ParsedDocument(
            source_path=self.source_path,
            parser_kind=ParserKind.SQL,
            object_type=ParsedObjectType(self.object_type.value)
            if self.object_type.value in ParsedObjectType._value2member_map_
            else ParsedObjectType.UNKNOWN,
            title=title,
            text=self.normalized_sql,
            metadata=metadata,
            references=references,
            checksum=None,
            language="sql",
            line_count=self.line_count,
            character_count=len(self.normalized_sql),
        )


@dataclass(frozen=True, slots=True)
class SqlParseSummary:
    total_objects: int = 0
    object_types: tuple[SqlObjectType, ...] = ()


_IDENTIFIER = r"(?:\[[^\]]+\]|\"(?:\"\"|[^\"])+\"|[\w$#@]+)"
_OBJECT_PATTERN = re.compile(
    rf"\b(?P<operation>CREATE\s+OR\s+ALTER|CREATE|ALTER)\s+"
    rf"(?P<type>UNIQUE\s+INDEX|INDEX|TABLE|VIEW|PROCEDURE|PROC|FUNCTION|TRIGGER)\s+"
    rf"(?P<name>{_IDENTIFIER}(?:\.{_IDENTIFIER}){{0,3}})",
    re.IGNORECASE | re.MULTILINE,
)
_REFERENCE_PATTERN = re.compile(
    rf"\b(?P<access>MERGE\s+INTO|INSERT\s+INTO|DELETE\s+FROM|UPDATE|FROM|JOIN|"
    rf"EXEC(?:UTE)?|CALL)\s+(?P<name>{_IDENTIFIER}(?:\.{_IDENTIFIER}){{0,3}})",
    re.IGNORECASE | re.MULTILINE,
)
_BATCH_SEPARATOR_PATTERN = re.compile(r"(?im)^[ \t]*GO(?:[ \t]+\d+)?[ \t]*$")


class SqlParser:
    """Parse SQL Server scripts into structured, search-ready metadata."""

    def __init__(self, default_schema: str = "dbo") -> None:
        self.default_schema = default_schema

    def parse_text(self, sql_text: str, source_path: str | Path = "<memory>") -> SqlParseResult:
        source = Path(source_path)
        normalized = self._normalize_sql(sql_text)
        definitions = self._parse_definitions(sql_text)
        if not definitions:
            definitions = self._parse_fallback(sql_text)

        object_name = definitions[0].name if definitions else "unknown"
        schema_name = definitions[0].schema if definitions else None
        object_type = definitions[0].object_type if definitions else SqlObjectType.UNKNOWN
        references = self._unique_references(
            reference
            for definition in definitions
            for reference in definition.referenced_objects
        )
        if not definitions:
            references = self._extract_script_references(sql_text)
        created = tuple(
            SqlReference(
                name=definition.name,
                schema=definition.schema,
                kind="created",
                object_type=definition.object_type.value,
                database=definition.database,
            )
            for definition in definitions
        )
        return SqlParseResult(
            source_path=source,
            object_name=object_name,
            schema_name=schema_name,
            object_type=object_type,
            sql_text=sql_text,
            normalized_sql=normalized,
            referenced_objects=references,
            created_objects=created,
            definitions=definitions,
            line_count=sql_text.count("\n") + (1 if sql_text else 0),
        )

    def parse_file(self, path: str | Path) -> SqlParseResult:
        source = Path(path)
        return self.parse_text(source.read_text(encoding="utf-8", errors="ignore"), source_path=source)

    def parse_many(self, paths: Iterable[str | Path]) -> tuple[SqlParseResult, ...]:
        return tuple(self.parse_file(path) for path in paths)

    def summarize(self, results: Sequence[SqlParseResult]) -> SqlParseSummary:
        object_types = tuple(
            sorted(
                {
                    definition.object_type
                    for result in results
                    for definition in result.definitions
                },
                key=lambda item: item.value,
            )
        )
        total_objects = sum(len(result.definitions) for result in results)
        return SqlParseSummary(total_objects=total_objects, object_types=object_types)

    def _parse_definitions(self, sql_text: str) -> tuple[SqlObjectDefinition, ...]:
        statements: list[exp.Expression] = []
        for batch in self._split_batches(sql_text):
            try:
                statements.extend(
                    statement
                    for statement in parse(batch, read="tsql", error_level=ErrorLevel.RAISE)
                    if statement is not None
                )
            except ParseError:
                return ()
        if any(isinstance(statement, exp.Command) for statement in statements):
            return ()

        definitions: list[SqlObjectDefinition] = []
        for statement in statements:
            if isinstance(statement, (exp.Create, exp.Alter)) and self._definition_target(statement) is None:
                return ()
            object_info = self._definition_target(statement)
            if object_info is None:
                continue
            object_type, target = object_info
            if object_type is SqlObjectType.UNKNOWN:
                continue
            operation = self._operation_for(statement)
            definitions.append(
                SqlObjectDefinition(
                    name=self._identifier_name(target.this),
                    schema=self._identifier_name(target.args.get("db"))
                    or self.default_schema,
                    database=self._identifier_name(target.args.get("catalog")),
                    object_type=object_type,
                    operation=operation,
                    parameters=self._extract_parameters(statement),
                    referenced_objects=self._extract_ast_references(statement, target),
                    dynamic_sql=self._has_dynamic_sql(statement),
                )
            )
        return tuple(definitions)

    def _definition_target(
        self, statement: exp.Expression
    ) -> tuple[SqlObjectType, exp.Table] | None:
        if isinstance(statement, exp.Create):
            target_node = statement.this
            raw_type = str(statement.args.get("kind") or "").upper()
            if isinstance(target_node, exp.StoredProcedure):
                raw_type = "PROCEDURE"
                target_node = target_node.this
        elif isinstance(statement, exp.Alter):
            target_node = statement.this
            raw_type = str(statement.args.get("kind") or "").upper()
        else:
            return None

        if not isinstance(target_node, exp.Table):
            return None
        object_type = {
            "PROC": SqlObjectType.PROCEDURE,
            "PROCEDURE": SqlObjectType.PROCEDURE,
            "TABLE": SqlObjectType.TABLE,
            "VIEW": SqlObjectType.VIEW,
            "FUNCTION": SqlObjectType.FUNCTION,
            "TRIGGER": SqlObjectType.TRIGGER,
            "INDEX": SqlObjectType.INDEX,
        }.get(raw_type, SqlObjectType.UNKNOWN)
        return object_type, target_node

    def _extract_parameters(self, statement: exp.Expression) -> tuple[SqlParameter, ...]:
        procedure: exp.StoredProcedure | None = None
        if isinstance(statement, exp.Create) and isinstance(statement.this, exp.StoredProcedure):
            procedure = statement.this
        if procedure is None:
            return ()

        parameters: list[SqlParameter] = []
        for item in procedure.expressions:
            if not isinstance(item, exp.ColumnDef) or not isinstance(item.this, exp.Parameter):
                continue
            default = item.args.get("default")
            parameters.append(
                SqlParameter(
                    name=item.this.name,
                    data_type=item.kind.sql(dialect="tsql")
                    if item.kind is not None
                    else "unknown",
                    default=default.sql(dialect="tsql") if default is not None else None,
                    output=bool(item.args.get("output")),
                )
            )
        return tuple(parameters)

    def _extract_ast_references(
        self, statement: exp.Expression, target: exp.Table | None
    ) -> tuple[SqlReference, ...]:
        cte_names = {
            cte.alias_or_name.casefold()
            for cte in statement.find_all(exp.CTE)
            if cte.alias_or_name
        }
        write_targets: set[tuple[str | None, str | None, str]] = set()
        execute_targets: set[tuple[str | None, str | None, str]] = set()
        dynamic_subtrees: set[int] = set()
        for node in statement.walk():
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
                table = node.this
                if isinstance(table, exp.Table):
                    write_targets.add(self._table_key(table))
            elif isinstance(node, exp.Execute):
                execute_target = node.this
                if isinstance(execute_target, exp.Table):
                    execute_targets.add(self._table_key(execute_target))
                    if execute_target.name.casefold() == "sp_executesql":
                        dynamic_subtrees.update(id(child) for child in node.walk())
                else:
                    dynamic_subtrees.update(id(child) for child in node.walk())

        target_key = self._table_key(target) if target is not None else None
        references: list[SqlReference] = []
        for table in statement.find_all(exp.Table):
            if (
                id(table) in dynamic_subtrees
                or (target_key is not None and self._table_key(table) == target_key)
            ):
                continue
            if (
                not table.args.get("db")
                and not table.args.get("catalog")
                and table.name.casefold() in cte_names
            ):
                continue
            key = self._table_key(table)
            access = "execute" if key in execute_targets else "write" if key in write_targets else "read"
            references.append(
                SqlReference(
                    name=table.name,
                    schema=self._identifier_name(table.args.get("db")) or self.default_schema,
                    kind=access,
                    object_type="procedure" if access == "execute" else "table_or_view",
                    database=self._identifier_name(table.args.get("catalog")),
                )
            )
        return self._unique_references(references)

    def _has_dynamic_sql(self, statement: exp.Expression) -> bool:
        return any(
            not isinstance(execute.this, exp.Table)
            or (
                isinstance(execute.this, exp.Table)
                and execute.this.name.casefold() == "sp_executesql"
            )
            for execute in statement.find_all(exp.Execute)
        )

    def _parse_fallback(self, sql_text: str) -> tuple[SqlObjectDefinition, ...]:
        masked = self._mask_sql(sql_text, mask_literals=True)
        matches = tuple(_OBJECT_PATTERN.finditer(masked))
        if not matches:
            return ()
        definitions: list[SqlObjectDefinition] = []
        for index, match in enumerate(matches):
            object_type = self._object_type(match.group("type"))
            database, schema, name = self._split_object_name(match.group("name"))
            statement_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(masked)
            )
            statement = masked[match.start():statement_end]
            definitions.append(
                SqlObjectDefinition(
                    name=name,
                    schema=schema,
                    database=database,
                    object_type=object_type,
                    operation=" ".join(match.group("operation").upper().split()),
                    parameters=self._extract_fallback_parameters(
                        sql_text, masked, match, statement_end
                    ),
                    referenced_objects=self._extract_fallback_references(statement),
                    dynamic_sql=bool(
                        re.search(r"\bEXEC(?:UTE)?\s*\(", statement, re.IGNORECASE)
                        or re.search(r"\bSP_EXECUTESQL\b", statement, re.IGNORECASE)
                    ),
                )
            )
        return tuple(definitions)

    def _extract_fallback_parameters(
        self,
        sql_text: str,
        masked_sql: str,
        definition_match: re.Match[str],
        statement_end: int,
    ) -> tuple[SqlParameter, ...]:
        if self._object_type(definition_match.group("type")) is not SqlObjectType.PROCEDURE:
            return ()
        header_end = re.search(
            r"\bAS\b", masked_sql[definition_match.end():statement_end], re.IGNORECASE
        )
        if header_end is None:
            return ()
        parameter_text = sql_text[
            definition_match.end():definition_match.end() + header_end.start()
        ]
        synthetic = (
            f"CREATE PROCEDURE {definition_match.group('name')} "
            f"{parameter_text} AS SELECT 1"
        )
        try:
            parsed = parse(synthetic, read="tsql", error_level=ErrorLevel.RAISE)
        except ParseError:
            return ()
        procedure = next(
            (
                statement.this
                for statement in parsed
                if isinstance(statement, exp.Create)
                and isinstance(statement.this, exp.StoredProcedure)
            ),
            None,
        )
        if procedure is None:
            return ()
        return self._extract_parameters(
            exp.Create(this=procedure, kind="PROCEDURE")
        )

    def _extract_fallback_references(self, masked_sql: str) -> tuple[SqlReference, ...]:
        references: list[SqlReference] = []
        for match in _REFERENCE_PATTERN.finditer(masked_sql):
            raw_access = " ".join(match.group("access").upper().split())
            access = (
                "execute"
                if raw_access.startswith(("EXEC", "CALL"))
                else "write"
                if raw_access.startswith(("UPDATE", "INSERT", "DELETE", "MERGE"))
                else "read"
            )
            database, schema, name = self._split_object_name(match.group("name"))
            references.append(
                SqlReference(
                    name=name,
                    schema=schema,
                    kind=access,
                    object_type="procedure" if access == "execute" else "table_or_view",
                    database=database,
                )
            )
        return self._unique_references(references)

    def _split_batches(self, sql_text: str) -> tuple[str, ...]:
        masked_sql = self._mask_sql(sql_text, mask_literals=True)
        boundaries = [match.start() for match in _BATCH_SEPARATOR_PATTERN.finditer(masked_sql)]
        if not boundaries:
            return (sql_text,)
        batches: list[str] = []
        start = 0
        for boundary in boundaries:
            batch = sql_text[start:boundary]
            if batch.strip():
                batches.append(batch)
            separator_end = masked_sql.find("\n", boundary)
            start = len(sql_text) if separator_end == -1 else separator_end + 1
        if sql_text[start:].strip():
            batches.append(sql_text[start:])
        return tuple(batches)

    def _mask_sql(self, sql_text: str, *, mask_literals: bool) -> str:
        chars = list(sql_text)
        index = 0
        state = "normal"
        block_depth = 0
        while index < len(chars):
            current = chars[index]
            next_char = chars[index + 1] if index + 1 < len(chars) else ""
            if state == "normal":
                if current == "-" and next_char == "-":
                    state = "line_comment"
                    chars[index] = chars[index + 1] = " "
                    index += 2
                    continue
                if current == "/" and next_char == "*":
                    state = "block_comment"
                    block_depth = 1
                    chars[index] = chars[index + 1] = " "
                    index += 2
                    continue
                if current == "'" and mask_literals:
                    state = "string"
                    chars[index] = " "
                elif current == "'":
                    state = "string_unmasked"
                elif current == '"':
                    state = "double_quote"
                elif current == "[":
                    state = "bracket"
            elif state in {"line_comment", "block_comment"}:
                if current not in "\r\n":
                    chars[index] = " "
                if state == "line_comment" and current in "\r\n":
                    state = "normal"
                elif state == "block_comment":
                    if current == "/" and next_char == "*":
                        chars[index] = chars[index + 1] = " "
                        block_depth += 1
                        index += 2
                        continue
                    if current == "*" and next_char == "/":
                        chars[index] = chars[index + 1] = " "
                        block_depth -= 1
                        index += 2
                        if block_depth == 0:
                            state = "normal"
                        continue
            elif state in {"string", "string_unmasked"}:
                if state == "string" and current not in "\r\n":
                    chars[index] = " "
                if current == "'" and next_char == "'":
                    if state == "string":
                        chars[index + 1] = " "
                    index += 2
                    continue
                if current == "'":
                    state = "normal"
            elif state == "double_quote":
                if current == '"' and next_char == '"':
                    index += 2
                    continue
                if current == '"':
                    state = "normal"
            elif state == "bracket":
                if current == "]" and next_char == "]":
                    index += 2
                    continue
                if current == "]":
                    state = "normal"
            index += 1
        return "".join(chars)

    def _operation_for(self, statement: exp.Expression) -> str:
        if isinstance(statement, exp.Alter):
            return "ALTER"
        if isinstance(statement, exp.Create) and statement.args.get("replace"):
            return "CREATE OR ALTER"
        return "CREATE"

    def _object_type(self, value: str) -> SqlObjectType:
        return {
            "PROC": SqlObjectType.PROCEDURE,
            "PROCEDURE": SqlObjectType.PROCEDURE,
            "TABLE": SqlObjectType.TABLE,
            "VIEW": SqlObjectType.VIEW,
            "FUNCTION": SqlObjectType.FUNCTION,
            "TRIGGER": SqlObjectType.TRIGGER,
            "INDEX": SqlObjectType.INDEX,
            "UNIQUE INDEX": SqlObjectType.INDEX,
        }.get(value.upper(), SqlObjectType.UNKNOWN)

    def _split_object_name(self, qualified_name: str) -> tuple[str | None, str | None, str]:
        parts = [
            self._clean_identifier(part)
            for part in re.findall(
                r'\[[^\]]*(?:\]\][^\]]*)*\]|"(?:[^"]|"")*"|[^.]+',
                qualified_name,
            )
            if part
        ]
        if len(parts) == 1:
            return None, self.default_schema, parts[0]
        if len(parts) == 2:
            return None, parts[0], parts[1]
        if len(parts) >= 3:
            return parts[-3], parts[-2], parts[-1]
        return None, self.default_schema, qualified_name

    def _identifier_name(self, identifier: exp.Expression | None) -> str | None:
        if identifier is None:
            return None
        return str(getattr(identifier, "name", None) or identifier.this or "").strip() or None

    def _table_key(self, table: exp.Table) -> tuple[str | None, str | None, str]:
        return (
            self._identifier_name(table.args.get("catalog")).casefold()
            if self._identifier_name(table.args.get("catalog"))
            else None,
            self._identifier_name(table.args.get("db")).casefold()
            if self._identifier_name(table.args.get("db"))
            else None,
            table.name.casefold(),
        )

    def _unique_references(self, references: Iterable[SqlReference]) -> tuple[SqlReference, ...]:
        unique: dict[tuple[str | None, str | None, str, str, str], SqlReference] = {}
        for reference in references:
            key = (
                reference.database.casefold() if reference.database else None,
                reference.schema.casefold() if reference.schema else None,
                reference.name.casefold(),
                reference.kind,
                reference.object_type,
            )
            unique.setdefault(key, reference)
        return tuple(unique.values())

    def _extract_script_references(self, sql_text: str) -> tuple[SqlReference, ...]:
        statements: list[exp.Expression] = []
        try:
            for batch in self._split_batches(sql_text):
                statements.extend(
                    statement
                    for statement in parse(batch, read="tsql", error_level=ErrorLevel.RAISE)
                    if statement is not None
                )
        except ParseError:
            return self._extract_fallback_references(
                self._mask_sql(sql_text, mask_literals=True)
            )
        if any(isinstance(statement, exp.Command) for statement in statements):
            return self._extract_fallback_references(
                self._mask_sql(sql_text, mask_literals=True)
            )
        return self._unique_references(
            reference
            for statement in statements
            for reference in self._extract_ast_references(statement, None)
        )

    def _normalize_sql(self, sql_text: str) -> str:
        text = sql_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    def _clean_identifier(self, identifier: str) -> str:
        ident = identifier.strip()
        if ident.startswith("[") and ident.endswith("]"):
            ident = ident[1:-1].replace("]]", "]")
        if ident.startswith('"') and ident.endswith('"'):
            ident = ident[1:-1].replace('""', '"')
        return ident.strip()


def _reference_metadata(reference: SqlReference) -> dict[str, str | None]:
    return {
        "database": reference.database,
        "schema": reference.schema,
        "name": reference.name,
        "access": reference.kind,
        "object_type": reference.object_type,
    }
