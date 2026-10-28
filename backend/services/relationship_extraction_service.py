from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from backend.graph.models import (
    EntityMention,
    GraphEntityType,
    GraphRelationshipType,
    RelationshipMention,
    normalize_entity_name,
)
from backend.parsers.parser_models import ParsedDocument, ParserKind


class RelationshipExtractionService:
    """Derive confidence-scored edges from parser structure and source syntax."""

    def extract(
        self,
        document: ParsedDocument,
        entities: Iterable[EntityMention] = (),
    ) -> tuple[RelationshipMention, ...]:
        entity_list = tuple(entities)
        document_name = document.title or Path(document.source_path).name
        relationships: list[RelationshipMention] = []
        if document.parser_kind is ParserKind.SQL:
            relationships.extend(self._extract_sql(document))
        elif document.parser_kind is ParserKind.DELPHI:
            relationships.extend(self._extract_delphi(document, document_name))
        elif Path(document.source_path).suffix.casefold() == ".py":
            relationships.extend(
                self._extract_python(document.text, Path(document.source_path).stem)
            )
        elif Path(document.source_path).suffix.casefold() in {".json", ".yaml", ".yml"}:
            relationships.extend(self._extract_swagger(document.text))

        for entity in entity_list:
            if entity.entity_type is GraphEntityType.DOCUMENT:
                continue
            relationships.append(
                RelationshipMention(
                    source_name=document_name,
                    target_name=entity.name,
                    relationship_type=GraphRelationshipType.MENTIONS,
                    confidence=max(0.5, entity.confidence),
                    source_type=GraphEntityType.DOCUMENT,
                    target_type=entity.entity_type,
                    evidence=entity.evidence,
                )
            )
        return self._deduplicate(relationships)

    def _extract_sql(self, document: ParsedDocument) -> list[RelationshipMention]:
        relationships: list[RelationshipMention] = []
        definitions = document.metadata.get("definitions", [])
        if not isinstance(definitions, list):
            return relationships
        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            source_type = self._entity_type(str(definition.get("object_type", "")))
            source_name = self._qualified_name(
                definition.get("schema_name"),
                definition.get("name"),
                definition.get("database_name"),
            )
            if not source_name:
                continue
            for parameter in definition.get("parameters", []):
                if isinstance(parameter, dict) and parameter.get("name"):
                    relationships.append(
                        RelationshipMention(
                            source_name=source_name,
                            target_name=str(parameter["name"]),
                            relationship_type=GraphRelationshipType.PARAMETER,
                            confidence=0.94,
                            source_type=source_type,
                            target_type=GraphEntityType.COLUMN,
                            evidence=f"Parameter {parameter['name']}",
                        )
                    )
            for dependency in definition.get("dependencies", []):
                if not isinstance(dependency, dict):
                    continue
                target_name = self._qualified_name(
                    dependency.get("schema"),
                    dependency.get("name"),
                    dependency.get("database"),
                )
                access = str(dependency.get("access", "read")).casefold()
                relation_type = {
                    "read": GraphRelationshipType.READS_FROM,
                    "write": GraphRelationshipType.WRITES_TO,
                    "execute": GraphRelationshipType.CALLS,
                }.get(access, GraphRelationshipType.REFERENCES)
                relationships.append(
                    RelationshipMention(
                        source_name=source_name,
                        target_name=target_name,
                        relationship_type=relation_type,
                        confidence=0.98 if access in {"read", "write", "execute"} else 0.75,
                        source_type=source_type,
                        target_type=self._entity_type(
                            str(dependency.get("object_type", ""))
                        ),
                        evidence=f"SQL {access} dependency",
                        metadata={"database": dependency.get("database")},
                    )
                )
        return relationships

    def _extract_python(self, text: str, module_name: str) -> list[RelationshipMention]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        relationships: list[RelationshipMention] = []
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        local_functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    relationships.append(
                        RelationshipMention(
                            module_name,
                            alias.name,
                            GraphRelationshipType.USES,
                            0.98,
                            GraphEntityType.MODULE,
                            GraphEntityType.LIBRARY,
                            evidence=f"import {alias.name}",
                        )
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                relationships.append(
                    RelationshipMention(
                        module_name,
                        node.module,
                        GraphRelationshipType.USES,
                        0.98,
                        GraphEntityType.MODULE,
                        GraphEntityType.LIBRARY,
                        evidence=f"from {node.module} import",
                    )
                )
            elif isinstance(node, ast.ClassDef):
                relationships.append(
                    RelationshipMention(
                        module_name,
                        node.name,
                        GraphRelationshipType.CONTAINS,
                        0.96,
                        GraphEntityType.MODULE,
                        GraphEntityType.CLASS,
                    )
                )
                for base in node.bases:
                    base_name = self._ast_name(base)
                    if base_name:
                        relationships.append(
                            RelationshipMention(
                                node.name,
                                base_name,
                                GraphRelationshipType.EXTENDS,
                                0.9,
                                GraphEntityType.CLASS,
                                GraphEntityType.CLASS,
                                evidence=f"class {node.name}",
                            )
                        )
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        relationships.append(
                            RelationshipMention(
                                node.name,
                                member.name,
                                GraphRelationshipType.CONTAINS,
                                0.98,
                                GraphEntityType.CLASS,
                                GraphEntityType.METHOD,
                            )
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if isinstance(parents.get(node), ast.Module):
                    relationships.append(
                        RelationshipMention(
                            module_name,
                            node.name,
                            GraphRelationshipType.CONTAINS,
                            0.96,
                            GraphEntityType.MODULE,
                            GraphEntityType.METHOD,
                        )
                    )
                parameters = [
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                ]
                if node.args.vararg is not None:
                    parameters.append(node.args.vararg)
                if node.args.kwarg is not None:
                    parameters.append(node.args.kwarg)
                for parameter in parameters:
                    if parameter.arg not in {"self", "cls"}:
                        relationships.append(
                            RelationshipMention(
                                node.name,
                                parameter.arg,
                                GraphRelationshipType.PARAMETER,
                                0.9,
                                GraphEntityType.METHOD,
                                GraphEntityType.COLUMN,
                            )
                        )
                if node.returns is not None:
                    return_name = self._ast_name(node.returns)
                    if return_name:
                        relationships.append(
                            RelationshipMention(
                                node.name,
                                return_name,
                                GraphRelationshipType.RETURNS,
                                0.9,
                                GraphEntityType.METHOD,
                                GraphEntityType.UNKNOWN,
                            )
                        )
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        call_name = self._ast_name(child.func)
                        if call_name and call_name.split(".")[-1] in local_functions:
                            relationships.append(
                                RelationshipMention(
                                    node.name,
                                    call_name,
                                    GraphRelationshipType.CALLS,
                                    0.88,
                                    GraphEntityType.METHOD,
                                    GraphEntityType.METHOD,
                                    evidence=f"call in {node.name}",
                                )
                            )
        return relationships

    def _extract_delphi(
        self, document: ParsedDocument, document_name: str
    ) -> list[RelationshipMention]:
        unit = str(document.metadata.get("unit_name") or document_name)
        relationships: list[RelationshipMention] = []
        uses = re.search(r"\buses\s+(?P<names>[^;]+);", document.text, re.I)
        if uses:
            for raw_name in uses.group("names").split(","):
                name = re.split(
                    r"\s+in\s+", raw_name, maxsplit=1, flags=re.I
                )[0].strip()
                if name:
                    relationships.append(
                        RelationshipMention(
                            unit,
                            name,
                            GraphRelationshipType.USES,
                            0.94,
                            GraphEntityType.MODULE,
                            GraphEntityType.MODULE,
                            evidence="Delphi uses clause",
                        )
                    )
        for match in re.finditer(
            r"\b(?P<class>[A-Za-z_]\w*)\s*=\s*class\b", document.text, re.I
        ):
            relationships.append(
                RelationshipMention(
                    unit,
                    match.group("class"),
                    GraphRelationshipType.CONTAINS,
                    0.92,
                    GraphEntityType.MODULE,
                    GraphEntityType.CLASS,
                )
            )
        return relationships

    def _extract_swagger(self, text: str) -> list[RelationshipMention]:
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            try:
                value = yaml.safe_load(text)
            except yaml.YAMLError:
                return []
        relationships: list[RelationshipMention] = []
        if not isinstance(value, dict) or not isinstance(value.get("paths"), dict):
            return relationships
        for path, operations in value["paths"].items():
            if not isinstance(operations, dict):
                continue
            for method, operation in operations.items():
                if method.casefold() not in {
                    "get", "post", "put", "patch", "delete", "options", "head"
                }:
                    continue
                endpoint = f"{method.upper()} {path}"
                if isinstance(operation, dict):
                    operation_id = operation.get("operationId")
                    if operation_id:
                        relationships.append(
                            RelationshipMention(
                                endpoint,
                                str(operation_id),
                                GraphRelationshipType.USES,
                                0.95,
                                GraphEntityType.ENDPOINT,
                                GraphEntityType.METHOD,
                            )
                        )
                    for reference in self._collect_refs(operation):
                        target = reference.rsplit("/", maxsplit=1)[-1]
                        relationships.append(
                            RelationshipMention(
                                endpoint,
                                target,
                                GraphRelationshipType.REFERENCES,
                                0.9,
                                GraphEntityType.ENDPOINT,
                                GraphEntityType.ERP_OBJECT,
                                evidence=reference,
                            )
                        )
        return relationships

    def _collect_refs(self, value: Any) -> tuple[str, ...]:
        found: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "$ref" and isinstance(child, str):
                    found.append(child)
                else:
                    found.extend(self._collect_refs(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(self._collect_refs(child))
        return tuple(dict.fromkeys(found))

    def _qualified_name(self, schema: Any, name: Any, database: Any = None) -> str:
        clean_name = str(name or "").strip()
        clean_schema = str(schema or "").strip()
        clean_database = str(database or "").strip()
        parts = [part for part in (clean_database, clean_schema, clean_name) if part]
        return ".".join(parts)

    def _entity_type(self, value: str) -> GraphEntityType:
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
            "column": GraphEntityType.COLUMN,
        }.get(value.casefold(), GraphEntityType.UNKNOWN)

    def _ast_name(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self._ast_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None

    def _deduplicate(
        self, relationships: Iterable[RelationshipMention]
    ) -> tuple[RelationshipMention, ...]:
        unique: dict[
            tuple[str, str, GraphRelationshipType], RelationshipMention
        ] = {}
        for relationship in relationships:
            key = (
                normalize_entity_name(relationship.source_name),
                normalize_entity_name(relationship.target_name),
                relationship.relationship_type,
            )
            current = unique.get(key)
            if current is None or relationship.confidence > current.confidence:
                unique[key] = relationship
        return tuple(unique.values())