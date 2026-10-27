from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api import dependencies
from backend.api.schemas import (
    DocumentDeleteResponse,
    DocumentSummary,
    IngestResponse,
    QueueSummary,
    ScanResponse,
    StatsSummary,
    WorkerMetricsResponse,
    WorkerStatusResponse,
)
from backend.workers.processing_worker import ProcessingWorker

router = APIRouter(prefix="/api", tags=["api"])


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
    results = worker.run_until_empty()
    return ScanResponse(processed=len(results), details=[result.file_path for result in results])


@router.post("/ingest", response_model=IngestResponse)
def ingest(worker: ProcessingWorker = Depends(dependencies.get_processing_worker)) -> IngestResponse:
    result = worker.run_once()
    if result is None:
        return IngestResponse(status="idle", processed=0, details=[])
    return IngestResponse(status=result.outcome.value, processed=1, details=[result.file_path])


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(document_repository=Depends(dependencies.get_document_repository)) -> list[DocumentSummary]:
    documents = document_repository.list_documents()
    return [DocumentSummary.model_validate(document) for document in documents]


@router.get("/documents/{document_id}", response_model=DocumentSummary)
def get_document(document_id: str, document_repository=Depends(dependencies.get_document_repository)) -> DocumentSummary:
    document = document_repository.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found.")
    return DocumentSummary.model_validate(document)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found.")
    return DocumentDeleteResponse(
        success=True,
        message="Document deleted",
        document_id=document_id,
    )
