from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

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


class QdrantCollectionError(RuntimeError):
    pass


class QdrantPointBuilder:
    @staticmethod
    def from_embedding_record(record: EmbeddingRecord) -> QdrantPoint:
        metadata = record.chunk.metadata
        payload = QdrantPayload(
            chunk_id=record.chunk.chunk_id,
            document_id=str(metadata.source_path),
            source_path=str(metadata.source_path),
            source_name=metadata.source_name,
            source_type=metadata.source_type,
            title=record.document_title,
            checksum=record.chunk_checksum,
            metadata={
                "chunk_index": metadata.chunk_index,
                "position": metadata.position,
                "page_number": metadata.page_number,
                "heading": metadata.heading,
                "token_count": metadata.token_count,
                **record.metadata,
            },
        )
        return QdrantPoint(id=record.chunk.chunk_id, vector=record.vector, payload=payload)
