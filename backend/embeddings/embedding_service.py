from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol, Sequence

import requests

from backend.chunking.chunk_engine import Chunk, ChunkingResult
from backend.embeddings.embedding_cache import EmbeddingCache, InMemoryEmbeddingCache
from backend.config.settings import get_settings


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
    document_title: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


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
    """Generate vectors using Ollama's embedding API."""

    def __init__(
        self,
        model_name: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.ollama_embedding_model
        self._base_url = base_url or f"http://{settings.ollama_host}:{settings.ollama_port}"
        self._timeout_seconds = timeout_seconds or settings.ollama_timeout_seconds

    def embed_texts(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        response = requests.post(
            f"{self._base_url.rstrip('/')}/api/embed",
            json={"model": self.model_name, "input": list(texts)},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        raw_embeddings = data.get("embeddings")
        if not isinstance(raw_embeddings, list) or len(raw_embeddings) != len(texts):
            raise RuntimeError("Ollama returned an unexpected embedding response.")
        vectors = tuple(tuple(float(value) for value in vector) for vector in raw_embeddings)
        if any(not vector for vector in vectors):
            raise RuntimeError("Ollama returned an empty embedding vector.")
        return vectors


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

    def embed_query(self, query: str) -> tuple[float, ...]:
        vectors = self.embed_texts((query,))
        if len(vectors) != 1 or not vectors[0]:
            raise RuntimeError("Embedding provider did not return a vector for the search query.")
        return vectors[0]

    def embed_texts(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        vectors = self._provider.embed_texts(texts)
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise RuntimeError("Embedding provider returned an invalid embedding batch.")
        return vectors

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
            uncached_chunks: list[Chunk] = []

            for chunk in batch:
                cache_result = self._cache.get(chunk, self.model_name)
                cached = cache_result.embedding
                if cache_result.hit and cached is not None:
                    cache_hits += 1
                    records.append(
                        EmbeddingRecord(
                            chunk_id=chunk.chunk_id,
                            model_name=self.model_name,
                            dimensions=len(cached.vector),
                            vector=cached.vector,
                            checksum=cached.checksum,
                            source_path=str(chunk.metadata.source_path),
                            document_title=chunk.metadata.source_name,
                            metadata={
                                "source_type": chunk.metadata.source_type,
                                "chunk_index": chunk.metadata.chunk_index,
                                "position": chunk.metadata.position,
                                "page_number": chunk.metadata.page_number,
                                "heading": chunk.metadata.heading,
                                "token_count": chunk.metadata.token_count,
                            },
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
                        document_title=chunk.metadata.source_name,
                        metadata={
                            "source_type": chunk.metadata.source_type,
                            "chunk_index": chunk.metadata.chunk_index,
                            "position": chunk.metadata.position,
                            "page_number": chunk.metadata.page_number,
                            "heading": chunk.metadata.heading,
                            "token_count": chunk.metadata.token_count,
                        },
                    )
                    records.append(record)
                    self._cache.set(chunk, self.model_name, vector)

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
