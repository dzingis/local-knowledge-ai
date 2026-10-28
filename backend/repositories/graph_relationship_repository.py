from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from backend.graph.models import GraphRelationship, GraphRelationshipType
from backend.repositories.graph_repository_base import GraphRepositoryBase


class GraphRelationshipRepository(GraphRepositoryBase):
    """Stores and queries confidence-scored, document-provenanced graph edges."""

    def insert(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: GraphRelationshipType,
        confidence: float,
        source_document_id: str | None = None,
        evidence: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GraphRelationship:
        return self.upsert(
            source_entity_id,
            target_entity_id,
            relationship_type,
            confidence,
            source_document_id,
            evidence,
            metadata,
        )

    def upsert(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: GraphRelationshipType,
        confidence: float,
        source_document_id: str | None = None,
        evidence: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GraphRelationship:
        if not 0 <= confidence <= 1:
            raise ValueError("Relationship confidence must be between 0 and 1.")
        source_id = self._uuid(source_entity_id)
        target_id = self._uuid(target_entity_id)
        document_id = self._uuid(source_document_id) if source_document_id else None
        if source_id == target_id:
            raise ValueError("Self-referential graph relationships are not supported.")
        relationship_id = str(uuid4())
        with self._connect() as connection:
            try:
                cursor = connection.cursor()
                if document_id is None:
                    row = cursor.execute(
                        """
                        SELECT TOP (1) RelationshipId FROM Graph.Relationship
                        WHERE SourceEntityId = ? AND TargetEntityId = ?
                          AND RelationshipType = ? AND SourceDocumentId IS NULL;
                        """,
                        (source_id, target_id, relationship_type.value),
                    ).fetchone()
                else:
                    row = cursor.execute(
                        """
                        SELECT TOP (1) RelationshipId FROM Graph.Relationship
                        WHERE SourceEntityId = ? AND TargetEntityId = ?
                          AND RelationshipType = ? AND SourceDocumentId = ?;
                        """,
                        (source_id, target_id, relationship_type.value, document_id),
                    ).fetchone()
                if row is not None:
                    relationship_id = str(row.RelationshipId)
                    cursor.execute(
                        """
                        UPDATE Graph.Relationship
                        SET Confidence = CASE WHEN Confidence < ? THEN ? ELSE Confidence END,
                            Evidence = COALESCE(?, Evidence),
                            MetadataJson = COALESCE(?, MetadataJson)
                        WHERE RelationshipId = ?;
                        """,
                        (
                            confidence,
                            confidence,
                            evidence,
                            json.dumps(metadata or {}, ensure_ascii=False),
                            relationship_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO Graph.Relationship (
                            RelationshipId, SourceEntityId, TargetEntityId,
                            RelationshipType, Confidence, SourceDocumentId,
                            Evidence, MetadataJson, CreatedAt
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME());
                        """,
                        (
                            relationship_id,
                            source_id,
                            target_id,
                            relationship_type.value,
                            confidence,
                            document_id,
                            evidence,
                            json.dumps(metadata or {}, ensure_ascii=False),
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        relationship = self.get(relationship_id)
        if relationship is None:
            raise RuntimeError(
                f"Graph relationship {relationship_id} was not available after upsert."
            )
        return relationship

    def update(self, relationship: GraphRelationship) -> GraphRelationship:
        if not 0 <= relationship.confidence <= 1:
            raise ValueError("Relationship confidence must be between 0 and 1.")
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE Graph.Relationship
                SET SourceEntityId = ?, TargetEntityId = ?, RelationshipType = ?,
                    Confidence = ?, SourceDocumentId = ?, Evidence = ?,
                    MetadataJson = ?
                WHERE RelationshipId = ?;
                """,
                (
                    self._uuid(relationship.source_entity_id),
                    self._uuid(relationship.target_entity_id),
                    relationship.relationship_type.value,
                    relationship.confidence,
                    self._uuid(relationship.source_document_id)
                    if relationship.source_document_id
                    else None,
                    relationship.evidence,
                    json.dumps(relationship.metadata, ensure_ascii=False),
                    self._uuid(relationship.relationship_id),
                ),
            )
            if cursor.rowcount == 0:
                connection.rollback()
                raise KeyError(
                    f"Graph relationship {relationship.relationship_id} does not exist."
                )
            connection.commit()
        updated = self.get(relationship.relationship_id)
        if updated is None:
            raise RuntimeError("Graph relationship disappeared after update.")
        return updated

    def delete(self, relationship_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM Graph.Relationship WHERE RelationshipId = ?;",
                (self._uuid(relationship_id),),
            )
            deleted = cursor.rowcount > 0
            connection.commit()
        return deleted

    def get(self, relationship_id: str) -> GraphRelationship | None:
        with self._connect() as connection:
            row = connection.cursor().execute(
                """
                SELECT RelationshipId, SourceEntityId, TargetEntityId,
                       RelationshipType, Confidence, SourceDocumentId,
                       Evidence, MetadataJson, CreatedAt
                FROM Graph.Relationship WHERE RelationshipId = ?;
                """,
                (self._uuid(relationship_id),),
            ).fetchone()
        return self._relationship_from_row(row) if row is not None else None

    def search(
        self,
        query: str,
        relationship_type: GraphRelationshipType | str | None = None,
        limit: int = 50,
    ) -> tuple[GraphRelationship, ...]:
        conditions = """
            (source.CanonicalName LIKE ? OR target.CanonicalName LIKE ?
             OR r.Evidence LIKE ?)
        """
        pattern = f"%{query.strip()}%"
        parameters: list[Any] = [pattern, pattern, pattern]
        if relationship_type is not None:
            type_value = (
                relationship_type.value
                if isinstance(relationship_type, GraphRelationshipType)
                else relationship_type
            )
            conditions += " AND r.RelationshipType = ?"
            parameters.append(type_value)
        parameters.append(max(1, min(limit, 200)))
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"""
                SELECT TOP (?) r.RelationshipId, r.SourceEntityId, r.TargetEntityId,
                       r.RelationshipType, r.Confidence, r.SourceDocumentId,
                       r.Evidence, r.MetadataJson, r.CreatedAt
                FROM Graph.Relationship AS r
                INNER JOIN Graph.Entity AS source ON source.EntityId = r.SourceEntityId
                INNER JOIN Graph.Entity AS target ON target.EntityId = r.TargetEntityId
                WHERE {conditions}
                ORDER BY r.Confidence DESC, r.CreatedAt DESC;
                """,
                (parameters[-1], *parameters[:-1]),
            ).fetchall()
        return tuple(self._relationship_from_row(row) for row in rows)

    def find_related(
        self, entity_id: str, limit: int = 100
    ) -> tuple[GraphRelationship, ...]:
        normalized_id = self._uuid(entity_id)
        with self._connect() as connection:
            rows = connection.cursor().execute(
                """
                SELECT TOP (?) RelationshipId, SourceEntityId, TargetEntityId,
                       RelationshipType, Confidence, SourceDocumentId,
                       Evidence, MetadataJson, CreatedAt
                FROM Graph.Relationship
                WHERE SourceEntityId = ? OR TargetEntityId = ?
                ORDER BY Confidence DESC, CreatedAt DESC;
                """,
                (max(1, min(limit, 500)), normalized_id, normalized_id),
            ).fetchall()
        return tuple(self._relationship_from_row(row) for row in rows)

    def find_by_document(self, document_id: str) -> tuple[GraphRelationship, ...]:
        with self._connect() as connection:
            rows = connection.cursor().execute(
                """
                SELECT RelationshipId, SourceEntityId, TargetEntityId,
                       RelationshipType, Confidence, SourceDocumentId,
                       Evidence, MetadataJson, CreatedAt
                FROM Graph.Relationship
                WHERE SourceDocumentId = ?
                ORDER BY RelationshipType, CreatedAt;
                """,
                (self._uuid(document_id),),
            ).fetchall()
        return tuple(self._relationship_from_row(row) for row in rows)

    def delete_for_document(self, document_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM Graph.Relationship WHERE SourceDocumentId = ?;",
                (self._uuid(document_id),),
            )
            deleted = max(cursor.rowcount, 0)
            connection.commit()
        return deleted

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.cursor().execute(
                "SELECT COUNT_BIG(*) AS Cnt FROM Graph.Relationship;"
            ).fetchone()
        return int(row.Cnt or 0)