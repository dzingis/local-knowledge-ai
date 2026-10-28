from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pyodbc

from backend.config.settings import get_settings
from backend.graph.models import (
    GraphEntity,
    GraphEntityType,
    GraphRelationship,
    GraphRelationshipType,
)


class GraphRepositoryBase:
    """Shared SQL Server connection and graph-row mapping helpers."""

    def __init__(self, connection_string: str | None = None) -> None:
        settings = get_settings()
        self._connection_string = connection_string or (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={settings.sql_server},{settings.sql_port};"
            f"DATABASE={settings.sql_database};"
            f"UID={settings.sql_user};"
            f"PWD={settings.sql_password};"
            "Encrypt=no;TrustServerCertificate=yes;Connection Timeout=5;"
        )

    def _connect(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)

    def _entity_from_row(self, row: Any) -> GraphEntity:
        metadata = self._json_dict(getattr(row, "MetadataJson", None))
        aliases = tuple(
            item.strip()
            for item in str(getattr(row, "Aliases", "") or "").split("\x1f")
            if item.strip()
        )
        properties: dict[str, str] = {}
        raw_properties = getattr(row, "PropertiesJson", None)
        if raw_properties:
            for item in str(raw_properties).split("\x1f"):
                key, separator, value = item.partition("\x1e")
                if separator:
                    properties[key] = value
        source_document_ids = tuple(
            item.strip()
            for item in str(getattr(row, "SourceDocumentIds", "") or "").split("\x1f")
            if item.strip()
        )
        entity_type = str(getattr(row, "EntityType", GraphEntityType.UNKNOWN.value))
        try:
            typed_entity = GraphEntityType(entity_type)
        except ValueError:
            typed_entity = GraphEntityType.UNKNOWN
        return GraphEntity(
            entity_id=str(row.EntityId),
            name=str(row.CanonicalName),
            normalized_name=str(row.NormalizedName),
            entity_type=typed_entity,
            description=getattr(row, "Description", None),
            metadata=metadata,
            aliases=aliases,
            properties=properties,
            source_document_ids=source_document_ids,
            created_at=getattr(row, "CreatedAt", None),
            updated_at=getattr(row, "UpdatedAt", None),
        )

    def _relationship_from_row(self, row: Any) -> GraphRelationship:
        try:
            relationship_type = GraphRelationshipType(str(row.RelationshipType))
        except ValueError:
            relationship_type = GraphRelationshipType.REFERENCES
        return GraphRelationship(
            relationship_id=str(row.RelationshipId),
            source_entity_id=str(row.SourceEntityId),
            target_entity_id=str(row.TargetEntityId),
            relationship_type=relationship_type,
            confidence=float(row.Confidence),
            source_document_id=(
                str(row.SourceDocumentId) if row.SourceDocumentId is not None else None
            ),
            evidence=getattr(row, "Evidence", None),
            metadata=self._json_dict(getattr(row, "MetadataJson", None)),
            created_at=getattr(row, "CreatedAt", None),
        )

    def _json_dict(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}

    def _uuid(self, value: str) -> str:
        return str(UUID(value))