from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

from backend.chunking.chunk_engine import Chunk


@dataclass(frozen=True, slots=True)
class CachedEmbedding:
    chunk_id: str
    source_path: Path
    checksum: str
    model_name: str
    vector: tuple[float, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CacheLookupResult:
    hit: bool
    embedding: CachedEmbedding | None = None


class EmbeddingCache(Protocol):
    def get(self, chunk: Chunk, model_name: str) -> CacheLookupResult:
        ...

    def set(self, chunk: Chunk, model_name: str, vector: Iterable[float]) -> CachedEmbedding:
        ...

    def bulk_get(self, chunks: Iterable[Chunk], model_name: str) -> tuple[CacheLookupResult, ...]:
        ...


class InMemoryEmbeddingCache:
    """Simple in-memory embedding cache keyed by chunk id and model name."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], CachedEmbedding] = {}

    def get(self, chunk: Chunk, model_name: str) -> CacheLookupResult:
        cached = self._cache.get((chunk.chunk_id, model_name))
        if cached is None:
            return CacheLookupResult(hit=False)
        if cached.checksum != self._checksum(chunk):
            return CacheLookupResult(hit=False)
        return CacheLookupResult(hit=True, embedding=cached)

    def set(self, chunk: Chunk, model_name: str, vector: Iterable[float]) -> CachedEmbedding:
        embedding = CachedEmbedding(
            chunk_id=chunk.chunk_id,
            source_path=Path(chunk.metadata.source_path),
            checksum=self._checksum(chunk),
            model_name=model_name,
            vector=tuple(float(value) for value in vector),
            created_at=datetime.now(timezone.utc),
        )
        self._cache[(chunk.chunk_id, model_name)] = embedding
        return embedding

    def bulk_get(self, chunks: Iterable[Chunk], model_name: str) -> tuple[CacheLookupResult, ...]:
        return tuple(self.get(chunk, model_name) for chunk in chunks)

    def _checksum(self, chunk: Chunk) -> str:
        return chunk.chunk_id + "|" + chunk.text[:128]
