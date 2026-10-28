from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from backend.graph.models import (
    EntityMention,
    GraphEntity,
    GraphEntityType,
    GraphStatistics,
    normalize_entity_name,
)
from backend.repositories.graph_repository_base import GraphRepositoryBase


_ENTITY_SELECT = """
SELECT e.EntityId, e.CanonicalName, e.NormalizedName, e.EntityType,
       e.Description, e.MetadataJson, e.CreatedAt, e.UpdatedAt,
       ISNULL((
           SELECT STRING_AGG(CONVERT(NVARCHAR(MAX), a.AliasName), NCHAR(31))
           FROM Graph.EntityAlias AS a WHERE a.EntityId = e.EntityId
       ), N'') AS Aliases,
       ISNULL((
           SELECT STRING_AGG(CONVERT(NVARCHAR(MAX), p.PropertyKey + NCHAR(30) + p.PropertyValue), NCHAR(31))
           FROM Graph.EntityProperty AS p WHERE p.EntityId = e.EntityId
       ), N'') AS PropertiesJson,
       ISNULL((
           SELECT STRING_AGG(CONVERT(NVARCHAR(36), ed.DocumentId), NCHAR(31))
           FROM Graph.EntityDocument AS ed WHERE ed.EntityId = e.EntityId
       ), N'') AS SourceDocumentIds
FROM Graph.Entity AS e
"""


class GraphEntityRepository(GraphRepositoryBase):
    """Persists canonical graph entities, aliases, properties, and provenance."""

    def insert(
        self,
        mention: EntityMention,
        source_document_id: str | None = None,
        source_path: str | None = None,
    ) -> GraphEntity:
        return self.upsert(mention, source_document_id, source_path)

    def upsert(
        self,
        mention: EntityMention,
        source_document_id: str | None = None,
        source_path: str | None = None,
    ) -> GraphEntity:
        normalized = normalize_entity_name(mention.name)
        if not normalized:
            raise ValueError("Entity names cannot be normalized to an empty value.")
        document_id = self._uuid(source_document_id) if source_document_id else None
        with self._connect() as connection:
            try:
                cursor = connection.cursor()
                row = cursor.execute(
                    """
                    SELECT EntityId, CanonicalName, NormalizedName, EntityType,
                           Description, MetadataJson, CreatedAt, UpdatedAt
                    FROM Graph.Entity
                    WHERE NormalizedName = ? AND EntityType = ?;
                    """,
                    (normalized, mention.entity_type.value),
                ).fetchone()
                if row is None:
                    entity_id = str(uuid4())
                    cursor.execute(
                        """
                        INSERT INTO Graph.Entity (
                            EntityId, CanonicalName, NormalizedName, EntityType,
                            Description, MetadataJson, CreatedAt, UpdatedAt
                        )
                        VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME());
                        """,
                        (
                            entity_id,
                            mention.name.strip(),
                            normalized,
                            mention.entity_type.value,
                            mention.description,
                            json.dumps(
                                {"confidence": mention.confidence, "evidence": mention.evidence},
                                ensure_ascii=False,
                            ),
                        ),
                    )
                else:
                    entity_id = str(row.EntityId)
                    cursor.execute(
                        """
                        UPDATE Graph.Entity
                        SET Description = COALESCE(Description, ?),
                            UpdatedAt = SYSUTCDATETIME()
                        WHERE EntityId = ?;
                        """,
                        (mention.description, entity_id),
                    )

                aliases = tuple(dict.fromkeys((mention.name.strip(), *mention.aliases)))
                for alias in aliases:
                    alias_normalized = normalize_entity_name(alias)
                    if not alias_normalized:
                        continue
                    cursor.execute(
                        """
                        IF NOT EXISTS (
                            SELECT 1 FROM Graph.EntityAlias
                            WHERE EntityId = ? AND NormalizedAlias = ?
                        )
                        INSERT INTO Graph.EntityAlias (
                            EntityId, AliasName, NormalizedAlias, CreatedAt
                        )
                        VALUES (?, ?, ?, SYSUTCDATETIME());
                        """,
                        (entity_id, alias_normalized, entity_id, alias, alias_normalized),
                    )

                for key, value in mention.properties.items():
                    cursor.execute(
                        """
                        MERGE Graph.EntityProperty AS target
                        USING (SELECT ? AS EntityId, ? AS PropertyKey) AS source
                        ON target.EntityId = source.EntityId
                           AND target.PropertyKey = source.PropertyKey
                        WHEN MATCHED THEN UPDATE SET
                            PropertyValue = ?, UpdatedAt = SYSUTCDATETIME()
                        WHEN NOT MATCHED THEN INSERT (
                            EntityId, PropertyKey, PropertyValue, CreatedAt, UpdatedAt
                        ) VALUES (?, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME());
                        """,
                        (entity_id, key, value, entity_id, key, value),
                    )
                if document_id is not None:
                    cursor.execute(
                        """
                        MERGE Graph.EntityDocument AS target
                        USING (SELECT ? AS EntityId, ? AS DocumentId) AS source
                        ON target.EntityId = source.EntityId
                           AND target.DocumentId = source.DocumentId
                        WHEN MATCHED THEN UPDATE SET
                            SourcePath = COALESCE(?, target.SourcePath),
                            Confidence = CASE WHEN ? > target.Confidence THEN ? ELSE target.Confidence END
                        WHEN NOT MATCHED THEN INSERT (
                            EntityId, DocumentId, SourcePath, Confidence, Evidence, CreatedAt
                        ) VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME());
                        """,
                        (
                            entity_id,
                            document_id,
                            source_path,
                            mention.confidence,
                            mention.confidence,
                            entity_id,
                            document_id,
                            source_path,
                            mention.confidence,
                            mention.evidence,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        entity = self.get(entity_id)
        if entity is None:
            raise RuntimeError(f"Graph entity {entity_id} was not available after upsert.")
        return entity

    def update(self, entity: GraphEntity) -> GraphEntity:
        normalized = normalize_entity_name(entity.name)
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE Graph.Entity
                SET CanonicalName = ?, NormalizedName = ?, EntityType = ?,
                    Description = ?, MetadataJson = ?, UpdatedAt = SYSUTCDATETIME()
                WHERE EntityId = ?;
                """,
                (
                    entity.name,
                    normalized,
                    entity.entity_type.value,
                    entity.description,
                    json.dumps(entity.metadata, ensure_ascii=False),
                    self._uuid(entity.entity_id),
                ),
            )
            if cursor.rowcount == 0:
                connection.rollback()
                raise KeyError(f"Graph entity {entity.entity_id} does not exist.")
            for alias in entity.aliases:
                alias_normalized = normalize_entity_name(alias)
                cursor.execute(
                    """
                    IF NOT EXISTS (
                        SELECT 1 FROM Graph.EntityAlias
                        WHERE EntityId = ? AND NormalizedAlias = ?
                    )
                    INSERT INTO Graph.EntityAlias(EntityId, AliasName, NormalizedAlias, CreatedAt)
                    VALUES (?, ?, ?, SYSUTCDATETIME());
                    """,
                    (
                        self._uuid(entity.entity_id),
                        alias_normalized,
                        self._uuid(entity.entity_id),
                        alias,
                        alias_normalized,
                    ),
                )
            connection.commit()
        updated = self.get(entity.entity_id)
        if updated is None:
            raise RuntimeError(f"Graph entity {entity.entity_id} disappeared after update.")
        return updated

    def delete(self, entity_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.cursor()
            normalized_id = self._uuid(entity_id)
            cursor.execute(
                """
                DELETE FROM Graph.Relationship
                WHERE SourceEntityId = ? OR TargetEntityId = ?;
                """,
                (normalized_id, normalized_id),
            )
            cursor.execute(
                "DELETE FROM Graph.Entity WHERE EntityId = ?;",
                (normalized_id,),
            )
            deleted = cursor.rowcount > 0
            connection.commit()
        return deleted

    def get(self, entity_id: str) -> GraphEntity | None:
        with self._connect() as connection:
            row = connection.cursor().execute(
                f"{_ENTITY_SELECT} WHERE e.EntityId = ?;",
                (self._uuid(entity_id),),
            ).fetchone()
        return self._entity_from_row(row) if row is not None else None

    def search(
        self,
        query: str,
        entity_type: GraphEntityType | str | None = None,
        limit: int = 20,
    ) -> tuple[GraphEntity, ...]:
        normalized = normalize_entity_name(query)
        if not normalized:
            return ()
        conditions = """
            (e.NormalizedName LIKE ? OR EXISTS (
                SELECT 1 FROM Graph.EntityAlias AS a
                WHERE a.EntityId = e.EntityId AND a.NormalizedAlias LIKE ?
            ))
        """
        parameters: list[Any] = [f"%{normalized}%", f"%{normalized}%"]
        if entity_type is not None:
            type_value = entity_type.value if isinstance(entity_type, GraphEntityType) else entity_type
            conditions += " AND e.EntityType = ?"
            parameters.append(type_value)
        safe_limit = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"""
                {_ENTITY_SELECT.replace("SELECT e.EntityId", "SELECT TOP (?) e.EntityId", 1)}
                WHERE {conditions}
                ORDER BY CASE WHEN e.NormalizedName = ? THEN 0 ELSE 1 END,
                         LEN(e.NormalizedName), e.CanonicalName;
                """,
                (safe_limit, *parameters, normalized),
            ).fetchall()
        return tuple(self._entity_from_row(row) for row in rows)

    def find_related(self, entity_id: str, limit: int = 50) -> tuple[GraphEntity, ...]:
        normalized_id = self._uuid(entity_id)
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"""
                {_ENTITY_SELECT.replace("SELECT e.EntityId", "SELECT TOP (?) e.EntityId", 1)}
                INNER JOIN (
                    SELECT TargetEntityId AS RelatedEntityId
                    FROM Graph.Relationship WHERE SourceEntityId = ?
                    UNION
                    SELECT SourceEntityId AS RelatedEntityId
                    FROM Graph.Relationship WHERE TargetEntityId = ?
                ) AS related ON related.RelatedEntityId = e.EntityId
                ORDER BY e.CanonicalName;
                """,
                (max(1, min(limit, 500)), normalized_id, normalized_id),
            ).fetchall()
        return tuple(self._entity_from_row(row) for row in rows)

    def find_by_document(self, document_id: str) -> tuple[GraphEntity, ...]:
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"""
                {_ENTITY_SELECT}
                INNER JOIN Graph.EntityDocument AS ed ON ed.EntityId = e.EntityId
                WHERE ed.DocumentId = ?
                ORDER BY e.EntityType, e.CanonicalName;
                """,
                (self._uuid(document_id),),
            ).fetchall()
        return tuple(self._entity_from_row(row) for row in rows)

    def merge_duplicates(self, entity_ids: tuple[str, ...]) -> GraphEntity:
        if len(set(entity_ids)) < 2:
            raise ValueError("At least two distinct entity IDs are required.")
        normalized_ids = tuple(self._uuid(entity_id) for entity_id in entity_ids)
        with self._connect() as connection:
            try:
                cursor = connection.cursor()
                placeholders = ",".join("?" for _ in normalized_ids)
                rows = cursor.execute(
                    f"""
                    SELECT EntityId, CanonicalName, NormalizedName, EntityType,
                           Description, MetadataJson, CreatedAt, UpdatedAt
                    FROM Graph.Entity WHERE EntityId IN ({placeholders})
                    ORDER BY CreatedAt, EntityId;
                    """,
                    normalized_ids,
                ).fetchall()
                if len(rows) != len(normalized_ids):
                    raise KeyError("One or more graph entities do not exist.")
                types = {str(row.EntityType) for row in rows}
                normalized_names = {str(row.NormalizedName) for row in rows}
                if len(types) != 1 or len(normalized_names) != 1:
                    raise ValueError("Only equivalent normalized entities of the same type can be merged.")
                canonical_id = str(rows[0].EntityId)
                duplicates = tuple(str(row.EntityId) for row in rows[1:])
                for duplicate_id in duplicates:
                    cursor.execute(
                        """
                        INSERT INTO Graph.EntityAlias(EntityId, AliasName, NormalizedAlias, CreatedAt)
                        SELECT ?, a.AliasName, a.NormalizedAlias, SYSUTCDATETIME()
                        FROM Graph.EntityAlias AS a
                        WHERE a.EntityId = ? AND NOT EXISTS (
                            SELECT 1 FROM Graph.EntityAlias AS existing
                            WHERE existing.EntityId = ? AND existing.NormalizedAlias = a.NormalizedAlias
                        );
                        """,
                        (canonical_id, duplicate_id, canonical_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO Graph.EntityDocument(EntityId, DocumentId, SourcePath, Confidence, Evidence, CreatedAt)
                        SELECT ?, ed.DocumentId, ed.SourcePath, ed.Confidence, ed.Evidence, ed.CreatedAt
                        FROM Graph.EntityDocument AS ed
                        WHERE ed.EntityId = ? AND NOT EXISTS (
                            SELECT 1 FROM Graph.EntityDocument AS existing
                            WHERE existing.EntityId = ? AND existing.DocumentId = ed.DocumentId
                        );
                        """,
                        (canonical_id, duplicate_id, canonical_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO Graph.EntityProperty(EntityId, PropertyKey, PropertyValue, CreatedAt, UpdatedAt)
                        SELECT ?, p.PropertyKey, p.PropertyValue, p.CreatedAt, SYSUTCDATETIME()
                        FROM Graph.EntityProperty AS p
                        WHERE p.EntityId = ? AND NOT EXISTS (
                            SELECT 1 FROM Graph.EntityProperty AS existing
                            WHERE existing.EntityId = ? AND existing.PropertyKey = p.PropertyKey
                        );
                        """,
                        (canonical_id, duplicate_id, canonical_id),
                    )
                    cursor.execute(
                        "UPDATE Graph.Relationship SET SourceEntityId = ? WHERE SourceEntityId = ?;",
                        (canonical_id, duplicate_id),
                    )
                    cursor.execute(
                        "UPDATE Graph.Relationship SET TargetEntityId = ? WHERE TargetEntityId = ?;",
                        (canonical_id, duplicate_id),
                    )
                    cursor.execute(
                        """
                        DELETE FROM Graph.Relationship
                        WHERE SourceEntityId = TargetEntityId;
                        """
                    )
                    cursor.execute(
                        """
                        INSERT INTO Graph.EntityEmbedding(EntityId, QdrantPointId, ModelName, UpdatedAt)
                        SELECT ?, QdrantPointId, ModelName, SYSUTCDATETIME()
                        FROM Graph.EntityEmbedding WHERE EntityId = ?
                          AND NOT EXISTS (SELECT 1 FROM Graph.EntityEmbedding WHERE EntityId = ?);
                        """,
                        (canonical_id, duplicate_id, canonical_id),
                    )
                    cursor.execute("DELETE FROM Graph.Entity WHERE EntityId = ?;", (duplicate_id,))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        canonical = self.get(canonical_id)
        if canonical is None:
            raise RuntimeError("The canonical graph entity was not available after merging.")
        return canonical

    def list_all(self) -> tuple[GraphEntity, ...]:
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"{_ENTITY_SELECT} ORDER BY e.CanonicalName;"
            ).fetchall()
        return tuple(self._entity_from_row(row) for row in rows)

    def add_embedding(self, entity_id: str, point_id: str, model_name: str) -> None:
        with self._connect() as connection:
            connection.cursor().execute(
                """
                MERGE Graph.EntityEmbedding AS target
                USING (SELECT ? AS EntityId) AS source
                ON target.EntityId = source.EntityId
                WHEN MATCHED THEN UPDATE SET
                    QdrantPointId = ?, ModelName = ?, UpdatedAt = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT (
                    EntityId, QdrantPointId, ModelName, UpdatedAt
                ) VALUES (?, ?, ?, SYSUTCDATETIME());
                """,
                (
                    self._uuid(entity_id),
                    point_id,
                    model_name,
                    self._uuid(entity_id),
                    point_id,
                    model_name,
                ),
            )
            connection.commit()

    def embedding_point_id(self, entity_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.cursor().execute(
                "SELECT QdrantPointId FROM Graph.EntityEmbedding WHERE EntityId = ?;",
                (self._uuid(entity_id),),
            ).fetchone()
        return str(row.QdrantPointId) if row is not None else None

    def statistics(self) -> GraphStatistics:
        with self._connect() as connection:
            cursor = connection.cursor()
            entity_count = int(cursor.execute("SELECT COUNT_BIG(*) AS Cnt FROM Graph.Entity;").fetchone().Cnt)
            relationship_count = int(cursor.execute("SELECT COUNT_BIG(*) AS Cnt FROM Graph.Relationship;").fetchone().Cnt)
            type_rows = cursor.execute(
                "SELECT EntityType, COUNT_BIG(*) AS Cnt FROM Graph.Entity GROUP BY EntityType;"
            ).fetchall()
            connected_rows = cursor.execute(
                """
                SELECT TOP (10) e.CanonicalName, COUNT_BIG(*) AS Degree
                FROM Graph.Entity AS e
                INNER JOIN (
                    SELECT SourceEntityId AS EntityId FROM Graph.Relationship
                    UNION ALL
                    SELECT TargetEntityId AS EntityId FROM Graph.Relationship
                ) AS degree ON degree.EntityId = e.EntityId
                GROUP BY e.EntityId, e.CanonicalName
                ORDER BY Degree DESC, e.CanonicalName;
                """
            ).fetchall()
            orphan_count = int(
                cursor.execute(
                    """
                    SELECT COUNT_BIG(*) AS Cnt FROM Graph.Entity AS e
                    WHERE NOT EXISTS (
                        SELECT 1 FROM Graph.Relationship AS r
                        WHERE r.SourceEntityId = e.EntityId OR r.TargetEntityId = e.EntityId
                    );
                    """
                ).fetchone().Cnt
            )
        return GraphStatistics(
            entity_count=entity_count,
            relationship_count=relationship_count,
            entity_types={str(row.EntityType): int(row.Cnt) for row in type_rows},
            most_connected=tuple(
                (str(row.CanonicalName), int(row.Degree)) for row in connected_rows
            ),
            orphan_entity_count=orphan_count,
            average_degree=(2 * relationship_count / entity_count) if entity_count else 0.0,
        )

    def clear_all(self) -> tuple[str, ...]:
        entities = self.list_all()
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM Graph.Relationship;")
            cursor.execute("DELETE FROM Graph.Entity;")
            connection.commit()
        return tuple(entity.entity_id for entity in entities)

    def detach_document(self, document_id: str) -> tuple[str, ...]:
        normalized_id = self._uuid(document_id)
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM Graph.EntityDocument WHERE DocumentId = ?;",
                (normalized_id,),
            )
            orphan_rows = cursor.execute(
                """
                SELECT e.EntityId FROM Graph.Entity AS e
                WHERE NOT EXISTS (
                    SELECT 1 FROM Graph.EntityDocument AS ed WHERE ed.EntityId = e.EntityId
                ) AND NOT EXISTS (
                    SELECT 1 FROM Graph.Relationship AS r
                    WHERE r.SourceEntityId = e.EntityId OR r.TargetEntityId = e.EntityId
                );
                """
            ).fetchall()
            orphan_ids = tuple(str(row.EntityId) for row in orphan_rows)
            if orphan_ids:
                placeholders = ",".join("?" for _ in orphan_ids)
                cursor.execute(
                    f"DELETE FROM Graph.Entity WHERE EntityId IN ({placeholders});",
                    orphan_ids,
                )
            connection.commit()
        return orphan_ids