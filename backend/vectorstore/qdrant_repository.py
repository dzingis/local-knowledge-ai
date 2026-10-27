from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.embeddings.embedding_service import EmbeddingBatchResult, EmbeddingRecord
from backend.vectorstore.qdrant_client import (
    InMemoryQdrantClient,
    QdrantClientProtocol,
    QdrantPoint,
    QdrantPointBuilder,
    QdrantSearchHit,
)


@dataclass(frozen=True, slots=True)
class QdrantRepositoryConfig:
    collection_name: str = "local-knowledge"
    vector_size: int = 1536
    default_limit: int = 10
    payload_index_fields: tuple[str, ...] = ("source_name", "source_type", "title")


@dataclass(frozen=True, slots=True)
class QdrantUpsertResult:
    collection_name: str
    point_count: int
    point_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QdrantDeleteResult:
    collection_name: str
    deleted_count: int
    point_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QdrantSearchResult:
    collection_name: str
    hits: tuple[QdrantSearchHit, ...] = ()
    query_metadata: dict[str, Any] = field(default_factory=dict)


class QdrantRepository:
    """Thin repository wrapper around the Qdrant client for Milestone 2E."""

    def __init__(
        self,
        client: QdrantClientProtocol | None = None,
        config: QdrantRepositoryConfig | None = None,
    ) -> None:
        self._client = client or InMemoryQdrantClient()
        self._config = config or QdrantRepositoryConfig()

    @property
    def collection_name(self) -> str:
        return self._config.collection_name

    def ensure_collection(self, vector_size: int | None = None) -> None:
        self._client.ensure_collection(self.collection_name, vector_size or self._config.vector_size)

    def upsert_embeddings(self, batch_result: EmbeddingBatchResult) -> QdrantUpsertResult:
        points = [QdrantPointBuilder.from_embedding_record(record) for record in batch_result.records]
        if not points:
            return QdrantUpsertResult(collection_name=self.collection_name, point_count=0, point_ids=())
        self.ensure_collection(vector_size=len(points[0].vector))
        self._client.upsert_points(self.collection_name, points)
        return QdrantUpsertResult(
            collection_name=self.collection_name,
            point_count=len(points),
            point_ids=tuple(point.id for point in points),
        )

    def delete_embeddings(self, point_ids: list[str]) -> QdrantDeleteResult:
        if not point_ids:
            return QdrantDeleteResult(collection_name=self.collection_name, deleted_count=0, point_ids=())
        self._client.delete_points(self.collection_name, point_ids)
        return QdrantDeleteResult(
            collection_name=self.collection_name,
            deleted_count=len(point_ids),
            point_ids=tuple(point_ids),
        )

    def search(self, vector: tuple[float, ...], limit: int | None = None, filters: dict[str, Any] | None = None) -> QdrantSearchResult:
        hits = self._client.search(self.collection_name, vector, limit=limit or self._config.default_limit, filters=filters)
        return QdrantSearchResult(collection_name=self.collection_name, hits=hits, query_metadata={"filters": filters or {}})

    def upsert_records(self, records: list[EmbeddingRecord]) -> QdrantUpsertResult:
        batch = EmbeddingBatchResult(records=tuple(records))
        return self.upsert_embeddings(batch)
