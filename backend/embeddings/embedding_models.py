from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from backend.chunking.chunk_engine import Chunk


class EmbeddingProvider(str, Enum):
    OLLAMA = "ollama"


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    chunk_id: str
    vector: tuple[float, ...]
    dimension: int
    model_name: str
    provider: EmbeddingProvider = EmbeddingProvider.OLLAMA
    checksum: str | None = None
    source_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    chunks: tuple[Chunk, ...]
    model_name: str
    provider: EmbeddingProvider = EmbeddingProvider.OLLAMA


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    chunk_id: str
    vector: EmbeddingVector
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class EmbeddingSummary:
    total_chunks: int
    embedded_chunks: int
    cache_hits: int
    cache_misses: int
    model_name: str
    provider: EmbeddingProvider
