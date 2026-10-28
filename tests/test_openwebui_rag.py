from __future__ import annotations

from types import SimpleNamespace

import requests
from fastapi.testclient import TestClient

from backend.api import dependencies
from backend.chat.ollama_chat import ChatCompletion, ChatMessage, OllamaRagChatService
from backend.main import app
from backend.repositories.knowledge_repository import KnowledgeDocument, SearchableChunk
from backend.search.service import SearchResult


class FakeSearchService:
    def __init__(self, results: tuple[SearchResult, ...] | None = None) -> None:
        self.queries: list[str] = []
        self.graph_facts = ""
        self.sql_results: tuple[SearchResult, ...] | None = None
        self.results = results or (
            SearchResult(
                chunk=SearchableChunk(
                    chunk_id="chunk-id",
                    document_id="document-id",
                    source_path="/knowledge/test_Magični.txt",
                    title="test_Magični.txt",
                    text="Magični broj je 987654321",
                    page_number=None,
                    heading=None,
                ),
                score=0.1,
            ),
        )

    def search(self, query: str, limit: int = 5) -> tuple[SearchResult, ...]:
        self.queries.append(query)
        if query.startswith("SQL:") and self.sql_results is not None:
            return self.sql_results[:limit]
        return self.results

    def graph_context(self, query: str) -> str:
        return self.graph_facts


class FakeModelListResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, list[dict[str, str]]]:
        return {
            "models": [
                {"name": "qwen2.5:3b"},
                {"name": "nomic-embed-text:latest"},
            ]
        }


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, dict[str, str]]:
        return {"message": {"content": "The magic number is 987654321 (test_Magični.txt)."}}


def test_chat_service_supplies_retrieved_passage_to_ollama(monkeypatch) -> None:
    search = FakeSearchService()
    requests_seen: list[tuple[str, dict[str, object]]] = []

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> FakeResponse:
        assert timeout == 180
        requests_seen.append((url, json))
        return FakeResponse()

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fake_post)
    service = OllamaRagChatService(search, base_url="http://ollama-test:11434")

    response = service.complete(
        "lkai-llama-test",
        (ChatMessage(role="user", content="Tell me about this indexed fact."),),
    )

    assert search.queries == ["Tell me about this indexed fact."]
    assert "987654321 (test_Magični.txt)." in response.content
    assert "[test_Magični.txt](http://localhost:8000/api/documents/document-id/source)" in response.content
    assert "[download](http://localhost:8000/api/documents/document-id/source?download=true)" in response.content
    assert requests_seen[0][0] == "http://ollama-test:11434/api/chat"
    messages = requests_seen[0][1]["messages"]
    assert any("Magični broj je 987654321" in message["content"] for message in messages)
    assert requests_seen[0][1]["model"] == "llama-test"
    assert requests_seen[0][1]["stream"] is False


def test_magic_number_question_returns_direct_standard_croatian_answer(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("A clear, extractive fact should not be paraphrased by the chat model.")

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fail_if_called)
    service = OllamaRagChatService(FakeSearchService(), base_url="http://ollama-test:11434")

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="Koji je magični broj?"),),
    )

    assert response.content.startswith("Magični broj je 987654321.\n\nSources / Izvori:")
    assert "[test_Magični.txt](http://localhost:8000/api/documents/document-id/source)" in response.content


def test_plain_exact_phrase_search_returns_matching_lines_without_model_call(monkeypatch) -> None:
    chunk = SearchableChunk(
        chunk_id="error-chunk",
        document_id="pdf-document",
        source_path="/knowledge/test2.pdf",
        title="test2.pdf",
        text=(
            "DocumentQld (12249): Korisnik nema prava\n"
            "DocumentQld (12250): Korisnik nema prava\n"
            "An unrelated error appears here."
        ),
        page_number=1,
        heading=None,
    )
    service = OllamaRagChatService(
        FakeSearchService((SearchResult(chunk=chunk, score=1.0),)),
        base_url="http://ollama-test:11434",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Plain exact-phrase searches should not invoke the slow chat model.")

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fail_if_called)

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="korisnik nema prava"),),
    )

    assert response.content.count("Korisnik nema prava") == 2
    assert "An unrelated error" not in response.content
    assert "[test2.pdf](http://localhost:8000/api/documents/pdf-document/source)" in response.content


def test_find_documents_for_quoted_phrase_uses_only_exact_phrase_sources(monkeypatch) -> None:
    chunk = SearchableChunk(
        chunk_id="error-chunk",
        document_id="pdf-document",
        source_path="/knowledge/test2.pdf",
        title="test2.pdf",
        text=(
            "DocumentQld (12249): Korisnik nema prava\n"
            "DocumentQld (12250): Korisnik nema prava"
        ),
        page_number=1,
        heading=None,
    )
    search = FakeSearchService((SearchResult(chunk=chunk, score=1.0),))
    service = OllamaRagChatService(search, base_url="http://ollama-test:11434")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Quoted document searches should not invoke the chat model.")

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fail_if_called)

    response = service.complete(
        "lkai-qwen-test",
        (
            ChatMessage(
                role="user",
                content="Molim te pronađi dokumente u kojima se spominje greška “korisnik nema prava”",
            ),
        ),
    )

    assert search.queries == [
        "Molim te pronađi dokumente u kojima se spominje greška “korisnik nema prava”"
    ]
    assert "Dokumenti u kojima se spominje „korisnik nema prava”:" in response.content
    assert response.content.count("Korisnik nema prava") == 2
    assert "[test2.pdf](http://localhost:8000/api/documents/pdf-document/source)" in response.content


def test_scoped_search_returns_matching_sql_text_without_model_call(monkeypatch) -> None:
    chunk = SearchableChunk(
        chunk_id="sql-chunk",
        document_id="sql-document",
        source_path="/knowledge/code/sql/test.sql",
        title="test.sql",
        text="CREATE PROCEDURE pTest\nAS\nBEGIN\n    SELECT 'IBAN'\nEND",
        page_number=None,
        heading=None,
    )
    service = OllamaRagChatService(
        FakeSearchService((SearchResult(chunk=chunk, score=1.0),)),
        base_url="http://ollama-test:11434",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Scoped text searches should return matching text directly.")

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fail_if_called)

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="SQL: IBAN"),),
    )

    assert "Izraz „IBAN” pronađen je u SQL datoteci." in response.content
    assert "Podudarajući tekst:\n```sql\nSELECT 'IBAN'\n```" in response.content
    assert "nije pronađen" not in response.content
    assert "[test.sql](http://localhost:8000/api/documents/sql-document/source)" in response.content


def test_natural_language_question_still_uses_chat_model(monkeypatch) -> None:
    requests_seen = []

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> FakeResponse:
        requests_seen.append(url)
        return FakeResponse()

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fake_post)
    service = OllamaRagChatService(FakeSearchService(), base_url="http://ollama-test:11434")

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="What does the indexed document say?"),),
    )

    assert requests_seen == ["http://ollama-test:11434/api/chat"]
    assert response.content.startswith("The magic number is 987654321")


def test_chat_prompt_merges_graph_facts_with_retrieved_passages(monkeypatch) -> None:
    search = FakeSearchService()
    search.graph_facts = "pImport -[WRITES_TO]-> tHE_Move"
    requests_seen: list[dict[str, object]] = []

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> FakeResponse:
        requests_seen.append(json)
        return FakeResponse()

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fake_post)
    service = OllamaRagChatService(search, base_url="http://ollama-test:11434")

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="Which procedure writes to tHE_Move?"),),
    )

    assert response.content
    messages = requests_seen[0]["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "Magični broj je 987654321" in prompt
    assert "pImport -[WRITES_TO]-> tHE_Move" in prompt
    assert "Treat knowledge-graph facts the same way" in prompt


def test_sql_existence_question_uses_only_relevant_sql_source(monkeypatch) -> None:
    search = FakeSearchService()
    sql_result = SearchResult(
        chunk=SearchableChunk(
            chunk_id="subject-sql",
            document_id="subject-document",
            source_path="/knowledge/code/sql/IzveziSubjektsIBAN.sql",
            title="IzveziSubjektsIBAN.sql",
            text="SELECT S.acSubject FROM vHE_SetSubj S",
            page_number=None,
            heading=None,
        ),
        score=0.01,
    )
    unrelated_sql_result = SearchResult(
        chunk=SearchableChunk(
            chunk_id="test-sql",
            document_id="test-document",
            source_path="/knowledge/code/sql/test.sql",
            title="test.sql",
            text="CREATE PROCEDURE pTest AS SELECT 'IBAN'",
            page_number=None,
            heading=None,
        ),
        score=0.02,
    )
    search.sql_results = (unrelated_sql_result, sql_result)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("A database-existence question should use indexed evidence directly.")

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fail_if_called)
    service = OllamaRagChatService(search, base_url="http://ollama-test:11434")

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="imam li SQL za izvoz subjekata?"),),
    )

    assert search.queries == ["SQL: imam li SQL za izvoz subjekata?"]
    assert "IzveziSubjektsIBAN.sql" in response.content
    assert "test.sql" not in response.content
    assert "FINA" not in response.content
    assert "subject-document/source" in response.content


def test_sql_existence_question_reports_no_match_without_generating_sql(monkeypatch) -> None:
    search = FakeSearchService()
    search.sql_results = ()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("A missing database source must not trigger generated SQL.")

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fail_if_called)
    service = OllamaRagChatService(search, base_url="http://ollama-test:11434")

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="imam li SQL za izvoz subjekata?"),),
    )

    assert response.content == "U bazi znanja nisam pronašao odgovarajuću SQL datoteku."


def test_magic_number_answer_cites_all_matching_documents(monkeypatch) -> None:
    first = FakeSearchService().results[0]
    second_chunk = SearchableChunk(
        chunk_id="chunk-two",
        document_id="document-two",
        source_path="/knowledge/second.txt",
        title="second.txt",
        text="Magic number is 987654321",
        page_number=None,
        heading=None,
    )
    monkeypatch.setattr(
        "backend.chat.ollama_chat.get_settings",
        lambda: SimpleNamespace(
            ollama_host="ollama",
            ollama_port=11434,
            ollama_timeout_seconds=60,
            ollama_chat_timeout_seconds=180,
            ollama_embedding_model="nomic-embed-text",
            source_public_base_url="http://localhost:8000",
            watch_host_path=r"D:\Knowledge",
        ),
    )
    service = OllamaRagChatService(
        FakeSearchService((first, SearchResult(chunk=second_chunk, score=0.09))),
        base_url="http://ollama-test:11434",
    )

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="Koji je magični broj?"),),
    )

    assert "Magični broj je 987654321." in response.content
    assert "[test_Magični.txt](http://localhost:8000/api/documents/document-id/source)" in response.content
    assert "[second.txt](http://localhost:8000/api/documents/document-two/source)" in response.content
    assert "[original file](file:///D:/Knowledge/test_Magi%C4%8Dni.txt)" in response.content


def test_magic_number_answer_reports_conflicting_documents(monkeypatch) -> None:
    first = FakeSearchService().results[0]
    conflicting = SearchableChunk(
        chunk_id="chunk-two",
        document_id="document-two",
        source_path="/knowledge/second.txt",
        title="second.txt",
        text="Magični broj je 123456789",
        page_number=None,
        heading=None,
    )
    service = OllamaRagChatService(
        FakeSearchService((first, SearchResult(chunk=conflicting, score=0.09))),
        base_url="http://ollama-test:11434",
    )

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="Koji je magični broj?"),),
    )

    assert "različite magične brojeve: 987654321 (test_Magični.txt); 123456789 (second.txt)" in response.content
    assert "[test_Magični.txt]" in response.content
    assert "[second.txt]" in response.content


def test_native_unc_source_link_is_formatted_for_windows(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.chat.ollama_chat.get_settings",
        lambda: SimpleNamespace(
            ollama_host="ollama",
            ollama_port=11434,
            ollama_timeout_seconds=60,
            ollama_chat_timeout_seconds=180,
            ollama_embedding_model="nomic-embed-text",
            source_public_base_url="http://localhost:8000",
            watch_host_path=None,
        ),
    )
    service = OllamaRagChatService(FakeSearchService(), base_url="http://ollama-test:11434")

    assert service._native_file_uri(r"\\server\share\folder\file name.txt") == (
        "file://server/share/folder/file%20name.txt"
    )


def test_magic_number_question_returns_direct_english_answer(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("A clear, extractive fact should not be paraphrased by the chat model.")

    monkeypatch.setattr("backend.chat.ollama_chat.requests.post", fail_if_called)
    service = OllamaRagChatService(FakeSearchService(), base_url="http://ollama-test:11434")

    response = service.complete(
        "lkai-qwen-test",
        (ChatMessage(role="user", content="What is the magic number?"),),
    )

    assert response.content.startswith("The magic number is 987654321.")
    assert "[test_Magični.txt]" in response.content


def test_model_list_marks_models_as_rag_backed(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.chat.ollama_chat.requests.get",
        lambda url, timeout: FakeModelListResponse(),
    )
    service = OllamaRagChatService(FakeSearchService(), base_url="http://ollama-test:11434")

    assert service.list_models() == ("lkai-qwen2.5:3b",)


def test_openai_compatible_chat_route_returns_rag_answer() -> None:
    class FakeChatService:
        def list_models(self) -> tuple[str, ...]:
            return ("llama-test",)

        def complete(self, model: str, messages: tuple[ChatMessage, ...], temperature: float | None = None) -> ChatCompletion:
            return ChatCompletion(model=model, content="The magic number is 987654321.")

    app.dependency_overrides[dependencies.get_chat_service] = FakeChatService
    try:
        response = TestClient(app).post(
            "/v1/chat/completions",
            json={"model": "llama-test", "messages": [{"role": "user", "content": "What is the number?"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "The magic number is 987654321."


def test_openai_compatible_chat_route_returns_gateway_timeout_for_slow_model() -> None:
    class SlowChatService:
        def complete(self, model: str, messages: tuple[ChatMessage, ...], temperature: float | None = None):
            raise requests.Timeout("model timed out")

    app.dependency_overrides[dependencies.get_chat_service] = SlowChatService
    try:
        response = TestClient(app).post(
            "/v1/chat/completions",
            json={"model": "qwen-test", "messages": [{"role": "user", "content": "Explain this error"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 504
    assert "took too long" in response.json()["detail"]


def test_document_source_route_serves_indexed_file(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.txt"
    source.write_text("indexed source", encoding="utf-8")

    class FakeDocumentRepository:
        def get_document(self, document_id: str) -> KnowledgeDocument:
            return KnowledgeDocument(
                document_id=document_id,
                source_path=str(source),
                title=source.name,
                parser_kind="text",
                object_type="FILE",
                checksum="checksum",
                line_count=1,
                character_count=14,
            )

    app.dependency_overrides[dependencies.get_document_repository] = FakeDocumentRepository
    monkeypatch.setattr(
        "backend.api.routes.get_settings",
        lambda: SimpleNamespace(watch_folders=[str(tmp_path)]),
    )
    try:
        client = TestClient(app)
        response = client.get("/api/documents/document-id/source")
        download_response = client.get("/api/documents/document-id/source?download=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.text == "indexed source"
    assert response.headers["content-disposition"].startswith("inline;")
    assert download_response.status_code == 200
    assert download_response.headers["content-disposition"].startswith("attachment;")


def test_document_source_route_declares_windows_1250_for_browser_preview(tmp_path, monkeypatch) -> None:
    source = tmp_path / "croatian.txt"
    expected_text = "Magi\u010dni broj je 987654321"
    source.write_bytes(expected_text.encode("cp1250"))

    class FakeDocumentRepository:
        def get_document(self, document_id: str) -> KnowledgeDocument:
            return KnowledgeDocument(
                document_id=document_id,
                source_path=str(source),
                title=source.name,
                parser_kind="text",
                object_type="FILE",
                checksum="checksum",
                line_count=1,
                character_count=len(expected_text),
            )

    app.dependency_overrides[dependencies.get_document_repository] = FakeDocumentRepository
    monkeypatch.setattr(
        "backend.api.routes.get_settings",
        lambda: SimpleNamespace(watch_folders=[str(tmp_path)]),
    )
    try:
        response = TestClient(app).get("/api/documents/document-id/source")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=windows-1250"
    assert response.content.decode("cp1250") == expected_text
