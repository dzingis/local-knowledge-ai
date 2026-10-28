from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import dependencies
from backend.api.graph import router as graph_router
from backend.graph.models import (
    EntityMention,
    GraphEntity,
    GraphEntityType,
    GraphRelationship,
    GraphRelationshipType,
    normalize_entity_name,
)
from backend.parsers.parser_models import (
    ParsedDocument,
    ParsedObjectType,
    ParserKind,
    ParserReference,
)
from backend.indexer.sql_queue_repository import QueueRepositoryRecord
from backend.parsers.sql_parser import SqlParser
from backend.repositories.graph_repository_base import GraphRepositoryBase
from backend.indexer.index_manager import ChangeType, QueueStatus
from backend.embeddings.embedding_service import EmbeddingService
from backend.chunking.chunk_engine import ChunkEngine, ChunkingConfig
from backend.vectorstore.qdrant_client import InMemoryQdrantClient
from backend.vectorstore.qdrant_repository import QdrantRepository
from backend.services.entity_extraction_service import EntityExtractionService
from backend.services.graph_indexing_service import GraphIndexResult, GraphIndexingService
from backend.services.relationship_extraction_service import RelationshipExtractionService
from backend.parsers.parser_service import ParserService
from backend.workers.processing_worker import ParserQueueProcessor, WorkerOutcome


def _document(
    text: str,
    *,
    name: str = "knowledge.txt",
    parser_kind: ParserKind = ParserKind.TEXT,
    metadata: dict[str, object] | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        source_path=Path(name),
        parser_kind=parser_kind,
        object_type=ParsedObjectType.UNKNOWN,
        title=Path(name).name,
        text=text,
        metadata=metadata or {},
    )


def test_normalization_and_extraction_canonicalize_sql_server_aliases() -> None:
    document = _document(
        "We use SQLSERVER, SQL Server, and Microsoft SQL Server in production."
    )

    mentions = EntityExtractionService().extract(document)

    sql_server_mentions = [
        mention
        for mention in mentions
        if mention.entity_type is GraphEntityType.TECHNOLOGY
        and normalize_entity_name(mention.name) == "sql server"
    ]
    assert len(sql_server_mentions) == 1
    assert sql_server_mentions[0].name == "SQL Server"
    assert normalize_entity_name("SQLSERVER") == normalize_entity_name(
        "Microsoft SQL Server"
    )
    assert {"SQLSERVER", "Microsoft SQL Server"} <= set(sql_server_mentions[0].aliases)


def test_prose_extraction_recognizes_labeled_people_projects_products_and_locations() -> None:
    document = _document(
        "Author: Ana Horvat\n"
        "Project: Pantheon Upgrade\n"
        "Product: Pantheon ERP\n"
        "The customer office is in Zagreb."
    )

    mentions = EntityExtractionService().extract(document)

    assert any(
        mention.name == "Ana Horvat"
        and mention.entity_type is GraphEntityType.PERSON
        for mention in mentions
    )
    assert any(
        mention.name == "Pantheon Upgrade"
        and mention.entity_type is GraphEntityType.PROJECT
        for mention in mentions
    )
    assert any(
        mention.name == "Pantheon ERP"
        and mention.entity_type is GraphEntityType.PRODUCT
        for mention in mentions
    )
    assert any(
        mention.name == "Zagreb" and mention.entity_type is GraphEntityType.LOCATION
        for mention in mentions
    )


def test_graph_repository_maps_persisted_entity_and_relationship_rows() -> None:
    repository = GraphRepositoryBase(connection_string="unused")
    entity_id = "a07f730a-d975-44c8-8ba4-1f91d5e25b67"
    document_id = "b07f730a-d975-44c8-8ba4-1f91d5e25b67"
    entity = repository._entity_from_row(
        SimpleNamespace(
            EntityId=entity_id,
            CanonicalName="SQL Server",
            NormalizedName="sql server",
            EntityType="technology",
            Description=None,
            MetadataJson='{"confidence": 0.94}',
            Aliases="SQLSERVER\x1fMicrosoft SQL Server",
            PropertiesJson="source\x1eimport.sql",
            SourceDocumentIds=document_id,
            CreatedAt=None,
            UpdatedAt=None,
        )
    )
    relationship = repository._relationship_from_row(
        SimpleNamespace(
            RelationshipId="c07f730a-d975-44c8-8ba4-1f91d5e25b67",
            SourceEntityId=entity_id,
            TargetEntityId=document_id,
            RelationshipType="MENTIONS",
            Confidence=0.9,
            SourceDocumentId=None,
            Evidence="SQL script",
            MetadataJson="{}",
            CreatedAt=None,
        )
    )

    assert entity.entity_type is GraphEntityType.TECHNOLOGY
    assert entity.aliases == ("SQLSERVER", "Microsoft SQL Server")
    assert entity.properties == {"source": "import.sql"}
    assert entity.source_document_ids == (document_id,)
    assert relationship.relationship_type is GraphRelationshipType.MENTIONS
    assert relationship.confidence == 0.9


def test_graph_migration_upgrades_legacy_relationship_columns_without_dropping_data() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "database"
        / "migrations"
        / "002-create-knowledge-graph.sql"
    )
    migration = migration_path.read_text(encoding="utf-8")

    assert "SourceEntityId = COALESCE(SourceEntityId, SourceEntity)" in migration
    assert "TargetEntityId = COALESCE(TargetEntityId, TargetEntity)" in migration
    assert "Confidence = COALESCE(Confidence, Weight, 0.8)" in migration
    assert "ALTER COLUMN SourceEntity UNIQUEIDENTIFIER NULL" in migration
    assert "DROP TABLE" not in migration.upper()


def test_sql_extraction_preserves_three_part_names_and_relationship_access() -> None:
    document = _document(
        "",
        name="import.sql",
        parser_kind=ParserKind.SQL,
        metadata={
            "definitions": [
                {
                    "name": "pImport",
                    "schema_name": "dbo",
                    "database_name": "ERP",
                    "object_type": "procedure",
                    "parameters": [{"name": "@DocumentId", "data_type": "int"}],
                    "dependencies": [
                        {
                            "name": "tHE_Move",
                            "schema": "dbo",
                            "database": "ERP",
                            "object_type": "table_or_view",
                            "access": "write",
                        },
                        {
                            "name": "pValidate",
                            "schema": "dbo",
                            "database": "ERP",
                            "object_type": "procedure",
                            "access": "execute",
                        },
                    ],
                }
            ]
        },
    )
    document = replace(
        document,
        references=(
            ParserReference("tHE_Move", "read_table_or_view", schema="dbo"),
        ),
    )

    entities = EntityExtractionService().extract(document)
    relationships = RelationshipExtractionService().extract(document, entities)

    assert any(
        entity.name == "ERP.dbo.pImport"
        and entity.entity_type is GraphEntityType.PROCEDURE
        for entity in entities
    )
    assert not any(entity.name == "dbo.tHE_Move" for entity in entities)
    assert any(
        edge.source_name == "ERP.dbo.pImport"
        and edge.target_name == "ERP.dbo.tHE_Move"
        and edge.relationship_type is GraphRelationshipType.WRITES_TO
        for edge in relationships
    )
    assert any(
        edge.source_name == "ERP.dbo.pImport"
        and edge.target_name == "ERP.dbo.pValidate"
        and edge.relationship_type is GraphRelationshipType.CALLS
        for edge in relationships
    )
    assert all(0 <= edge.confidence <= 1 for edge in relationships)


def test_python_relationships_capture_structure_and_calls() -> None:
    document = _document(
        "import pathlib\n"
        "class Importer(BaseImporter):\n"
        "    def run(self, value: str) -> Result:\n"
        "        return validate(value)\n"
        "def validate(value):\n"
        "    return value\n",
        name="importer.py",
    )
    extractor = EntityExtractionService()
    entities = extractor.extract(document)
    relationships = RelationshipExtractionService().extract(document, entities)

    assert any(
        edge.source_name == "Importer"
        and edge.target_name == "BaseImporter"
        and edge.relationship_type is GraphRelationshipType.EXTENDS
        for edge in relationships
    )
    assert any(
        edge.source_name == "run"
        and edge.target_name == "validate"
        and edge.relationship_type is GraphRelationshipType.CALLS
        for edge in relationships
    )
    assert any(
        edge.source_name == "run"
        and edge.target_name == "Result"
        and edge.relationship_type is GraphRelationshipType.RETURNS
        for edge in relationships
    )


def test_swagger_yaml_extracts_endpoint_schema_and_reference_edges() -> None:
    document = _document(
        "openapi: 3.0.0\n"
        "info:\n"
        "  title: Orders API\n"
        "  version: 1.2.0\n"
        "paths:\n"
        "  /orders:\n"
        "    get:\n"
        "      operationId: listOrders\n"
        "      responses:\n"
        "        '200':\n"
        "          content:\n"
        "            application/json:\n"
        "              schema:\n"
        "                $ref: '#/components/schemas/Order'\n"
        "components:\n"
        "  schemas:\n"
        "    Order:\n"
        "      type: object\n",
        name="orders.yaml",
    )
    extractor = EntityExtractionService()
    entities = extractor.extract(document)
    relationships = RelationshipExtractionService().extract(document, entities)

    assert any(
        entity.name == "GET /orders" and entity.entity_type is GraphEntityType.ENDPOINT
        for entity in entities
    )
    assert any(
        edge.source_name == "GET /orders"
        and edge.target_name == "Order"
        and edge.relationship_type is GraphRelationshipType.REFERENCES
        for edge in relationships
    )


class _MemoryEntityRepository:
    def __init__(self) -> None:
        self.entities: dict[tuple[str, GraphEntityType], GraphEntity] = {}
        self.embeddings: list[tuple[str, str, str]] = []

    def upsert(
        self,
        mention: EntityMention,
        source_document_id: str | None = None,
        source_path: str | None = None,
    ) -> GraphEntity:
        key = (normalize_entity_name(mention.name), mention.entity_type)
        entity = self.entities.get(key)
        if entity is None:
            entity = GraphEntity.from_mention(mention)
        properties = dict(entity.properties)
        if source_path:
            properties["source_path"] = source_path
        document_ids = set(entity.source_document_ids)
        if source_document_id:
            document_ids.add(source_document_id)
        entity = replace(
            entity,
            properties=properties,
            source_document_ids=tuple(sorted(document_ids)),
        )
        self.entities[key] = entity
        return entity

    def detach_document(self, document_id: str) -> tuple[str, ...]:
        self.last_detached_document = document_id
        return ()

    def add_embedding(self, entity_id: str, point_id: str, model_name: str) -> None:
        self.embeddings.append((entity_id, point_id, model_name))

    def search(
        self,
        query: str,
        entity_type: GraphEntityType | None = None,
        limit: int = 20,
    ) -> tuple[GraphEntity, ...]:
        normalized = normalize_entity_name(query)
        return tuple(
            entity
            for (name, _), entity in self.entities.items()
            if normalized in name
            and (entity_type is None or entity.entity_type is entity_type)
        )[:limit]

    def get(self, entity_id: str) -> GraphEntity | None:
        return next(
            (entity for entity in self.entities.values() if entity.entity_id == entity_id),
            None,
        )


class _MemoryRelationshipRepository:
    def __init__(self) -> None:
        self.relationships: list[GraphRelationship] = []

    def delete_for_document(self, document_id: str) -> int:
        self.relationships = [
            item
            for item in self.relationships
            if item.source_document_id != document_id
        ]
        return 0

    def upsert(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: GraphRelationshipType,
        confidence: float,
        source_document_id: str | None = None,
        evidence: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> GraphRelationship:
        relationship = GraphRelationship(
            relationship_id=str(uuid4()),
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relationship_type=relationship_type,
            confidence=confidence,
            source_document_id=source_document_id,
            evidence=evidence,
            metadata=metadata or {},
        )
        self.relationships.append(relationship)
        return relationship

    def find_related(
        self, entity_id: str, limit: int = 100
    ) -> tuple[GraphRelationship, ...]:
        return tuple(
            item
            for item in self.relationships
            if item.source_entity_id == entity_id or item.target_entity_id == entity_id
        )[:limit]


def test_graph_indexing_resolves_and_embeds_relationship_endpoints() -> None:
    class _EmbeddingService:
        model_name = "test-model"

        def embed_texts(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            return tuple((1.0, 0.0) for _ in texts)

    entities = _MemoryEntityRepository()
    relationships = _MemoryRelationshipRepository()
    service = GraphIndexingService(
        EntityExtractionService(),
        RelationshipExtractionService(),
        entities,  # type: ignore[arg-type]
        relationships,  # type: ignore[arg-type]
        embedding_service=EmbeddingService(provider=_EmbeddingService()),  # type: ignore[arg-type]
        entity_vector_repository=QdrantRepository(client=InMemoryQdrantClient()),
    )
    document = _document(
        "def run(value: Input) -> Output:\n"
        "    return validate(value)\n"
        "def validate(value):\n"
        "    return value\n",
        name="module.py",
    )

    result = service.index_document(
        document, "a07f730a-d975-44c8-8ba4-1f91d5e25b67"
    )

    assert result.relationship_count > 0
    assert result.embedded_entity_count == result.entity_count
    assert result.embedded_entity_count > 0
    assert entities.embeddings


def test_processing_worker_calls_graph_between_document_setup_and_chunk_embedding(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    path = tmp_path / "process.txt"
    path.write_text("A document that is long enough to make one chunk.", encoding="utf-8")
    record = QueueRepositoryRecord(
        file_name=path.name,
        full_path=str(path),
        extension="txt",
        folder_path=str(path.parent),
        file_size_bytes=path.stat().st_size,
        modified_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
        sha256="test-hash",
        status=QueueStatus.PENDING,
        change_type=ChangeType.NEW,
        enqueued_at=datetime.now(timezone.utc),
    )

    class _KnowledgeRepository:
        def ensure_document_record(self, **_kwargs: object) -> str:
            assert isinstance(_kwargs.get("parsed"), ParsedDocument)
            events.append("document")
            return "a07f730a-d975-44c8-8ba4-1f91d5e25b67"

        def store_indexed_document(
            self, **_kwargs: object
        ) -> tuple[str, tuple[str, ...]]:
            assert isinstance(_kwargs.get("parsed"), ParsedDocument)
            events.append("store")
            return "a07f730a-d975-44c8-8ba4-1f91d5e25b67", ()

    class _GraphService:
        def index_document(self, document: ParsedDocument, document_id: str) -> GraphIndexResult:
            assert document.source_path.suffix == ".txt"
            assert document_id == "a07f730a-d975-44c8-8ba4-1f91d5e25b67"
            events.append("graph")
            return GraphIndexResult(document_id, 1, 0, 0)

    class _EmbeddingProvider:
        model_name = "worker-test-model"

        def embed_texts(self, texts: list[str]) -> tuple[tuple[float, ...], ...]:
            events.append("embed")
            return tuple((1.0, 0.0) for _ in texts)

    processor = ParserQueueProcessor(
        parser_service=ParserService(),
        chunk_engine=ChunkEngine(ChunkingConfig(min_chunk_chars=1)),
        embedding_service=EmbeddingService(provider=_EmbeddingProvider()),  # type: ignore[arg-type]
        knowledge_repository=_KnowledgeRepository(),  # type: ignore[arg-type]
        graph_indexing_service=_GraphService(),  # type: ignore[arg-type]
    )

    result = processor(record)

    assert result.outcome is WorkerOutcome.COMPLETED
    assert events == ["document", "graph", "embed", "store"]
    assert result.graph_index_result is not None


def test_graph_entity_search_api_uses_dependency_injected_repository() -> None:
    class _Repository:
        def search(
            self, _query: str, _entity_type: object, _limit: int
        ) -> tuple[GraphEntity, ...]:
            assert _query == "SQL Server"
            assert _entity_type is None
            assert _limit > 0
            return (
                GraphEntity(
                    entity_id="a07f730a-d975-44c8-8ba4-1f91d5e25b67",
                    name="SQL Server",
                    normalized_name="sql server",
                    entity_type=GraphEntityType.TECHNOLOGY,
                ),
            )

    app = FastAPI()
    app.include_router(graph_router)
    app.dependency_overrides[dependencies.get_graph_entity_repository] = _Repository

    response = TestClient(app).get("/api/graph/entity/search?q=SQL%20Server")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "SQL Server"


def test_sql_parser_provides_graph_input_for_multiple_definitions() -> None:
    parsed = SqlParser().parse_text(
        """
        CREATE VIEW dbo.vImport AS SELECT Id FROM dbo.tHE_Move
        GO
        CREATE OR ALTER PROCEDURE dbo.pImport @Id int
        AS
        BEGIN
            EXEC dbo.pValidate @Id;
            UPDATE dbo.tHE_Move SET Id = @Id;
        END
        """,
        source_path="import.sql",
    ).to_parsed_document()

    entities = EntityExtractionService().extract(parsed)
    relationships = RelationshipExtractionService().extract(parsed, entities)

    assert {entity.entity_type for entity in entities} >= {
        GraphEntityType.PROCEDURE,
        GraphEntityType.VIEW,
        GraphEntityType.TABLE,
        GraphEntityType.COLUMN,
    }
    assert any(edge.relationship_type is GraphRelationshipType.CALLS for edge in relationships)
    assert any(
        edge.relationship_type is GraphRelationshipType.WRITES_TO
        for edge in relationships
    )