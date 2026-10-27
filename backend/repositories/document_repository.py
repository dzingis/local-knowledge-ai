from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import pyodbc

from backend.config.settings import get_settings
from backend.embeddings.embedding_service import EmbeddingBatchResult
from backend.parsers.parser_models import ParsedDocument
from backend.vectorstore.qdrant_repository import QdrantRepository, QdrantSearchResult


@dataclass(frozen=True, slots=True)
class StoredDocument:
    document_id: str
    source_path: str
    title: str
    parser_kind: str
    object_type: str
    checksum: str | None
    language: str | None
    page_count: int | None
    line_count: int | None
    character_count: int
    created_at: datetime
    modified_at: datetime
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredChunk:
    chunk_id: str
    document_id: str
    source_path: str
    position: int
    chunk_index: int
    text: str
    token_count: int
    page_number: int | None
    heading: str | None
    checksum: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    embedding_id: str
    chunk_id: str
    model_name: str
    vector_size: int
    created_at: datetime
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DocumentStoreResult:
    document: StoredDocument
    chunks: tuple[StoredChunk, ...]
    embeddings: tuple[StoredEmbedding, ...]
    qdrant_result: QdrantSearchResult | None = None


class DocumentRepository:
    """SQL Server-backed repository for documents, chunks, and embeddings."""

    def __init__(self, connection_string: str | None = None, qdrant_repository: QdrantRepository | None = None) -> None:
        self._settings = get_settings()
        self._connection_string = connection_string or self._build_connection_string()
        self._qdrant_repository = qdrant_repository

    def store_parsed_document(self, parsed_document: ParsedDocument, embedding_result: EmbeddingBatchResult | None = None) -> DocumentStoreResult:
        stored_document = self._upsert_document(parsed_document)
        stored_chunks = self._upsert_chunks(parsed_document, stored_document.document_id)
        stored_embeddings: list[StoredEmbedding] = []

        if embedding_result is not None:
            stored_embeddings = self._upsert_embeddings(stored_chunks, embedding_result)
            if self._qdrant_repository is not None and embedding_result.records:
                self._qdrant_repository.upsert_embedding_records(embedding_result.records)

        return DocumentStoreResult(
            document=stored_document,
            chunks=tuple(stored_chunks),
            embeddings=tuple(stored_embeddings),
        )

    def list_documents(self) -> tuple[StoredDocument, ...]:
        with self._connect() as connection:
            cursor = connection.cursor()
            rows = cursor.execute(
                """
                SELECT
                    DocumentId,
                    SourcePath,
                    Title,
                    ParserKind,
                    ObjectType,
                    Checksum,
                    Language,
                    PageCount,
                    LineCount,
                    CharacterCount,
                    CreatedAt,
                    ModifiedAt,
                    MetadataJson
                FROM AI.Documents
                ORDER BY ModifiedAt DESC;
                """
            ).fetchall()
        return tuple(self._row_to_document(row) for row in rows)

    def get_document(self, document_id: str) -> StoredDocument | None:
        with self._connect() as connection:
            cursor = connection.cursor()
            row = cursor.execute(
                """
                SELECT
                    DocumentId,
                    SourcePath,
                    Title,
                    ParserKind,
                    ObjectType,
                    Checksum,
                    Language,
                    PageCount,
                    LineCount,
                    CharacterCount,
                    CreatedAt,
                    ModifiedAt,
                    MetadataJson
                FROM AI.Documents
                WHERE DocumentId = ?;
                """,
                (document_id,),
            ).fetchone()
        return self._row_to_document(row) if row is not None else None

    def get_document_by_path(self, source_path: str) -> StoredDocument | None:
        with self._connect() as connection:
            cursor = connection.cursor()
            row = cursor.execute(
                """
                SELECT TOP 1
                    DocumentId,
                    SourcePath,
                    Title,
                    ParserKind,
                    ObjectType,
                    Checksum,
                    Language,
                    PageCount,
                    LineCount,
                    CharacterCount,
                    CreatedAt,
                    ModifiedAt,
                    MetadataJson
                FROM AI.Documents
                WHERE SourcePath = ?
                ORDER BY ModifiedAt DESC;
                """,
                (source_path,),
            ).fetchone()

        if row is None:
            return None
        return self._row_to_document(row)

    def delete_document(self, document_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute("DELETE FROM AI.ChunkEmbeddings WHERE ChunkId IN (SELECT ChunkId FROM AI.DocumentChunks WHERE DocumentId = ?);", (document_id,))
            cursor.execute("DELETE FROM AI.DocumentChunks WHERE DocumentId = ?;", (document_id,))
            cursor.execute("DELETE FROM AI.Documents WHERE DocumentId = ?;", (document_id,))
            connection.commit()
            return cursor.rowcount > 0

    def get_stats(self) -> dict[str, int]:
        with self._connect() as connection:
            cursor = connection.cursor()
            documents = cursor.execute("SELECT COUNT(*) AS Cnt FROM AI.Documents;").fetchone()
            chunks = cursor.execute("SELECT COUNT(*) AS Cnt FROM AI.DocumentChunks;").fetchone()
            embeddings = cursor.execute("SELECT COUNT(*) AS Cnt FROM AI.ChunkEmbeddings;").fetchone()
        return {
            "documents": int(getattr(documents, "Cnt", 0) or 0),
            "chunks": int(getattr(chunks, "Cnt", 0) or 0),
            "embeddings": int(getattr(embeddings, "Cnt", 0) or 0),
        }

    def _upsert_document(self, parsed_document: ParsedDocument) -> StoredDocument:
        now = datetime.now(timezone.utc)
        metadata_json = self._serialize_metadata(parsed_document.metadata)
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                MERGE AI.Documents AS target
                USING (SELECT ? AS SourcePath) AS source
                ON target.SourcePath = source.SourcePath
                WHEN MATCHED THEN
                    UPDATE SET
                        Title = ?,
                        ParserKind = ?,
                        ObjectType = ?,
                        Checksum = ?,
                        Language = ?,
                        PageCount = ?,
                        LineCount = ?,
                        CharacterCount = ?,
                        ModifiedAt = ?,
                        MetadataJson = ?
                WHEN NOT MATCHED THEN
                    INSERT (
                        DocumentId,
                        SourcePath,
                        Title,
                        ParserKind,
                        ObjectType,
                        Checksum,
                        Language,
                        PageCount,
                        LineCount,
                        CharacterCount,
                        CreatedAt,
                        ModifiedAt,
                        MetadataJson
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    parsed_document.source_path.as_posix(),
                    parsed_document.title,
                    parsed_document.parser_kind.value,
                    parsed_document.object_type.value,
                    parsed_document.checksum,
                    parsed_document.language,
                    parsed_document.page_count,
                    parsed_document.line_count,
                    parsed_document.character_count,
                    now,
                    metadata_json,
                    parsed_document.source_path.as_posix(),
                    parsed_document.source_path.as_posix(),
                    parsed_document.title,
                    parsed_document.parser_kind.value,
                    parsed_document.object_type.value,
                    parsed_document.checksum,
                    parsed_document.language,
                    parsed_document.page_count,
                    parsed_document.line_count,
                    parsed_document.character_count,
                    now,
                    now,
                    metadata_json,
                ),
            )
            connection.commit()

        return StoredDocument(
            document_id=parsed_document.source_path.as_posix(),
            source_path=parsed_document.source_path.as_posix(),
            title=parsed_document.title,
            parser_kind=parsed_document.parser_kind.value,
            object_type=parsed_document.object_type.value,
            checksum=parsed_document.checksum,
            language=parsed_document.language,
            page_count=parsed_document.page_count,
            line_count=parsed_document.line_count,
            character_count=parsed_document.character_count,
            created_at=now,
            modified_at=now,
            metadata=dict(parsed_document.metadata),
        )

    def _upsert_chunks(self, parsed_document: ParsedDocument, document_id: str) -> list[StoredChunk]:
        from backend.chunking.chunk_engine import ChunkEngine, ChunkingConfig

        chunk_engine = ChunkEngine(ChunkingConfig())
        chunking_result = chunk_engine.chunk_document(parsed_document)
        now = datetime.now(timezone.utc)
        stored_chunks: list[StoredChunk] = []

        with self._connect() as connection:
            cursor = connection.cursor()
            for chunk in chunking_result.chunks:
                cursor.execute(
                    """
                    MERGE AI.DocumentChunks AS target
                    USING (SELECT ? AS ChunkId) AS source
                    ON target.ChunkId = source.ChunkId
                    WHEN MATCHED THEN
                        UPDATE SET
                            DocumentId = ?,
                            SourcePath = ?,
                            Position = ?,
                            ChunkIndex = ?,
                            TextContent = ?,
                            TokenCount = ?,
                            PageNumber = ?,
                            Heading = ?,
                            Checksum = ?,
                            ModifiedAt = ?
                    WHEN NOT MATCHED THEN
                        INSERT (
                            ChunkId,
                            DocumentId,
                            SourcePath,
                            Position,
                            ChunkIndex,
                            TextContent,
                            TokenCount,
                            PageNumber,
                            Heading,
                            Checksum,
                            CreatedAt,
                            ModifiedAt
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        chunk.chunk_id,
                        document_id,
                        parsed_document.source_path.as_posix(),
                        chunk.metadata.position,
                        chunk.metadata.chunk_index,
                        chunk.text,
                        chunk.metadata.token_count,
                        chunk.metadata.page_number,
                        chunk.metadata.heading,
                        parsed_document.checksum,
                        now,
                        chunk.chunk_id,
                        document_id,
                        parsed_document.source_path.as_posix(),
                        chunk.metadata.position,
                        chunk.metadata.chunk_index,
                        chunk.text,
                        chunk.metadata.token_count,
                        chunk.metadata.page_number,
                        chunk.metadata.heading,
                        parsed_document.checksum,
                        now,
                        now,
                    ),
                )
                stored_chunks.append(
                    StoredChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=document_id,
                        source_path=parsed_document.source_path.as_posix(),
                        position=chunk.metadata.position,
                        chunk_index=chunk.metadata.chunk_index,
                        text=chunk.text,
                        token_count=chunk.metadata.token_count,
                        page_number=chunk.metadata.page_number,
                        heading=chunk.metadata.heading,
                        checksum=parsed_document.checksum,
                        created_at=now,
                    )
                )
            connection.commit()

        return stored_chunks

    def _upsert_embeddings(self, chunks: list[StoredChunk], embedding_result: EmbeddingBatchResult) -> list[StoredEmbedding]:
        now = datetime.now(timezone.utc)
        by_chunk_id = {record.chunk_id: record for record in embedding_result.records}
        stored_embeddings: list[StoredEmbedding] = []

        with self._connect() as connection:
            cursor = connection.cursor()
            for stored_chunk in chunks:
                record = by_chunk_id.get(stored_chunk.chunk_id)
                if record is None:
                    continue
                cursor.execute(
                    """
                    MERGE AI.ChunkEmbeddings AS target
                    USING (SELECT ? AS EmbeddingId) AS source
                    ON target.EmbeddingId = source.EmbeddingId
                    WHEN MATCHED THEN
                        UPDATE SET
                            ChunkId = ?,
                            ModelName = ?,
                            VectorSize = ?,
                            VectorJson = ?,
                            MetadataJson = ?,
                            ModifiedAt = ?
                    WHEN NOT MATCHED THEN
                        INSERT (
                            EmbeddingId,
                            ChunkId,
                            ModelName,
                            VectorSize,
                            VectorJson,
                            MetadataJson,
                            CreatedAt,
                            ModifiedAt
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        record.embedding_id,
                        stored_chunk.chunk_id,
                        record.model_name,
                        len(record.vector),
                        self._serialize_vector(record.vector),
                        self._serialize_metadata(record.metadata),
                        now,
                        record.embedding_id,
                        stored_chunk.chunk_id,
                        record.model_name,
                        len(record.vector),
                        self._serialize_vector(record.vector),
                        self._serialize_metadata(record.metadata),
                        now,
                        now,
                    ),
                )
                stored_embeddings.append(
                    StoredEmbedding(
                        embedding_id=record.embedding_id,
                        chunk_id=stored_chunk.chunk_id,
                        model_name=record.model_name,
                        vector_size=len(record.vector),
                        created_at=now,
                        metadata=dict(record.metadata),
                    )
                )
            connection.commit()

        return stored_embeddings

    def _connect(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)

    def _build_connection_string(self) -> str:
        return (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER={self._settings.sql_server},{self._settings.sql_port};"
            f"DATABASE={self._settings.sql_database};"
            f"UID={self._settings.sql_user};"
            f"PWD={self._settings.sql_password};"
            "Encrypt=no;"
            "TrustServerCertificate=yes;"
            "Connection Timeout=5;"
        )

    def _serialize_vector(self, vector: tuple[float, ...]) -> str:
        return ",".join(f"{value:.8f}" for value in vector)

    def _serialize_metadata(self, metadata: dict[str, Any]) -> str:
        import json

        return json.dumps(metadata, ensure_ascii=False, sort_keys=True)

    def _row_to_document(self, row: Any) -> StoredDocument:
        import json

        return StoredDocument(
            document_id=row.DocumentId,
            source_path=row.SourcePath,
            title=row.Title,
            parser_kind=row.ParserKind,
            object_type=row.ObjectType,
            checksum=row.Checksum,
            language=row.Language,
            page_count=row.PageCount,
            line_count=row.LineCount,
            character_count=row.CharacterCount,
            created_at=row.CreatedAt,
            modified_at=row.ModifiedAt,
            metadata=json.loads(row.MetadataJson or "{}"),
        )
