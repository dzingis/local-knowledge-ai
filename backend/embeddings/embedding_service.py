from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol, Sequence

from backend.chunking.chunk_engine import Chunk, ChunkingResult
from backend.embeddings.embedding_cache import CachedEmbedding, EmbeddingCache, InMemoryEmbeddingCache


class EmbeddingStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    chunk_id: str
    model_name: str
    dimensions: int
    vector: tuple[float, ...]
    checksum: str | None = None
    source_path: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    source_name: str
    source_path: str
    model_name: str
    chunk_count: int
    embedded_count: int
    cache_hits: int
    cache_misses: int
    records: tuple[EmbeddingRecord, ...] = ()
    status: EmbeddingStatus = EmbeddingStatus.OK
    error_message: str | None = None

    @property
    def vector_count(self) -> int:
        return len(self.records)


class EmbeddingProvider(Protocol):
    model_name: str

    def embed_texts(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        ...


class OllamaEmbeddingProvider:
    """Minimal Ollama embedding provider abstraction.

    The implementation intentionally avoids a hard dependency on a specific HTTP
    client so it can be wired to the project’s preferred transport later.
    """

    def __init__(self, model_name: str = "nomic-embed-text") -> None:
        self.model_name = model_name

    def embed_texts(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            vectors.append(self._pseudo_embed(text))
        return tuple(vectors)

    def _pseudo_embed(self, text: str) -> tuple[float, ...]:
        # Deterministic fallback for environments where Ollama is not yet wired.
        cleaned = text.strip().lower()
        if not cleaned:
            return (0.0,)
        buckets = [0.0] * 8
        for index, char in enumerate(cleaned):
            buckets[index % len(buckets)] += (ord(char) % 97) / 97.0
        return tuple(round(value, 6) for value in buckets)


class EmbeddingService:
    """Batch chunks, consult cache, and generate embedding vectors."""

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        cache: EmbeddingCache | None = None,
        batch_size: int = 16,
    ) -> None:
        self._provider = provider or OllamaEmbeddingProvider()
        self._cache = cache or InMemoryEmbeddingCache()
        self._batch_size = batch_size

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def embed_chunking_result(self, result: ChunkingResult) -> EmbeddingBatchResult:
        return self.embed_chunks(result.chunks, source_name=result.source_name, source_path=result.source_path)

    def embed_chunks(
        self,
        chunks: Iterable[Chunk],
        *,
        source_name: str,
        source_path: str,
    ) -> EmbeddingBatchResult:
        chunk_list = tuple(chunks)
        if not chunk_list:
            return EmbeddingBatchResult(
                source_name=source_name,
                source_path=source_path,
                model_name=self.model_name,
                chunk_count=0,
                embedded_count=0,
                cache_hits=0,
                cache_misses=0,
                records=(),
            )

        records: list[EmbeddingRecord] = []
        cache_hits = 0
        cache_misses = 0

        for batch in self._batched(chunk_list, self._batch_size):
            batch_vectors: list[tuple[float, ...]] = []
            uncached_chunks: list[Chunk] = []

            for chunk in batch:
                cached = self._cache.get(chunk.chunk_id, self.model_name, checksum=self._chunk_checksum(chunk))
                if cached is not None:
                    cache_hits += 1
                    records.append(
                        EmbeddingRecord(
                            chunk_id=chunk.chunk_id,
                            model_name=self.model_name,
                            dimensions=len(cached.vector),
                            vector=cached.vector,
                            checksum=cached.checksum,
                            source_path=str(chunk.metadata.source_path),
                        )
                    )
                    continue

                cache_misses += 1
                uncached_chunks.append(chunk)

            if uncached_chunks:
                vectors = self._provider.embed_texts([chunk.text for chunk in uncached_chunks])
                for chunk, vector in zip(uncached_chunks, vectors, strict=False):
                    checksum = self._chunk_checksum(chunk)
                    record = EmbeddingRecord(
                        chunk_id=chunk.chunk_id,
                        model_name=self.model_name,
                        dimensions=len(vector),
                        vector=vector,
                        checksum=checksum,
                        source_path=str(chunk.metadata.source_path),
                    )
                    records.append(record)
                    self._cache.set(
                        CachedEmbedding(
                            chunk_id=chunk.chunk_id,
                            model_name=self.model_name,
                            checksum=checksum,
                            vector=vector,
                        )
                    )
                    batch_vectors.append(vector)

        return EmbeddingBatchResult(
            source_name=source_name,
            source_path=source_path,
            model_name=self.model_name,
            chunk_count=len(chunk_list),
            embedded_count=len(records),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            records=tuple(records),
            status=EmbeddingStatus.OK,
        )

    def _batched(self, items: Sequence[Chunk], batch_size: int) -> Iterable[tuple[Chunk, ...]]:
        for index in range(0, len(items), batch_size):
            yield tuple(items[index : index + batch_size])

    def _chunk_checksum(self, chunk: Chunk) -> str:
        checksum = chunk.metadata.source_path
        return f"{checksum}:{chunk.metadata.chunk_index}:{len(chunk.text)}"
