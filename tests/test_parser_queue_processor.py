from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pymupdf

from backend.chunking.chunk_engine import Chunk, ChunkEngine, ChunkingConfig
from backend.embeddings.embedding_cache import InMemoryEmbeddingCache
from backend.embeddings.embedding_service import EmbeddingService
from backend.indexer.index_manager import ChangeType, QueueStatus
from backend.indexer.sql_queue_repository import QueueRepositoryRecord
from backend.parsers.parser_models import ParsedDocument, ParserKind
from backend.parsers.parser_service import ParserService
from backend.parsers.pdf_parser import PdfParser
from backend.vectorstore.qdrant_client import InMemoryQdrantClient
from backend.vectorstore.qdrant_repository import QdrantRepository
from backend.workers.processing_worker import ParserQueueProcessor, WorkerOutcome


class FakeEmbeddingResult:
    records: tuple[object, ...] = ()


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.source_name: str | None = None
        self.source_path: str | None = None
        self.chunk_count = 0

    def embed_chunks(
        self,
        chunks: Iterable[Chunk],
        *,
        source_name: str,
        source_path: str,
    ) -> FakeEmbeddingResult:
        self.source_name = source_name
        self.source_path = source_path
        self.chunk_count = len(tuple(chunks))
        return FakeEmbeddingResult()


class StaticEmbeddingProvider:
    model_name = "test-embedding-model"

    def embed_texts(self, texts: Iterable[str]) -> tuple[tuple[float, ...], ...]:
        return tuple((1.0, 0.0) for _ in texts)


class FakeKnowledgeRepository:
    document_id = "a07f730a-d975-44c8-8ba4-1f91d5e25b67"

    def __init__(self) -> None:
        self.saved: dict[str, object] | None = None

    def store_indexed_document(self, **kwargs: object) -> tuple[str, tuple[str, ...]]:
        self.saved = kwargs
        return self.document_id, ()


def _queue_record(path: Path) -> QueueRepositoryRecord:
    return QueueRepositoryRecord(
        file_name=path.name,
        full_path=str(path),
        extension=path.suffix.lstrip("."),
        folder_path=str(path.parent),
        file_size_bytes=path.stat().st_size,
        modified_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
        sha256="test-hash",
        status=QueueStatus.PENDING,
        change_type=ChangeType.NEW,
        enqueued_at=datetime.now(timezone.utc),
    )


def test_parser_queue_processor_adapts_shared_parsed_document(tmp_path: Path) -> None:
    path = tmp_path / "knowledge.txt"
    path.write_text(
        "This document contains enough text to verify parser-to-chunker adaptation.",
        encoding="utf-8",
    )
    processor = ParserQueueProcessor(
        parser_service=ParserService(),
        chunk_engine=ChunkEngine(ChunkingConfig(min_chunk_chars=1)),
    )

    result = processor(_queue_record(path))

    assert result.outcome == WorkerOutcome.COMPLETED
    assert result.parsed_document is not None
    assert result.parsed_document.title == "This document contains enough text to verify parser-to-chunker adaptation."
    assert result.chunking_result is not None
    assert result.chunking_result.source_name == result.parsed_document.title
    assert result.chunking_result.chunks[0].metadata.source_type == ParserKind.TEXT.value


def test_parser_queue_processor_passes_source_metadata_to_embedding(tmp_path: Path) -> None:
    path = tmp_path / "embedded.txt"
    path.write_text(
        "This document contains enough text to verify embedding source metadata.",
        encoding="utf-8",
    )
    embedding_service = FakeEmbeddingService()
    processor = ParserQueueProcessor(
        parser_service=ParserService(),
        chunk_engine=ChunkEngine(ChunkingConfig(min_chunk_chars=1)),
        embedding_service=embedding_service,  # type: ignore[arg-type]
    )

    result = processor(_queue_record(path))

    assert result.outcome == WorkerOutcome.COMPLETED
    assert embedding_service.source_name is not None
    assert embedding_service.source_path == str(path)


def test_parser_queue_processor_embeds_and_caches_chunks(tmp_path: Path) -> None:
    path = tmp_path / "embedded-real.txt"
    path.write_text(
        "This document contains enough text to test embedding and cache integration.",
        encoding="utf-8",
    )
    embedding_service = EmbeddingService(
        provider=StaticEmbeddingProvider(),
        cache=InMemoryEmbeddingCache(),
    )
    qdrant_repository = QdrantRepository(client=InMemoryQdrantClient())
    processor = ParserQueueProcessor(
        parser_service=ParserService(),
        chunk_engine=ChunkEngine(ChunkingConfig(min_chunk_chars=1)),
        embedding_service=embedding_service,
        qdrant_repository=qdrant_repository,
    )

    result = processor(_queue_record(path))

    assert result.outcome == WorkerOutcome.COMPLETED
    assert result.embedding_result is not None
    assert result.embedding_result.embedded_count > 0
    assert result.embedding_result.records[0].source_path == str(path)
    assert result.qdrant_result is not None
    assert result.qdrant_result.point_count == result.embedding_result.embedded_count


def test_parser_queue_processor_persists_sql_metadata_before_vector_upsert(tmp_path: Path) -> None:
    path = tmp_path / "persisted.txt"
    path.write_text("A stored document chunk contains an exact retrieval fact.", encoding="utf-8")
    knowledge_repository = FakeKnowledgeRepository()
    qdrant_client = InMemoryQdrantClient()
    qdrant_repository = QdrantRepository(client=qdrant_client)
    processor = ParserQueueProcessor(
        parser_service=ParserService(),
        chunk_engine=ChunkEngine(ChunkingConfig(min_chunk_chars=1)),
        embedding_service=EmbeddingService(provider=StaticEmbeddingProvider()),
        qdrant_repository=qdrant_repository,
        knowledge_repository=knowledge_repository,  # type: ignore[arg-type]
    )

    result = processor(_queue_record(path))

    assert result.outcome == WorkerOutcome.COMPLETED
    assert knowledge_repository.saved is not None
    assert knowledge_repository.saved["file_checksum"] == "test-hash"
    assert result.embedding_result is not None
    assert result.embedding_result.records[0].metadata["document_id"] == knowledge_repository.document_id
    assert result.qdrant_result is not None
    assert result.qdrant_result.point_count == 1


def test_parser_service_returns_shared_document_for_pdf(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "A PDF document converted to the shared parser model.")
        document.save(path)

    parsed = ParserService().parse_file(path)

    assert isinstance(parsed, ParsedDocument)
    assert parsed.parser_kind == ParserKind.PDF
    assert "PDF document" in parsed.text


def test_pdf_parser_ocr_extracts_text_from_image_pages(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "scanned.pdf"
    path.touch()
    ocr_page = object()
    ocr_calls: list[tuple[str, int, bool]] = []

    class FakePage:
        rect = type("Rect", (), {"width": 600, "height": 800})()

        def get_text(self, kind: str, *, textpage=None) -> str:
            if textpage is ocr_page:
                return "Existing selectable text\nError code E-1234"
            return "Existing selectable text"

        def get_image_info(self, *, xrefs: bool) -> list[dict[str, tuple[int, int, int, int]]]:
            return [{"bbox": (0, 0, 600, 800)}]

        def get_textpage_ocr(self, *, language: str, dpi: int, full: bool):
            ocr_calls.append((language, dpi, full))
            return ocr_page

    class FakeDocument:
        metadata = {"title": None}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter((FakePage(),))

    monkeypatch.setattr("backend.parsers.pdf_parser.pymupdf.open", lambda source: FakeDocument())

    parsed = PdfParser().parse_file(path)

    assert "Error code E-1234" in parsed.text
    assert parsed.metadata["ocr_pages"] == [1]
    assert parsed.pages[0].ocr_used is True
    assert ocr_calls == [("eng+hrv", 300, False)]


def test_pdf_parser_skips_ocr_for_text_only_pages(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "digital.pdf"
    path.touch()

    class FakePage:
        def get_text(self, kind: str) -> str:
            return "Selectable error E-5678"

        rect = type("Rect", (), {"width": 600, "height": 800})()

        def get_image_info(self, *, xrefs: bool) -> list[dict[str, tuple[int, int, int, int]]]:
            return []

    class FakeDocument:
        metadata = {"title": None}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter((FakePage(),))

    monkeypatch.setattr("backend.parsers.pdf_parser.pymupdf.open", lambda source: FakeDocument())

    parsed = PdfParser().parse_file(path)

    assert "Selectable error E-5678" in parsed.text
    assert parsed.metadata["ocr_pages"] == []


def test_pdf_parser_skips_ocr_for_small_images_on_text_pages(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "digital-with-logo.pdf"
    path.touch()
    ocr_calls: list[bool] = []

    class FakePage:
        rect = type("Rect", (), {"width": 600, "height": 800})()

        def get_text(self, kind: str, *, textpage=None) -> str:
            return "Selectable document text"

        def get_image_info(self, *, xrefs: bool) -> list[dict[str, tuple[int, int, int, int]]]:
            return [{"bbox": (10, 10, 100, 80)}]

        def get_textpage_ocr(self, *, language: str, dpi: int, full: bool):
            ocr_calls.append(True)

    class FakeDocument:
        metadata = {"title": None}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter((FakePage(),))

    monkeypatch.setattr("backend.parsers.pdf_parser.pymupdf.open", lambda source: FakeDocument())

    parsed = PdfParser().parse_file(path)

    assert parsed.text == "Selectable document text"
    assert parsed.metadata["ocr_pages"] == []
    assert parsed.pages[0].ocr_used is False
    assert ocr_calls == []
