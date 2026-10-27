from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.chunking.chunk_engine import ChunkingResult
from backend.embeddings.embedding_service import EmbeddingBatchResult
from backend.parsers.parser_models import ParsedDocument


@dataclass(frozen=True, slots=True)
class ScanRequest:
    root_path: str | None = None
    recursive: bool = True


@dataclass(frozen=True, slots=True)
class ReindexRequest:
    root_path: str | None = None
    force: bool = False


@dataclass(frozen=True, slots=True)
class IngestRequest:
    file_path: str


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    document_id: str
    source_path: str
    title: str
    parser_kind: str
    object_type: str
    checksum: str | None = None
    line_count: int | None = None
    character_count: int = 0

    @classmethod
    def from_parsed_document(cls, document: ParsedDocument) -> "DocumentSummary":
        return cls(
            document_id=str(document.source_path),
            source_path=str(document.source_path),
            title=document.title,
            parser_kind=document.parser_kind.value,
            object_type=document.object_type.value,
            checksum=document.checksum,
            line_count=document.line_count,
            character_count=document.character_count,
        )


@dataclass(frozen=True, slots=True)
class ChunkSummary:
    chunk_id: str
    document_id: str
    text: str
    token_count: int
    position: int
    chunk_index: int


@dataclass(frozen=True, slots=True)
class EmbeddingSummary:
    chunk_id: str
    model_name: str
    dimensions: int
    vector: tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class QueueItemSummary:
    file_name: str
    full_path: str
    status: str
    change_type: str
    retry_count: int = 0
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class HealthResponse:
    status: str = "ok"
    service: str = "local-knowledge-ai"
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class StatsResponse:
    documents: int = 0
    chunks: int = 0
    embeddings: int = 0
    queue_items: int = 0
    conversations: int = 0
    prompts: int = 0
    models: int = 0


@dataclass(frozen=True, slots=True)
class ApiErrorResponse:
    detail: str
    context: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DocumentDetailResponse:
    document: DocumentSummary
    parsed_document: ParsedDocument | None = None
    chunking_result: ChunkingResult | None = None
    embedding_result: EmbeddingBatchResult | None = None


@dataclass(frozen=True, slots=True)
class DocumentsResponse:
    documents: tuple[DocumentSummary, ...] = ()


@dataclass(frozen=True, slots=True)
class QueueResponse:
    items: tuple[QueueItemSummary, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationResponse:
    success: bool
    message: str
    path: str | None = None
    document_id: str | None = None
