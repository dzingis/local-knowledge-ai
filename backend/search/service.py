from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from backend.embeddings.embedding_service import EmbeddingService
from backend.repositories.knowledge_repository import KnowledgeRepository, SearchableChunk
from backend.services.graph_indexing_service import GraphIndexingService
from backend.vectorstore.qdrant_repository import QdrantRepository

_QUOTED_PHRASE = re.compile(r"[\"“„«](.+?)[\"”»]")
_SCOPE_PREFIX = re.compile(
    r"^\s*(?P<scope>SQL|PDF|DOCX|WORD|DELPHI|PAS|DFM|MARKDOWN|MD|TEXT)\s*:\s*",
    re.IGNORECASE,
)

_SEARCH_SCOPES = {
    "SQL": ("sql", (".sql",)),
    "PDF": ("pdf", (".pdf",)),
    "DOCX": ("word", (".docx",)),
    "WORD": ("word", (".docx",)),
    "DELPHI": ("delphi", (".pas", ".dfm")),
    "PAS": ("delphi", (".pas",)),
    "DFM": ("delphi", (".dfm",)),
    "MARKDOWN": ("markdown", (".md", ".markdown")),
    "MD": ("markdown", (".md", ".markdown")),
    "TEXT": (
        "text",
        (
            ".txt",
            ".text",
            ".json",
            ".xml",
            ".yaml",
            ".yml",
            ".csv",
            ".log",
            ".ini",
            ".cfg",
            ".conf",
            ".config",
            ".html",
            ".htm",
            ".rst",
            ".toml",
            ".env",
        ),
    ),
}

_CROSS_LANGUAGE_PHRASES = {
    "koji je magični broj": ("magic number", "čarobni broj"),
    "koji je čarobni broj": ("magic number", "magični broj"),
    "magični broj": ("magic number", "čarobni broj"),
    "čarobni broj": ("magic number", "magični broj"),
    "what is the magic number": ("magični broj", "čarobni broj"),
    "what's the magic number": ("magični broj", "čarobni broj"),
    "magic number": ("magični broj", "čarobni broj"),
}


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk: SearchableChunk
    score: float


@dataclass(frozen=True, slots=True)
class SearchScope:
    parser_kind: str
    extensions: tuple[str, ...]


def extract_search_scope(query: str) -> tuple[str, SearchScope | None]:
    match = _SCOPE_PREFIX.match(query)
    if match is None:
        return query.strip(), None
    parser_kind, extensions = _SEARCH_SCOPES[match.group("scope").upper()]
    return query[match.end():].strip(), SearchScope(parser_kind, extensions)


def extract_quoted_phrase(query: str) -> str | None:
    match = _QUOTED_PHRASE.search(query)
    if match is None:
        return None
    phrase = match.group(1).strip()
    return phrase or None


class KnowledgeSearchService:
    """Retrieves relevant stored passages using vector and SQL keyword search."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        qdrant_repository: QdrantRepository,
        knowledge_repository: KnowledgeRepository,
        graph_indexing_service: GraphIndexingService | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._qdrant_repository = qdrant_repository
        self._knowledge_repository = knowledge_repository
        self._graph_indexing_service = graph_indexing_service

    def graph_context(self, query: str) -> str:
        if self._graph_indexing_service is None:
            return ""
        return self._graph_indexing_service.search_context(query)

    def search(self, query: str, limit: int = 5) -> tuple[SearchResult, ...]:
        normalized_query, scope = extract_search_scope(query)
        if not normalized_query:
            return ()

        quoted_phrase = extract_quoted_phrase(normalized_query)
        phrase = quoted_phrase or normalized_query
        if scope is None:
            phrase_chunks = self._knowledge_repository.search_chunks_by_phrase(phrase, limit)
        else:
            phrase_chunks = self._knowledge_repository.search_chunks_by_phrase(
                phrase, limit, extensions=scope.extensions
            )
        if phrase_chunks:
            return tuple(
                SearchResult(chunk=chunk, score=1.0 / rank)
                for rank, chunk in enumerate(phrase_chunks, start=1)
            )
        if quoted_phrase is not None:
            return ()

        vector = self._embedding_service.embed_query(normalized_query)
        if scope is None:
            vector_hits = self._qdrant_repository.search(
                vector, limit=max(limit * 4, limit)
            ).hits
            vector_chunks = self._knowledge_repository.get_chunks(
                tuple(hit.id for hit in vector_hits)
            )
        else:
            vector_hits = self._qdrant_repository.search(
                vector,
                limit=max(limit * 10, limit),
                filters={"source_type": scope.parser_kind},
            ).hits
            vector_chunks = self._knowledge_repository.get_chunks(
                tuple(hit.id for hit in vector_hits), extensions=scope.extensions
            )
        vector_rank = {hit.id: rank for rank, hit in enumerate(vector_hits, start=1) if hit.id in vector_chunks}

        terms = re.findall(r"[^\W_]+", normalized_query, flags=re.UNICODE)
        normalized_lower = normalized_query.casefold()
        for phrase, translations in _CROSS_LANGUAGE_PHRASES.items():
            if phrase in normalized_lower:
                terms.extend(translations)
        if scope is None:
            keyword_chunks = self._knowledge_repository.search_chunks_by_terms(
                terms, limit=max(limit * 4, limit)
            )
        else:
            keyword_chunks = self._knowledge_repository.search_chunks_by_terms(
                terms, limit=max(limit * 4, limit), extensions=scope.extensions
            )
            keyword_chunks = tuple(
                chunk for chunk in keyword_chunks if self._matches_scope(chunk, scope)
            )
        keyword_rank = {chunk.chunk_id: rank for rank, chunk in enumerate(keyword_chunks, start=1)}
        chunks = dict(vector_chunks)
        chunks.update((chunk.chunk_id, chunk) for chunk in keyword_chunks)
        if scope is not None:
            chunks = {
                chunk_id: chunk
                for chunk_id, chunk in chunks.items()
                if self._matches_scope(chunk, scope)
            }

        results = [
            SearchResult(
                chunk=chunk,
                score=(1 / (60 + vector_rank[chunk_id]) if chunk_id in vector_rank else 0)
                + (1 / (60 + keyword_rank[chunk_id]) if chunk_id in keyword_rank else 0),
            )
            for chunk_id, chunk in chunks.items()
        ]
        results.sort(key=lambda result: result.score, reverse=True)
        return tuple(results[:limit])

    def _matches_scope(self, chunk: SearchableChunk, scope: SearchScope) -> bool:
        return Path(chunk.source_path).suffix.casefold() in scope.extensions
