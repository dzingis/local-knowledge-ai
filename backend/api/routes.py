from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/status")
def get_status() -> dict[str, str]:
    return {"status": "ok", "service": "local-knowledge-ai"}


@router.post("/scan")
def scan() -> dict[str, str]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Scan endpoint not implemented yet.")


@router.post("/reindex")
def reindex() -> dict[str, str]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reindex endpoint not implemented yet.")


@router.post("/ingest")
def ingest() -> dict[str, str]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Ingest endpoint not implemented yet.")


@router.get("/documents")
def list_documents() -> dict[str, list[dict[str, str]]]:
    return {"documents": []}


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> dict[str, str]:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found.")


@router.get("/queue")
def get_queue() -> dict[str, list[dict[str, str]]]:
    return {"items": []}


@router.get("/stats")
def get_stats() -> dict[str, int]:
    return {"documents": 0, "chunks": 0, "embeddings": 0, "queue_items": 0}


@router.delete("/document/{document_id}")
def delete_document(document_id: str) -> dict[str, str]:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=f"Delete for {document_id} not implemented yet.")
