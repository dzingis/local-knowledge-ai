from __future__ import annotations

from backend.embeddings.embedding_service import EmbeddingRecord, OllamaEmbeddingProvider
from backend.repositories.knowledge_repository import SearchableChunk
from backend.search.service import KnowledgeSearchService, SearchScope, extract_search_scope
from backend.vectorstore.qdrant_client import InMemoryQdrantClient
from backend.vectorstore.qdrant_repository import QdrantRepository


class FakeEmbeddingService:
    def embed_query(self, query: str) -> tuple[float, ...]:
        assert query == "koji je magični broj"
        return (1.0, 0.0)


class FakeKnowledgeRepository:
    def __init__(self, chunk: SearchableChunk) -> None:
        self.chunk = chunk
        self.terms: tuple[str, ...] = ()

    def get_chunks(self, chunk_ids: tuple[str, ...]) -> dict[str, SearchableChunk]:
        if self.chunk.chunk_id not in chunk_ids:
            return {}
        return {self.chunk.chunk_id: self.chunk}

    def search_chunks_by_terms(self, terms: tuple[str, ...], limit: int) -> tuple[SearchableChunk, ...]:
        self.terms = terms
        return (self.chunk,)

    def search_chunks_by_phrase(self, phrase: str, limit: int) -> tuple[SearchableChunk, ...]:
        if phrase.casefold() in self.chunk.text.casefold():
            return (self.chunk,)
        return ()


def test_search_returns_matching_chunk_with_exact_fact() -> None:
    chunk_id = "0f10f842-605a-4f4f-9f8c-fb8cf7b4f64f"
    chunk = SearchableChunk(
        chunk_id=chunk_id,
        document_id="a07f730a-d975-44c8-8ba4-1f91d5e25b67",
        source_path="/knowledge/documents/text/test_Magični.txt",
        title="test_Magični.txt",
        text="Magični broj je 987654321",
        page_number=None,
        heading=None,
        keyword_matches=1,
    )
    qdrant = QdrantRepository(client=InMemoryQdrantClient())
    qdrant.upsert_records(
        [
            EmbeddingRecord(
                chunk_id=chunk_id,
                model_name="test",
                dimensions=2,
                vector=(1.0, 0.0),
                source_path=chunk.source_path,
                document_title=chunk.title,
            )
        ]
    )
    knowledge_repository = FakeKnowledgeRepository(chunk)
    service = KnowledgeSearchService(
        embedding_service=FakeEmbeddingService(),  # type: ignore[arg-type]
        qdrant_repository=qdrant,
        knowledge_repository=knowledge_repository,  # type: ignore[arg-type]
    )

    results = service.search("koji je magični broj")

    assert results
    assert results[0].chunk.text == "Magični broj je 987654321"
    assert "magic number" in knowledge_repository.terms


def test_search_returns_exact_phrase_matches_before_hybrid_search() -> None:
    chunk = SearchableChunk(
        chunk_id="phrase-chunk",
        document_id="document-id",
        source_path="/knowledge/test2.pdf",
        title="test2.pdf",
        text="DocumentQld (12249): Korisnik nema prava",
        page_number=1,
        heading=None,
    )

    class ExactPhraseRepository:
        def search_chunks_by_phrase(self, phrase: str, limit: int) -> tuple[SearchableChunk, ...]:
            assert phrase == "korisnik nema prava"
            assert limit == 5
            return (chunk,)

        def search_chunks_by_terms(self, terms: tuple[str, ...], limit: int) -> tuple[SearchableChunk, ...]:
            raise AssertionError("Broad keyword search should not run when an exact phrase is found.")

    class UnusedEmbeddingService:
        def embed_query(self, query: str) -> tuple[float, ...]:
            raise AssertionError("Vector search should not run when an exact phrase is found.")

    class UnusedQdrantRepository:
        def search(self, *args, **kwargs):
            raise AssertionError("Vector search should not run when an exact phrase is found.")

    service = KnowledgeSearchService(
        embedding_service=UnusedEmbeddingService(),  # type: ignore[arg-type]
        qdrant_repository=UnusedQdrantRepository(),  # type: ignore[arg-type]
        knowledge_repository=ExactPhraseRepository(),  # type: ignore[arg-type]
    )

    results = service.search("korisnik nema prava")

    assert len(results) == 1
    assert results[0].chunk.text == "DocumentQld (12249): Korisnik nema prava"


def test_search_extracts_quoted_phrase_from_natural_language_query() -> None:
    chunk = SearchableChunk(
        chunk_id="quoted-phrase-chunk",
        document_id="document-id",
        source_path="/knowledge/test2.pdf",
        title="test2.pdf",
        text="DocumentQld (12249): Korisnik nema prava",
        page_number=1,
        heading=None,
    )

    class QuotedPhraseRepository:
        def search_chunks_by_phrase(self, phrase: str, limit: int) -> tuple[SearchableChunk, ...]:
            assert phrase == "korisnik nema prava"
            return (chunk,)

    class UnusedEmbeddingService:
        def embed_query(self, query: str) -> tuple[float, ...]:
            raise AssertionError("Quoted phrase matches should not use vector search.")

    service = KnowledgeSearchService(
        embedding_service=UnusedEmbeddingService(),  # type: ignore[arg-type]
        qdrant_repository=object(),  # type: ignore[arg-type]
        knowledge_repository=QuotedPhraseRepository(),  # type: ignore[arg-type]
    )

    results = service.search(
        "Molim te pronađi dokumente u kojima se spominje greška “korisnik nema prava”"
    )

    assert len(results) == 1
    assert results[0].chunk.title == "test2.pdf"


def test_missing_quoted_phrase_does_not_fall_back_to_unrelated_hybrid_results() -> None:
    class MissingPhraseRepository:
        def search_chunks_by_phrase(self, phrase: str, limit: int) -> tuple[SearchableChunk, ...]:
            assert phrase == "nepostojeća greška"
            return ()

    class UnusedEmbeddingService:
        def embed_query(self, query: str) -> tuple[float, ...]:
            raise AssertionError("An exact quoted search with no match should not broaden.")

    service = KnowledgeSearchService(
        embedding_service=UnusedEmbeddingService(),  # type: ignore[arg-type]
        qdrant_repository=object(),  # type: ignore[arg-type]
        knowledge_repository=MissingPhraseRepository(),  # type: ignore[arg-type]
    )

    assert service.search('pronađi “nepostojeća greška”') == ()


def test_search_scope_prefix_is_optional_and_supports_parser_types() -> None:
    assert extract_search_scope("SQL: IBAN") == ("IBAN", SearchScope("sql", (".sql",)))
    assert extract_search_scope("PDF: greška") == ("greška", SearchScope("pdf", (".pdf",)))
    assert extract_search_scope("IBAN u svim datotekama") == (
        "IBAN u svim datotekama",
        None,
    )
    assert extract_search_scope("sql procedura") == ("sql procedura", None)


def test_scoped_exact_phrase_search_only_queries_selected_file_type() -> None:
    sql_chunk = SearchableChunk(
        chunk_id="sql-chunk",
        document_id="sql-document",
        source_path="/knowledge/code/sql/test.sql",
        title="test.sql",
        text="SELECT 'IBAN'",
        page_number=None,
        heading=None,
    )
    calls: list[tuple[str, tuple[str, ...]]] = []

    class ScopedRepository:
        def search_chunks_by_phrase(
            self, phrase: str, limit: int, *, extensions: tuple[str, ...]
        ) -> tuple[SearchableChunk, ...]:
            calls.append((phrase, extensions))
            return (sql_chunk,) if phrase.casefold() in sql_chunk.text.casefold() else ()

    class UnusedEmbeddingService:
        def embed_query(self, query: str) -> tuple[float, ...]:
            raise AssertionError("Exact phrase results should not use vector search.")

    service = KnowledgeSearchService(
        embedding_service=UnusedEmbeddingService(),  # type: ignore[arg-type]
        qdrant_repository=object(),  # type: ignore[arg-type]
        knowledge_repository=ScopedRepository(),  # type: ignore[arg-type]
    )

    results = service.search("SQL: “IBAN”")

    assert calls == [("IBAN", (".sql",))]
    assert [result.chunk.title for result in results] == ["test.sql"]


def test_scoped_hybrid_search_filters_vector_and_keyword_results() -> None:
    sql_chunk = SearchableChunk(
        chunk_id="sql-chunk",
        document_id="sql-document",
        source_path="/knowledge/code/sql/test.sql",
        title="test.sql",
        text="procedure that contains IBAN",
        page_number=None,
        heading=None,
    )
    pdf_chunk = SearchableChunk(
        chunk_id="pdf-chunk",
        document_id="pdf-document",
        source_path="/knowledge/documents/pdf/example.pdf",
        title="example.pdf",
        text="procedure that contains IBAN",
        page_number=1,
        heading=None,
    )
    seen: dict[str, object] = {}

    class ScopedEmbeddingService:
        def embed_query(self, query: str) -> tuple[float, ...]:
            assert query == "procedure IBAN"
            return (1.0, 0.0)

    class ScopedQdrant:
        def search(
            self, vector: tuple[float, ...], limit: int, filters: dict[str, str]
        ):
            seen["vector_filter"] = filters

            class Hit:
                id = "sql-chunk"

            return type("Response", (), {"hits": (Hit(),)})()

    class ScopedRepository:
        def search_chunks_by_phrase(
            self, phrase: str, limit: int, *, extensions: tuple[str, ...]
        ) -> tuple[SearchableChunk, ...]:
            return ()

        def get_chunks(
            self, chunk_ids: tuple[str, ...], *, extensions: tuple[str, ...]
        ) -> dict[str, SearchableChunk]:
            seen["vector_extensions"] = extensions
            return {"sql-chunk": sql_chunk} if "sql-chunk" in chunk_ids else {}

        def search_chunks_by_terms(
            self, terms: tuple[str, ...], limit: int, *, extensions: tuple[str, ...]
        ) -> tuple[SearchableChunk, ...]:
            seen["keyword_extensions"] = extensions
            seen["terms"] = terms
            return (sql_chunk, pdf_chunk)

    service = KnowledgeSearchService(
        embedding_service=ScopedEmbeddingService(),  # type: ignore[arg-type]
        qdrant_repository=ScopedQdrant(),  # type: ignore[arg-type]
        knowledge_repository=ScopedRepository(),  # type: ignore[arg-type]
    )

    results = service.search("SQL: procedure IBAN")

    assert seen["vector_filter"] == {"source_type": "sql"}
    assert seen["vector_extensions"] == (".sql",)
    assert seen["keyword_extensions"] == (".sql",)
    assert "SQL" not in seen["terms"]
    assert {result.chunk.title for result in results} == {"test.sql"}


def test_ollama_embedding_provider_uses_real_embedding_response(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, list[list[float]]]:
            return {"embeddings": [[0.25, 0.75]]}

    requests_seen: list[tuple[str, dict[str, object]]] = []

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> FakeResponse:
        requests_seen.append((url, json))
        return FakeResponse()

    monkeypatch.setattr("backend.embeddings.embedding_service.requests.post", fake_post)
    provider = OllamaEmbeddingProvider(
        model_name="test-model",
        base_url="http://ollama-test:11434",
    )

    vectors = provider.embed_texts(("test query",))

    assert vectors == ((0.25, 0.75),)
    assert requests_seen == [
        ("http://ollama-test:11434/api/embed", {"model": "test-model", "input": ["test query"]})
    ]
