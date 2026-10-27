from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pyodbc

from backend.embeddings.embedding_service import EmbeddingRecord
from backend.indexer.sql_queue_repository import QueueRepositoryRecord


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    embedding_id: str
    chunk_id: str
    document_id: str
    source_path: str
    model_name: str
    dimension_count: int
    checksum: str | None = None
    metadata: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingRepositoryResult:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0


class EmbeddingRepository:
    """SQL-backed embedding repository for Milestone 2F."""

    def __init__(self, connection: pyodbc.Connection | None = None) -> None:
        self._connection = connection

    def store_embedding_record(self, record: EmbeddingRecord) -> StoredEmbedding:
        stored = StoredEmbedding(
            embedding_id=record.embedding_id,
            chunk_id=record.chunk.chunk_id,
            document_id=str(record.chunk.metadata.source_path),
            source_path=str(record.chunk.metadata.source_path),
            model_name=record.model_name,
            dimension_count=len(record.vector),
            checksum=record.chunk_checksum,
            metadata={
                "chunk_index": str(record.chunk.metadata.chunk_index),
                "position": str(record.chunk.metadata.position),
                "page_number": str(record.chunk.metadata.page_number or ""),
                "heading": record.chunk.metadata.heading or "",
                "token_count": str(record.chunk.metadata.token_count),
                **{k: str(v) for k, v in record.metadata.items()},
            },
        )

        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                MERGE AI.ChunkEmbeddings AS target
                USING (SELECT ? AS EmbeddingId) AS source
                ON target.EmbeddingId = source.EmbeddingId
                WHEN MATCHED THEN
                    UPDATE SET
                        ChunkId = ?,
                        DocumentId = ?,
                        SourcePath = ?,
                        ModelName = ?,
                        DimensionCount = ?,
                        Checksum = ?
                WHEN NOT MATCHED THEN
                    INSERT (
                        EmbeddingId,
                        ChunkId,
                        DocumentId,
                        SourcePath,
                        ModelName,
                        DimensionCount,
                        Checksum
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    stored.embedding_id,
                    stored.chunk_id,
                    stored.document_id,
                    stored.source_path,
                    stored.model_name,
                    stored.dimension_count,
                    stored.checksum,
                    stored.embedding_id,
                    stored.chunk_id,
                    stored.document_id,
                    stored.source_path,
                    stored.model_name,
                    stored.dimension_count,
                    stored.checksum,
                ),
            )
            connection.commit()

        return stored

    def store_embedding_records(self, records: Sequence[EmbeddingRecord]) -> tuple[StoredEmbedding, ...]:
        stored: list[StoredEmbedding] = []
        for record in records:
            stored.append(self.store_embedding_record(record))
        return tuple(stored)

    def delete_by_chunk_ids(self, chunk_ids: Iterable[str]) -> int:
        deleted = 0
        with self._connect() as connection:
            cursor = connection.cursor()
            for chunk_id in chunk_ids:
                cursor.execute("DELETE FROM AI.ChunkEmbeddings WHERE ChunkId = ?;", (chunk_id,))
                deleted += cursor.rowcount if cursor.rowcount > 0 else 0
            connection.commit()
        return deleted

    def _connect(self) -> pyodbc.Connection:
        if self._connection is not None:
            return self._connection
        raise RuntimeError("EmbeddingRepository requires an injected pyodbc connection for this build stage.")
