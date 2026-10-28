from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from qdrant_client import QdrantClient
from qdrant_client.http import models

from backend.embeddings.embedding_service import EmbeddingRecord


@dataclass(frozen=True, slots=True)
class QdrantPayload:
    chunk_id: str
    document_id: str
    source_path: str
    source_name: str
    source_type: str
    title: str
    checksum: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QdrantPoint:
    id: str
    vector: tuple[float, ...]
    payload: QdrantPayload


@dataclass(frozen=True, slots=True)
class QdrantSearchHit:
    id: str
    score: float
    payload: QdrantPayload
    vector: tuple[float, ...] | None = None


class QdrantClientProtocol(Protocol):
    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        ...

    def upsert_points(self, collection_name: str, points: list[QdrantPoint]) -> None:
        ...

    def delete_points(self, collection_name: str, point_ids: list[str]) -> None:
        ...

    def search(
        self,
        collection_name: str,
        vector: tuple[float, ...],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> tuple[QdrantSearchHit, ...]:
        ...


class InMemoryQdrantClient:
    """Deterministic in-memory Qdrant stand-in for local development and tests."""

    def __init__(self) -> None:
        self._collections: dict[str, dict[str, QdrantPoint]] = {}
        self._vector_sizes: dict[str, int] = {}

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        self._collections.setdefault(collection_name, {})
        self._vector_sizes[collection_name] = vector_size

    def upsert_points(self, collection_name: str, points: list[QdrantPoint]) -> None:
        collection = self._collections.setdefault(collection_name, {})
        for point in points:
            collection[point.id] = point

    def delete_points(self, collection_name: str, point_ids: list[str]) -> None:
        collection = self._collections.get(collection_name, {})
        for point_id in point_ids:
            collection.pop(point_id, None)

    def search(
        self,
        collection_name: str,
        vector: tuple[float, ...],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> tuple[QdrantSearchHit, ...]:
        collection = self._collections.get(collection_name, {})
        hits: list[QdrantSearchHit] = []
        for point in collection.values():
            if filters and not self._payload_matches(point.payload, filters):
                continue
            score = self._cosine_similarity(vector, point.vector)
            hits.append(QdrantSearchHit(id=point.id, score=score, payload=point.payload, vector=point.vector))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return tuple(hits[:limit])

    def _payload_matches(self, payload: QdrantPayload, filters: dict[str, Any]) -> bool:
        for key, expected in filters.items():
            actual = getattr(payload, key, payload.metadata.get(key))
            if actual != expected:
                return False
        return True

    def _cosine_similarity(self, left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sum(a * a for a in left) ** 0.5
        right_norm = sum(b * b for b in right) ** 0.5
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)


class QdrantServiceClient:
    """Persistent Qdrant adapter used by the running application."""

    def __init__(self, host: str, port: int) -> None:
        self._client = QdrantClient(url=f"http://{host}:{port}", timeout=10)

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        if not self._client.collection_exists(collection_name):
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

    def upsert_points(self, collection_name: str, points: list[QdrantPoint]) -> None:
        self._client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=point.id,
                    vector=list(point.vector),
                    payload={
                        "chunk_id": point.payload.chunk_id,
                        "document_id": point.payload.document_id,
                        "source_path": point.payload.source_path,
                        "source_name": point.payload.source_name,
                        "source_type": point.payload.source_type,
                        "title": point.payload.title,
                        "checksum": point.payload.checksum,
                        "metadata": point.payload.metadata,
                    },
                )
                for point in points
            ],
            wait=True,
        )

    def delete_points(self, collection_name: str, point_ids: list[str]) -> None:
        if not point_ids or not self._client.collection_exists(collection_name):
            return
        self._client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=point_ids),
            wait=True,
        )

    def search(
        self,
        collection_name: str,
        vector: tuple[float, ...],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> tuple[QdrantSearchHit, ...]:
        query_filter = None
        if filters:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                    for key, value in filters.items()
                ]
            )
        response = self._client.query_points(
            collection_name=collection_name,
            query=list(vector),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        hits: list[QdrantSearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            metadata = payload.get("metadata", {})
            hits.append(
                QdrantSearchHit(
                    id=str(point.id),
                    score=float(point.score),
                    payload=QdrantPayload(
                        chunk_id=str(payload.get("chunk_id", point.id)),
                        document_id=str(payload.get("document_id", "")),
                        source_path=str(payload.get("source_path", "")),
                        source_name=str(payload.get("source_name", "")),
                        source_type=str(payload.get("source_type", "")),
                        title=str(payload.get("title", "")),
                        checksum=payload.get("checksum"),
                        metadata=metadata if isinstance(metadata, dict) else {},
                    ),
                )
            )
        return tuple(hits)


class QdrantCollectionError(RuntimeError):
    pass


class QdrantPointBuilder:
    @staticmethod
    def from_embedding_record(record: EmbeddingRecord) -> QdrantPoint:
        payload = QdrantPayload(
            chunk_id=record.chunk_id,
            document_id=str(record.metadata.get("document_id", record.source_path or record.chunk_id)),
            source_path=record.source_path or record.chunk_id,
            source_name=record.document_title or "",
            source_type=str(record.metadata.get("source_type", "")),
            title=record.document_title or "",
            checksum=record.checksum,
            metadata=dict(record.metadata),
        )
        return QdrantPoint(id=record.chunk_id, vector=record.vector, payload=payload)
