from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=4000,
        description=(
            "Question or search phrase in Croatian or English. Prefix with SQL:, PDF:, "
            "DOCX:, DELPHI:, MARKDOWN:, or TEXT: to restrict file types; without a "
            "prefix all file types are searched. / Pitanje ili izraz za pretraživanje "
            "na hrvatskom ili engleskom. Prefiksom SQL:, PDF:, DOCX:, DELPHI:, "
            "MARKDOWN: ili TEXT: ograničite vrste datoteka; bez prefiksa pretražuju "
            "se sve vrste."
        ),
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of passages. / Najveći broj odlomaka.",
    )


class SearchHitResponse(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    source_path: str
    text: str
    score: float
    page_number: int | None = None
    heading: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHitResponse] = Field(default_factory=list)


class GraphEntityResponse(BaseModel):
    entity_id: str
    name: str
    normalized_name: str
    entity_type: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)
    source_document_ids: list[str] = Field(default_factory=list)


class GraphRelationshipResponse(BaseModel):
    relationship_id: str
    source_entity_id: str
    source_name: str | None = None
    target_entity_id: str
    target_name: str | None = None
    relationship_type: str
    confidence: float = Field(ge=0, le=1)
    source_document_id: str | None = None
    evidence: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphDocumentResponse(BaseModel):
    document_id: str
    source_path: str
    entities: list[GraphEntityResponse] = Field(default_factory=list)
    relationships: list[GraphRelationshipResponse] = Field(default_factory=list)


class GraphStatisticsResponse(BaseModel):
    entity_count: int
    relationship_count: int
    entity_types: dict[str, int]
    most_connected: list[tuple[str, int]]
    orphan_entity_count: int
    average_degree: float


class GraphOperationResponse(BaseModel):
    success: bool
    documents_processed: int = 0
    entities_processed: int = 0
    relationships_processed: int = 0
    message: str


class OpenAIChatMessage(BaseModel):
    role: Literal["system", "developer", "user", "assistant"]
    content: str


class OpenAIChatCompletionRequest(BaseModel):
    model: str
    messages: list[OpenAIChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)


class IngestResponse(BaseModel):
    status: str
    processed: int = 0
    details: list[str] = Field(default_factory=list)


class ScanResponse(BaseModel):
    processed: int = 0
    details: list[str] = Field(default_factory=list)


class WorkerStatusResponse(BaseModel):
    worker_id: str
    running: bool
    locked: bool
    status: str
    iterations: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    current_file: str | None = None
    last_error: str | None = None
    average_duration_ms: float = 0.0


class QueueSummary(BaseModel):
    worker_id: str
    status: str
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    current_file: str | None = None
    last_error: str | None = None


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


class StatsSummary(BaseModel):
    documents: int = 0
    chunks: int = 0
    embeddings: int = 0
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


class DocumentDeleteResponse(BaseModel):
    success: bool
    message: str
    document_id: str | None = None
    chunks_deleted: int = 0
    embeddings_deleted: int = 0
    vectors_deleted: int = 0


class WorkerMetricsResponse(BaseModel):
    worker_id: str
    running: bool
    locked: bool
    paused: bool
    iterations: int
    processed: int
    recovered_items: int = 0
    idle_iterations: int = 0
    current_interval_seconds: float = 0.0
    last_heartbeat_at: datetime | None = None
    last_result_file: str | None = None
    last_result_outcome: str | None = None
