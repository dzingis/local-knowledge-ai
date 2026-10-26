from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence


class ChunkStrategy(str, Enum):
    """Chunking strategy used to split parsed text into embedding-ready pieces."""

    FIXED = "fixed"
    HEADING_AWARE = "heading_aware"
    PAGE_AWARE = "page_aware"


@dataclass(frozen=True, slots=True)
class ChunkMetadata:
    """Metadata attached to each generated chunk."""

    source_path: str
    source_name: str
    source_type: str
    parent_id: str | None = None
    page_number: int | None = None
    heading: str | None = None
    position: int = 0
    chunk_index: int = 0
    token_count: int = 0


@dataclass(frozen=True, slots=True)
class Chunk:
    """A single chunk ready for embedding and storage."""

    chunk_id: str
    text: str
    metadata: ChunkMetadata


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """Configuration for the chunking engine."""

    max_tokens: int = 800
    overlap_tokens: int = 120
    strategy: ChunkStrategy = ChunkStrategy.HEADING_AWARE
    min_chunk_chars: int = 50
    preserve_empty_lines: bool = False


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    """Result of a chunking operation."""

    source_name: str
    source_path: str
    chunks: tuple[Chunk, ...] = ()
    total_tokens: int = 0
    strategy: ChunkStrategy = ChunkStrategy.HEADING_AWARE

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Normalized parser output consumed by the chunking engine."""

    source_name: str
    source_path: str
    text: str
    source_type: str
    page_number: int | None = None
    heading: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class TokenEstimator:
    """Heuristic token estimator used when an exact tokenizer is unavailable."""

    def estimate(self, text: str) -> int:
        text = text.strip()
        if not text:
            return 0
        words = text.split()
        return max(1, int(len(words) * 1.25))


class ChunkEngine:
    """Split parsed documents into embedding-ready chunks.

    The implementation intentionally favors deterministic behavior so the same input
    document yields the same chunk layout across runs, which keeps embeddings,
    Qdrant payloads, and SQL references stable.
    """

    def __init__(self, config: ChunkingConfig | None = None, estimator: TokenEstimator | None = None) -> None:
        self.config = config or ChunkingConfig()
        self.estimator = estimator or TokenEstimator()

    def chunk_document(self, document: ParsedDocument) -> ChunkingResult:
        normalized_text = self._normalize_text(document.text)
        if not normalized_text:
            return ChunkingResult(
                source_name=document.source_name,
                source_path=document.source_path,
                chunks=(),
                total_tokens=0,
                strategy=self.config.strategy,
            )

        paragraphs = self._split_into_paragraphs(normalized_text)
        chunks: list[Chunk] = []
        buffer: list[str] = []
        current_tokens = 0
        chunk_index = 0
        position = 0

        for paragraph in paragraphs:
            paragraph_tokens = self.estimator.estimate(paragraph)
            if not buffer:
                buffer.append(paragraph)
                current_tokens = paragraph_tokens
                continue

            if current_tokens + paragraph_tokens <= self.config.max_tokens:
                buffer.append(paragraph)
                current_tokens += paragraph_tokens
                continue

            chunk_text = self._join_paragraphs(buffer)
            if len(chunk_text) >= self.config.min_chunk_chars:
                chunks.append(
                    self._build_chunk(
                        document=document,
                        text=chunk_text,
                        chunk_index=chunk_index,
                        position=position,
                        token_count=current_tokens,
                    )
                )
                chunk_index += 1
                position += 1

            buffer = self._apply_overlap(buffer)
            if buffer:
                current_tokens = self.estimator.estimate(self._join_paragraphs(buffer))
            else:
                current_tokens = 0

            buffer.append(paragraph)
            current_tokens += paragraph_tokens

        if buffer:
            chunk_text = self._join_paragraphs(buffer)
            if len(chunk_text) >= self.config.min_chunk_chars or not chunks:
                chunks.append(
                    self._build_chunk(
                        document=document,
                        text=chunk_text,
                        chunk_index=chunk_index,
                        position=position,
                        token_count=current_tokens,
                    )
                )

        total_tokens = sum(chunk.metadata.token_count for chunk in chunks)
        return ChunkingResult(
            source_name=document.source_name,
            source_path=document.source_path,
            chunks=tuple(chunks),
            total_tokens=total_tokens,
            strategy=self.config.strategy,
        )

    def chunk_many(self, documents: Iterable[ParsedDocument]) -> tuple[ChunkingResult, ...]:
        return tuple(self.chunk_document(document) for document in documents)

    def _build_chunk(
        self,
        document: ParsedDocument,
        text: str,
        chunk_index: int,
        position: int,
        token_count: int,
    ) -> Chunk:
        metadata = ChunkMetadata(
            source_path=document.source_path,
            source_name=document.source_name,
            source_type=document.source_type,
            page_number=document.page_number,
            heading=document.heading,
            position=position,
            chunk_index=chunk_index,
            token_count=token_count,
        )
        chunk_id = f"{document.source_path}:{chunk_index:04d}"
        return Chunk(chunk_id=chunk_id, text=text.strip(), metadata=metadata)

    def _split_into_paragraphs(self, text: str) -> list[str]:
        if self.config.strategy == ChunkStrategy.PAGE_AWARE:
            paragraphs = [part.strip() for part in text.split("\f") if part.strip()]
        else:
            paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        if self.config.preserve_empty_lines:
            return paragraphs
        return [paragraph for paragraph in paragraphs if paragraph]

    def _normalize_text(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in normalized.split("\n")]
        if self.config.preserve_empty_lines:
            return "\n".join(lines).strip()
        collapsed_lines = []
        previous_blank = False
        for line in lines:
            is_blank = not line.strip()
            if is_blank and previous_blank:
                continue
            collapsed_lines.append(line)
            previous_blank = is_blank
        return "\n".join(collapsed_lines).strip()

    def _join_paragraphs(self, paragraphs: Sequence[str]) -> str:
        return "\n\n".join(paragraphs).strip()

    def _apply_overlap(self, buffer: Sequence[str]) -> list[str]:
        if not buffer or self.config.overlap_tokens <= 0:
            return []

        overlap: list[str] = []
        running_tokens = 0
        for paragraph in reversed(buffer):
            paragraph_tokens = self.estimator.estimate(paragraph)
            if overlap and running_tokens + paragraph_tokens > self.config.overlap_tokens:
                break
            overlap.insert(0, paragraph)
            running_tokens += paragraph_tokens
            if running_tokens >= self.config.overlap_tokens:
                break
        return overlap
