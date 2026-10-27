from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api import dependencies
from backend.api.schemas import (
    DocumentSummary,
    IngestResponse,
    QueueSummary,
    ScanResponse,
    StatsSummary,
)
from backend.workers.processing_worker import ProcessingWorker

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/status")
def get_status() -> dict[str, str]:
    return {"status": "ok", "service": "local-knowledge-ai"}


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
    summary = document_repository.get_statistics()
    return StatsSummary(
        documents=summary.documents,
        chunks=summary.chunks,
        embeddings=summary.embeddings,
        conversations=summary.conversations,
        prompts=summary.prompts,
        models=summary.models,
    )


@router.delete("/document/{document_id}")
def delete_document(document_id: str, document_repository=Depends(dependencies.get_document_repository)) -> dict[str, Any]:
    deleted = document_repository.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found.")
    return {"deleted": document_id}
