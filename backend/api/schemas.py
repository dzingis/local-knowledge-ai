from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.chunking.chunk_engine import ChunkingResult
from backend.embeddings.embedding_service import EmbeddingBatchResult
from backend.parsers.parser_models import ParsedDocument


class ScanRequest(BaseModel):
    root_path: str | None = None
    recursive: bool = True


class ReindexRequest(BaseModel):
    root_path: str | None = None
    force: bool = False


class IngestRequest(BaseModel):
    file_path: str


class DocumentSummary(BaseModel):
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


class ChunkSummary(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    token_count: int
    position: int
    chunk_index: int


class EmbeddingSummary(BaseModel):
    chunk_id: str
    model_name: str
    dimensions: int
    vector: tuple[float, ...] = Field(default_factory=tuple)


class QueueItemSummary(BaseModel):
    file_name: str
    full_path: str
    status: str
    change_type: str
    retry_count: int = 0
    error_message: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "local-knowledge-ai"
    timestamp: datetime | None = None


class StatsResponse(BaseModel):
    documents: int = 0
    chunks: int = 0
    embeddings: int = 0
    queue_items: int = 0
    conversations: int = 0
    prompts: int = 0
    models: int = 0


class ApiErrorResponse(BaseModel):
    detail: str
    context: dict[str, Any] | None = None


class DocumentDetailResponse(BaseModel):
    document: DocumentSummary
    parsed_document: ParsedDocument | None = None
    chunking_result: ChunkingResult | None = None
    embedding_result: EmbeddingBatchResult | None = None


class DocumentsResponse(BaseModel):
    documents: tuple[DocumentSummary, ...] = ()


class QueueResponse(BaseModel):
    items: tuple[QueueItemSummary, ...] = ()


class OperationResponse(BaseModel):
    success: bool
    message: str
    path: str | None = None
    document_id: str | None = None
