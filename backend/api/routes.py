from __future__ import annotations

import codecs
from datetime import datetime, timezone
import json
import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
import requests

from backend.api import dependencies
from backend.api.schemas import (
    DocumentDeleteResponse,
    DocumentSummary,
    IngestResponse,
    OpenAIChatCompletionRequest,
    QueueSummary,
    SearchHitResponse,
    SearchRequest,
    SearchResponse,
    ScanResponse,
    StatsSummary,
    WorkerMetricsResponse,
    WorkerStatusResponse,
)
from backend.workers.processing_worker import ProcessingWorker
from backend.search.service import KnowledgeSearchService
from backend.chat.ollama_chat import ChatMessage, OllamaRagChatService
from backend.config.settings import get_settings

router = APIRouter(prefix="/api", tags=["api"])
openai_router = APIRouter(prefix="/v1", tags=["openai-compatible"])


@router.get("/status")
def get_status() -> dict[str, str]:
    return {"status": "ok", "service": "local-knowledge-ai"}


@router.get("/worker/status", response_model=WorkerStatusResponse)
def get_worker_status(worker: ProcessingWorker = Depends(dependencies.get_processing_worker)) -> WorkerStatusResponse:
    progress = worker.progress
    return WorkerStatusResponse(
        worker_id=progress.worker_id,
        running=progress.status.value == "running",
        locked=False,
        status=progress.status.value,
        iterations=getattr(progress, "iterations", 0),
        processed=progress.processed,
        succeeded=progress.succeeded,
        failed=progress.failed,
        retried=progress.retried,
        current_file=progress.current_file,
        last_error=progress.last_error,
        average_duration_ms=progress.average_duration_ms,
    )


@router.get("/worker/metrics", response_model=WorkerMetricsResponse)
def get_worker_metrics(worker: ProcessingWorker = Depends(dependencies.get_processing_worker)) -> WorkerMetricsResponse:
    background_service = dependencies.get_background_worker_service()
    state = background_service.state
    last_result = state.last_result
    return WorkerMetricsResponse(
        worker_id=dependencies.get_background_worker_service_worker_id(),
        running=state.running,
        locked=state.locked,
        paused=getattr(state, "paused", False),
        iterations=state.iterations,
        processed=state.processed,
        recovered_items=state.recovered_items,
        idle_iterations=state.idle_iterations,
        current_interval_seconds=state.current_interval_seconds,
        last_heartbeat_at=state.last_heartbeat_at,
        last_result_file=last_result.file_path if last_result is not None else None,
        last_result_outcome=last_result.outcome.value if last_result is not None else None,
    )


@router.post("/scan", response_model=ScanResponse)
def scan(worker: ProcessingWorker = Depends(dependencies.get_processing_worker)) -> ScanResponse:
    results = worker.run_until_empty()
    return ScanResponse(processed=len(results), details=[result.file_path for result in results])


@router.post("/reindex", response_model=ScanResponse)
def reindex(worker: ProcessingWorker = Depends(dependencies.get_processing_worker)) -> ScanResponse:
    queued = dependencies.get_sql_queue_repository().requeue_completed()
    results = worker.run_until_empty()
    return ScanResponse(processed=max(queued, len(results)), details=[result.file_path for result in results])


@router.post("/ingest", response_model=IngestResponse)
def ingest(worker: ProcessingWorker = Depends(dependencies.get_processing_worker)) -> IngestResponse:
    result = worker.run_once()
    if result is None:
        return IngestResponse(status="idle", processed=0, details=[])
    return IngestResponse(status=result.outcome.value, processed=1, details=[result.file_path])


@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest,
    search_service: KnowledgeSearchService = Depends(dependencies.get_search_service),
) -> SearchResponse:
    results = search_service.search(request.query, limit=request.limit)
    return SearchResponse(
        query=request.query,
        results=[
            SearchHitResponse(
                chunk_id=result.chunk.chunk_id,
                document_id=result.chunk.document_id,
                title=result.chunk.title,
                source_path=result.chunk.source_path,
                text=result.chunk.text,
                score=result.score,
                page_number=result.chunk.page_number,
                heading=result.chunk.heading,
            )
            for result in results
        ],
    )


@openai_router.get("/models")
def list_openai_models(
    chat_service: OllamaRagChatService = Depends(dependencies.get_chat_service),
) -> dict[str, object]:
    now = int(datetime.now(timezone.utc).timestamp())
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "created": now, "owned_by": "ollama"}
            for model in chat_service.list_models()
        ],
    }


@openai_router.post("/chat/completions", response_model=None)
def create_chat_completion(
    request: OpenAIChatCompletionRequest,
    chat_service: OllamaRagChatService = Depends(dependencies.get_chat_service),
) -> Any:
    try:
        completion = chat_service.complete(
            model=request.model,
            messages=tuple(ChatMessage(role=message.role, content=message.content) for message in request.messages),
            temperature=request.temperature,
        )
    except requests.Timeout as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "The local chat model took too long to respond. Try again or select a smaller model. "
                "/ Lokalnom modelu trebalo je predugo za odgovor. Pokušajte ponovno ili odaberite manji model."
            ),
        ) from exc
    completion_id = f"chatcmpl-{uuid4().hex}"
    created = int(datetime.now(timezone.utc).timestamp())
    if request.stream:
        def stream_response():
            content = completion.content
            for start in range(0, len(content), 64):
                event = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": completion.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": content[start : start + 64]},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            final_event = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": completion.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final_event)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": completion.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": completion.content},
                "finish_reason": "stop",
            }
        ],
    }


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(document_repository=Depends(dependencies.get_document_repository)) -> list[DocumentSummary]:
    documents = document_repository.list_documents()
    return [DocumentSummary.model_validate(document) for document in documents]


@router.get("/documents/{document_id}", response_model=DocumentSummary)
def get_document(document_id: str, document_repository=Depends(dependencies.get_document_repository)) -> DocumentSummary:
    document = document_repository.get_document(document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dokument {document_id} nije pronađen. / Document {document_id} was not found.",
        )
    return DocumentSummary.model_validate(document)


@router.get("/documents/{document_id}/source", response_class=FileResponse)
def get_document_source(
    document_id: str,
    download: bool = False,
    document_repository=Depends(dependencies.get_document_repository),
) -> FileResponse:
    document = document_repository.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    try:
        source_path = Path(document.source_path).resolve(strict=True)
    except (OSError, RuntimeError):
        source_path = None
    if source_path is None or not source_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source file is unavailable.")

    allowed_roots = get_settings().watch_folders
    if allowed_roots:
        resolved_roots = [Path(root).resolve() for root in allowed_roots]
        if not any(source_path == root or root in source_path.parents for root in resolved_roots):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source file is unavailable.")

    media_type, _ = mimetypes.guess_type(document.title)
    if media_type is not None and (media_type.startswith("text/") or media_type == "application/json"):
        try:
            decoder = codecs.getincrementaldecoder("utf-8-sig")()
            with source_path.open("rb") as source_file:
                while block := source_file.read(64 * 1024):
                    decoder.decode(block)
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            charset = "windows-1250"
        else:
            charset = "utf-8"
        media_type = f"{media_type}; charset={charset}"
    return FileResponse(
        source_path,
        media_type=media_type or "application/octet-stream",
        filename=document.title,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/queue", response_model=QueueSummary)
def get_queue(worker: ProcessingWorker = Depends(dependencies.get_processing_worker)) -> QueueSummary:
    progress = worker.progress
    return QueueSummary(
        worker_id=progress.worker_id,
        status=progress.status.value,
        processed=progress.processed,
        succeeded=progress.succeeded,
        failed=progress.failed,
        retried=progress.retried,
        current_file=progress.current_file,
        last_error=progress.last_error,
    )


@router.get("/stats", response_model=StatsSummary)
def get_stats(document_repository=Depends(dependencies.get_document_repository)) -> StatsSummary:
    summary = document_repository.get_stats()
    return StatsSummary(
        documents=summary["documents"],
        chunks=summary["chunks"],
        embeddings=summary["embeddings"],
        conversations=summary["conversations"],
        prompts=summary["prompts"],
        models=summary["models"],
    )


@router.delete("/document/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(document_id: str, document_repository=Depends(dependencies.get_document_repository)) -> DocumentDeleteResponse:
    deleted = document_repository.delete_document(document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dokument {document_id} nije pronađen. / Document {document_id} was not found.",
        )
    return DocumentDeleteResponse(
        success=True,
        message="Document deleted",
        document_id=document_id,
    )
