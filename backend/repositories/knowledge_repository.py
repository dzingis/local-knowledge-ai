from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID, uuid4

import pyodbc

from backend.config.settings import get_settings
from backend.chunking.chunk_engine import Chunk
from backend.embeddings.embedding_service import EmbeddingBatchResult
from backend.parsers.parser_models import ParsedDocument
from backend.vectorstore.qdrant_repository import QdrantRepository


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    document_id: str
    source_path: str
    title: str
    parser_kind: str
    object_type: str
    checksum: str | None
    line_count: int | None
    character_count: int


@dataclass(frozen=True, slots=True)
class SearchableChunk:
    chunk_id: str
    document_id: str
    source_path: str
    title: str
    text: str
    page_number: int | None
    heading: str | None
    keyword_matches: int = 0


class KnowledgeRepository:
    """Persists indexed content using the AI schema in the database bootstrap script."""

    def __init__(
        self,
        connection_string: str | None = None,
        qdrant_repository: QdrantRepository | None = None,
    ) -> None:
        self._settings = get_settings()
        self._connection_string = connection_string or self._build_connection_string()
        self._qdrant_repository = qdrant_repository

    def ensure_document_record(
        self,
        parsed: ParsedDocument,
        modified_at: datetime,
        file_size_bytes: int,
        file_checksum: str,
    ) -> str:
        """Create or refresh document identity before graph provenance is stored."""
        source_path = str(parsed.source_path)
        document_id = str(uuid4())
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            try:
                cursor = connection.cursor()
                existing = cursor.execute(
                    """
                    SELECT DocumentId FROM AI.Document
                    WHERE OriginalPath = ? AND IsDeleted = 0;
                    """,
                    (source_path,),
                ).fetchone()
                if existing is not None:
                    document_id = str(existing.DocumentId)
                    cursor.execute(
                        """
                        UPDATE AI.Document
                        SET FileName = ?, Extension = ?, FileSize = ?, SHA256 = ?,
                            Modified = ?, IsDeleted = 0
                        WHERE DocumentId = ?;
                        """,
                        (
                            Path(source_path).name,
                            Path(source_path).suffix,
                            file_size_bytes,
                            file_checksum,
                            modified_at,
                            document_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO AI.Document (
                            DocumentId, FileName, OriginalPath, RelativePath, Extension,
                            FileSize, SHA256, Created, Modified, Indexed, IsDeleted
                        )
                        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, 0);
                        """,
                        (
                            document_id,
                            Path(source_path).name,
                            source_path,
                            Path(source_path).suffix,
                            file_size_bytes,
                            file_checksum,
                            now,
                            modified_at,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return document_id

    def store_indexed_document(
        self,
        parsed: ParsedDocument,
        chunks: Sequence[Chunk],
        embeddings: EmbeddingBatchResult,
        modified_at: datetime,
        file_size_bytes: int,
        file_checksum: str,
    ) -> tuple[str, tuple[str, ...]]:
        source_path = str(parsed.source_path)
        document_id = str(uuid4())
        now = datetime.now(timezone.utc)
        stale_chunk_ids: list[str] = []

        with self._connect() as connection:
            try:
                cursor = connection.cursor()
                existing = cursor.execute(
                    """
                    SELECT DocumentId
                    FROM AI.Document
                    WHERE OriginalPath = ? AND IsDeleted = 0;
                    """,
                    (source_path,),
                ).fetchone()

                if existing is not None:
                    document_id = str(existing.DocumentId)
                    stale_chunk_ids = [
                        str(row.ChunkId)
                        for row in cursor.execute(
                            "SELECT ChunkId FROM AI.DocumentChunk WHERE DocumentId = ?;",
                            (document_id,),
                        ).fetchall()
                    ]
                    cursor.execute(
                        """
                        DELETE FROM AI.Embedding
                        WHERE ChunkId IN (
                            SELECT ChunkId FROM AI.DocumentChunk WHERE DocumentId = ?
                        );
                        """,
                        (document_id,),
                    )
                    cursor.execute("DELETE FROM AI.DocumentChunk WHERE DocumentId = ?;", (document_id,))
                    cursor.execute(
                        """
                        UPDATE AI.Document
                        SET FileName = ?, Extension = ?, FileSize = ?, SHA256 = ?,
                            Modified = ?, Indexed = ?, IsDeleted = 0
                        WHERE DocumentId = ?;
                        """,
                        (
                            Path(source_path).name,
                            Path(source_path).suffix,
                            file_size_bytes,
                            file_checksum,
                            modified_at,
                            now,
                            document_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO AI.Document (
                            DocumentId, FileName, OriginalPath, RelativePath, Extension,
                            FileSize, SHA256, Created, Modified, Indexed, IsDeleted
                        )
                        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 0);
                        """,
                        (
                            document_id,
                            Path(source_path).name,
                            source_path,
                            Path(source_path).suffix,
                            file_size_bytes,
                            file_checksum,
                            now,
                            modified_at,
                            now,
                        ),
                    )

                cursor.execute(
                    """
                    INSERT INTO AI.DocumentVersion (DocumentId, VersionNumber, SHA256, Indexed)
                    SELECT ?, ISNULL(MAX(VersionNumber), 0) + 1, ?, ?
                    FROM AI.DocumentVersion
                    WHERE DocumentId = ?;
                    """,
                    (document_id, file_checksum, now, document_id),
                )

                records_by_chunk_id = {record.chunk_id: record for record in embeddings.records}
                for chunk in chunks:
                    cursor.execute(
                        """
                        INSERT INTO AI.DocumentChunk (
                            ChunkId, DocumentId, ChunkNumber, PageNumber, ChunkText,
                            TokenCount, VectorId
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            chunk.chunk_id,
                            document_id,
                            chunk.metadata.chunk_index,
                            chunk.metadata.page_number,
                            chunk.text,
                            chunk.metadata.token_count,
                            chunk.chunk_id,
                        ),
                    )
                    record = records_by_chunk_id.get(chunk.chunk_id)
                    if record is not None:
                        cursor.execute(
                            """
                            INSERT INTO AI.Embedding (ChunkId, QModel, QVectorId, Created)
                            VALUES (?, ?, ?, ?);
                            """,
                            (chunk.chunk_id, record.model_name, chunk.chunk_id, now),
                        )

                if file_checksum:
                    cursor.execute(
                        """
                        MERGE AI.FileHash AS target
                        USING (SELECT ? AS SHA256) AS source
                        ON target.SHA256 = source.SHA256
                        WHEN MATCHED THEN
                            UPDATE SET LastSeen = ?, FileCount = ISNULL(target.FileCount, 0) + 1
                        WHEN NOT MATCHED THEN
                            INSERT (SHA256, FirstSeen, LastSeen, FileCount)
                            VALUES (?, ?, ?, 1);
                        """,
                        (file_checksum, now, file_checksum, now, now),
                    )

                connection.commit()
            except Exception:
                connection.rollback()
                raise

        retained_ids = {chunk.chunk_id for chunk in chunks}
        return document_id, tuple(chunk_id for chunk_id in stale_chunk_ids if chunk_id not in retained_ids)

    def get_chunks(
        self,
        chunk_ids: Sequence[str],
        extensions: Sequence[str] | None = None,
    ) -> dict[str, SearchableChunk]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        extension_clause = ""
        parameters: tuple[object, ...] = tuple(chunk_ids)
        if extensions:
            extension_clause = f" AND LOWER(d.Extension) IN ({','.join('?' for _ in extensions)})"
            parameters += tuple(extension.casefold() for extension in extensions)
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"""
                SELECT c.ChunkId, c.DocumentId, d.OriginalPath, d.FileName,
                       c.ChunkText, c.PageNumber, CAST(NULL AS NVARCHAR(1000)) AS Heading
                FROM AI.DocumentChunk AS c
                INNER JOIN AI.Document AS d ON d.DocumentId = c.DocumentId
                WHERE d.IsDeleted = 0 AND c.ChunkId IN ({placeholders}){extension_clause};
                """,
                parameters,
            ).fetchall()
        return {
            str(row.ChunkId): SearchableChunk(
                chunk_id=str(row.ChunkId),
                document_id=str(row.DocumentId),
                source_path=str(row.OriginalPath),
                title=str(row.FileName),
                text=str(row.ChunkText or ""),
                page_number=row.PageNumber,
                heading=row.Heading,
            )
            for row in rows
        }

    def search_chunks_by_terms(
        self,
        terms: Sequence[str],
        limit: int,
        extensions: Sequence[str] | None = None,
    ) -> tuple[SearchableChunk, ...]:
        unique_terms = tuple(dict.fromkeys(term for term in terms if len(term) > 1))
        if not unique_terms:
            return ()
        conditions = " OR ".join("c.ChunkText LIKE ?" for _ in unique_terms)
        ranking = " + ".join("CASE WHEN c.ChunkText LIKE ? THEN 1 ELSE 0 END" for _ in unique_terms)
        patterns = tuple(f"%{term.replace('[', '[[]').replace('%', '[%]').replace('_', '[_]')}%" for term in unique_terms)
        extension_clause = ""
        extension_parameters: tuple[str, ...] = ()
        if extensions:
            extension_clause = f" AND LOWER(d.Extension) IN ({','.join('?' for _ in extensions)})"
            extension_parameters = tuple(extension.casefold() for extension in extensions)
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"""
                SELECT TOP (?) c.ChunkId, c.DocumentId, d.OriginalPath, d.FileName,
                       c.ChunkText, c.PageNumber,
                       CAST(NULL AS NVARCHAR(1000)) AS Heading,
                       ({ranking}) AS KeywordMatches
                FROM AI.DocumentChunk AS c
                INNER JOIN AI.Document AS d ON d.DocumentId = c.DocumentId
                WHERE d.IsDeleted = 0 AND ({conditions}){extension_clause}
                ORDER BY KeywordMatches DESC, c.ChunkNumber ASC;
                """,
                (limit, *patterns, *patterns, *extension_parameters),
            ).fetchall()
        return tuple(
            SearchableChunk(
                chunk_id=str(row.ChunkId),
                document_id=str(row.DocumentId),
                source_path=str(row.OriginalPath),
                title=str(row.FileName),
                text=str(row.ChunkText or ""),
                page_number=row.PageNumber,
                heading=row.Heading,
                keyword_matches=int(row.KeywordMatches or 0),
            )
            for row in rows
        )

    def search_chunks_by_phrase(
        self,
        phrase: str,
        limit: int,
        extensions: Sequence[str] | None = None,
    ) -> tuple[SearchableChunk, ...]:
        normalized_phrase = phrase.strip()
        if not normalized_phrase:
            return ()
        pattern = (
            normalized_phrase.replace("[", "[[]")
            .replace("%", "[%]")
            .replace("_", "[_]")
        )
        extension_clause = ""
        extension_parameters: tuple[str, ...] = ()
        if extensions:
            extension_clause = f" AND LOWER(d.Extension) IN ({','.join('?' for _ in extensions)})"
            extension_parameters = tuple(extension.casefold() for extension in extensions)
        with self._connect() as connection:
            rows = connection.cursor().execute(
                f"""
                SELECT TOP (?) c.ChunkId, c.DocumentId, d.OriginalPath, d.FileName,
                       c.ChunkText, c.PageNumber,
                       CAST(NULL AS NVARCHAR(1000)) AS Heading
                FROM AI.DocumentChunk AS c
                INNER JOIN AI.Document AS d ON d.DocumentId = c.DocumentId
                WHERE d.IsDeleted = 0 AND c.ChunkText LIKE ?{extension_clause}
                ORDER BY c.ChunkNumber ASC;
                """,
                (limit, f"%{pattern}%", *extension_parameters),
            ).fetchall()
        return tuple(
            SearchableChunk(
                chunk_id=str(row.ChunkId),
                document_id=str(row.DocumentId),
                source_path=str(row.OriginalPath),
                title=str(row.FileName),
                text=str(row.ChunkText or ""),
                page_number=row.PageNumber,
                heading=row.Heading,
                keyword_matches=len(normalized_phrase.split()),
            )
            for row in rows
        )

    def list_documents(self) -> tuple[KnowledgeDocument, ...]:
        with self._connect() as connection:
            rows = connection.cursor().execute(
                """
                SELECT DocumentId, OriginalPath, FileName, Extension, SHA256
                FROM AI.Document
                WHERE IsDeleted = 0
                ORDER BY Modified DESC;
                """
            ).fetchall()
        return tuple(self._document_from_row(row) for row in rows)

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        try:
            normalized_id = str(UUID(document_id))
        except ValueError:
            return None
        with self._connect() as connection:
            row = connection.cursor().execute(
                """
                SELECT DocumentId, OriginalPath, FileName, Extension, SHA256
                FROM AI.Document
                WHERE DocumentId = ? AND IsDeleted = 0;
                """,
                (normalized_id,),
            ).fetchone()
        return self._document_from_row(row) if row is not None else None

    def delete_document(self, document_id: str) -> bool:
        try:
            normalized_id = str(UUID(document_id))
        except ValueError:
            return False
        with self._connect() as connection:
            cursor = connection.cursor()
            chunk_ids = [
                str(row.ChunkId)
                for row in cursor.execute(
                    "SELECT ChunkId FROM AI.DocumentChunk WHERE DocumentId = ?;",
                    (normalized_id,),
                ).fetchall()
            ]
            cursor.execute(
                """
                UPDATE AI.Document
                SET IsDeleted = 1, Indexed = ?
                WHERE DocumentId = ? AND IsDeleted = 0;
                """,
                (datetime.now(timezone.utc), normalized_id),
            )
            deleted = cursor.rowcount > 0
            connection.commit()
        if deleted and self._qdrant_repository is not None and chunk_ids:
            self._qdrant_repository.delete_embeddings(chunk_ids)
        return deleted

    def get_stats(self) -> dict[str, int]:
        with self._connect() as connection:
            cursor = connection.cursor()
            documents = cursor.execute("SELECT COUNT(*) AS Cnt FROM AI.Document WHERE IsDeleted = 0;").fetchone()
            chunks = cursor.execute(
                """
                SELECT COUNT(*) AS Cnt
                FROM AI.DocumentChunk AS c
                INNER JOIN AI.Document AS d ON d.DocumentId = c.DocumentId
                WHERE d.IsDeleted = 0;
                """
            ).fetchone()
            embeddings = cursor.execute(
                """
                SELECT COUNT(*) AS Cnt
                FROM AI.Embedding AS e
                INNER JOIN AI.DocumentChunk AS c ON c.ChunkId = e.ChunkId
                INNER JOIN AI.Document AS d ON d.DocumentId = c.DocumentId
                WHERE d.IsDeleted = 0;
                """
            ).fetchone()
        return {
            "documents": int(documents.Cnt or 0),
            "chunks": int(chunks.Cnt or 0),
            "embeddings": int(embeddings.Cnt or 0),
            "conversations": 0,
            "prompts": 0,
            "models": 0,
        }

    def _document_from_row(self, row: Any) -> KnowledgeDocument:
        return KnowledgeDocument(
            document_id=str(row.DocumentId),
            source_path=str(row.OriginalPath),
            title=str(row.FileName),
            parser_kind=str(row.Extension or "").lstrip("."),
            object_type="document",
            checksum=str(row.SHA256).strip() if row.SHA256 else None,
            line_count=None,
            character_count=0,
        )

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

    def _connect(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)
