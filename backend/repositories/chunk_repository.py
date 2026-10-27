from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import pyodbc

from backend.config.settings import get_settings
from backend.embeddings.embedding_service import EmbeddingRecord
from backend.parsers.parser_models import ParsedDocument


@dataclass(frozen=True, slots=True)
class StoredChunk:
    chunk_id: str
    document_id: str
    source_path: str
    source_name: str
    source_type: str
    chunk_index: int
    text: str
    checksum: str | None = None
    metadata_json: str | None = None
    created_at_utc: datetime = datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ChunkRepositoryResult:
    stored_chunks: int


class ChunkRepository:
    """Persist parsed document chunks to SQL Server."""

    def __init__(self, connection_string: str | None = None) -> None:
        self._settings = get_settings()
        self._connection_string = connection_string or self._build_connection_string()

    def store_document_chunks(self, document: ParsedDocument, chunks: Sequence[StoredChunk]) -> ChunkRepositoryResult:
        if not chunks:
            return ChunkRepositoryResult(stored_chunks=0)

        with self._connect() as connection:
            cursor = connection.cursor()
            for chunk in chunks:
                cursor.execute(
                    """
                    MERGE AI.DocumentChunks AS target
                    USING (SELECT ? AS ChunkId) AS source
                    ON target.ChunkId = source.ChunkId
                    WHEN MATCHED THEN
                        UPDATE SET
                            DocumentId = ?,
                            SourcePath = ?,
                            SourceName = ?,
                            SourceType = ?,
                            ChunkIndex = ?,
                            Text = ?,
                            Checksum = ?,
                            MetadataJson = ?,
                            ModifiedAtUtc = SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN
                        INSERT (
                            ChunkId,
                            DocumentId,
                            SourcePath,
                            SourceName,
                            SourceType,
                            ChunkIndex,
                            Text,
                            Checksum,
                            MetadataJson,
                            CreatedAtUtc,
                            ModifiedAtUtc
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME());
                    """,
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.source_path,
                        chunk.source_name,
                        chunk.source_type,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.checksum,
                        chunk.metadata_json,
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.source_path,
                        chunk.source_name,
                        chunk.source_type,
                        chunk.chunk_index,
                        chunk.text,
                        chunk.checksum,
                        chunk.metadata_json,
                    ),
                )
            connection.commit()
        return ChunkRepositoryResult(stored_chunks=len(chunks))

    def store_embedding_records(self, embedding_records: Iterable[EmbeddingRecord]) -> int:
        records = tuple(embedding_records)
        if not records:
            return 0

        with self._connect() as connection:
            cursor = connection.cursor()
            for record in records:
                cursor.execute(
                    """
                    MERGE AI.ChunkEmbeddings AS target
                    USING (SELECT ? AS ChunkId, ? AS ModelName) AS source
                    ON target.ChunkId = source.ChunkId AND target.ModelName = source.ModelName
                    WHEN MATCHED THEN
                        UPDATE SET
                            VectorJson = ?,
                            ChunkChecksum = ?,
                            DocumentTitle = ?,
                            MetadataJson = ?,
                            ModifiedAtUtc = SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN
                        INSERT (
                            ChunkId,
                            ModelName,
                            VectorJson,
                            ChunkChecksum,
                            DocumentTitle,
                            MetadataJson,
                            CreatedAtUtc,
                            ModifiedAtUtc
                        )
                        VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME());
                    """,
                    (
                        record.chunk.chunk_id,
                        record.model_name,
                        record.vector_json,
                        record.chunk_checksum,
                        record.document_title,
                        record.metadata_json,
                        record.chunk.chunk_id,
                        record.model_name,
                        record.vector_json,
                        record.chunk_checksum,
                        record.document_title,
                        record.metadata_json,
                    ),
                )
            connection.commit()
        return len(records)

    def _build_connection_string(self) -> str:
        return (
            f"DRIVER={self._settings.odbc_driver};"
            f"SERVER={self._settings.sql_server},{self._settings.sql_port};"
            f"DATABASE={self._settings.sql_database};"
            f"UID={self._settings.sql_user};"
            f"PWD={self._settings.sql_password};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=5;"
        )

    def _connect(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)
