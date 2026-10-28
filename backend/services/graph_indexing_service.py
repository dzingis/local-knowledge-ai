from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from backend.embeddings.embedding_service import (
    EmbeddingBatchResult,
    EmbeddingRecord,
    EmbeddingService,
)
from backend.graph.models import (
    EntityMention,
    GraphDocument,
    GraphEntity,
    GraphEntityType,
    GraphRelationship,
    GraphStatistics,
    normalize_entity_name,
)
from backend.parsers.parser_models import ParsedDocument
from backend.parsers.parser_service import ParserService
from backend.repositories.graph_entity_repository import GraphEntityRepository
from backend.repositories.graph_relationship_repository import GraphRelationshipRepository
from backend.repositories.knowledge_repository import KnowledgeDocument
from backend.services.entity_extraction_service import EntityExtractionService
from backend.services.relationship_extraction_service import RelationshipExtractionService
from backend.vectorstore.qdrant_repository import QdrantRepository


@dataclass(frozen=True, slots=True)
class GraphIndexResult:
    document_id: str
    entity_count: int
    relationship_count: int
    embedded_entity_count: int


class GraphIndexingService:
    """Coordinates graph extraction, persistence, entity vectors, and retrieval."""

    def __init__(
        self,
        entity_extraction_service: EntityExtractionService,
        relationship_extraction_service: RelationshipExtractionService,
        entity_repository: GraphEntityRepository,
        relationship_repository: GraphRelationshipRepository,
        parser_service: ParserService | None = None,
        embedding_service: EmbeddingService | None = None,
        entity_vector_repository: QdrantRepository | None = None,
    ) -> None:
        self._entity_extractor = entity_extraction_service
        self._relationship_extractor = relationship_extraction_service
        self._entities = entity_repository
        self._relationships = relationship_repository
        self._parser_service = parser_service or ParserService()
        self._embedding_service = embedding_service
        self._entity_vectors = entity_vector_repository

    def index_document(
        self, document: ParsedDocument, document_id: str
    ) -> GraphIndexResult:
        self._relationships.delete_for_document(document_id)
        stale_entity_ids = self._entities.detach_document(document_id)
        if stale_entity_ids and self._entity_vectors is not None:
            self._entity_vectors.delete_embeddings(list(stale_entity_ids))

        mentions = self._entity_extractor.extract(document)
        lookup: dict[tuple[str, GraphEntityType], GraphEntity] = {}
        for mention in mentions:
            entity = self._entities.upsert(
                mention,
                source_document_id=document_id,
                source_path=str(document.source_path),
            )
            key = (normalize_entity_name(mention.name), mention.entity_type)
            lookup.setdefault(key, entity)

        relationships = self._relationship_extractor.extract(document, mentions)
        persisted_relationships: list[GraphRelationship] = []
        for relationship in relationships:
            source = self._resolve_entity(
                relationship.source_name,
                relationship.source_type,
                lookup,
                document_id,
                str(document.source_path),
            )
            target = self._resolve_entity(
                relationship.target_name,
                relationship.target_type,
                lookup,
                document_id,
                str(document.source_path),
            )
            if source.entity_id == target.entity_id:
                continue
            persisted_relationships.append(
                self._relationships.upsert(
                    source_entity_id=source.entity_id,
                    target_entity_id=target.entity_id,
                    relationship_type=relationship.relationship_type,
                    confidence=relationship.confidence,
                    source_document_id=document_id,
                    evidence=relationship.evidence,
                    metadata=relationship.metadata,
                )
            )

        entity_values = tuple({entity.entity_id: entity for entity in lookup.values()}.values())
        embedded_count = self._embed_entities(entity_values)
        return GraphIndexResult(
            document_id=document_id,
            entity_count=len(entity_values),
            relationship_count=len(persisted_relationships),
            embedded_entity_count=embedded_count,
        )

    def document_graph(self, document_id: str) -> GraphDocument:
        entities = self._entities.find_by_document(document_id)
        relationships = self._relationships.find_by_document(document_id)
        path = next(
            (
                str(entity.properties.get("source_path"))
                for entity in entities
                if entity.entity_type is GraphEntityType.DOCUMENT
                and entity.properties.get("source_path")
            ),
            "",
        )
        return GraphDocument(document_id, path, entities, relationships)

    def graph_context(self, query: str, limit: int = 12) -> str:
        return self.search_context(query, limit)

    def search_context(self, query: str, limit: int = 12) -> str:
        seeds: dict[str, GraphEntity] = {}
        for term in dict.fromkeys(re.findall(r"[\w.]+", query, flags=re.UNICODE)):
            if len(term) < 3:
                continue
            for entity in self._entities.search(term, limit=3):
                seeds.setdefault(entity.entity_id, entity)
        if self._embedding_service is not None and self._entity_vectors is not None:
            vector = self._embedding_service.embed_query(query)
            hits = self._entity_vectors.search(
                vector,
                limit=max(limit, 1),
                filters={"source_type": "graph_entity"},
            ).hits
            for hit in hits:
                entity_id = str(hit.payload.metadata.get("entity_id", hit.id))
                entity = self._entities.get(entity_id)
                if entity is not None:
                    seeds.setdefault(entity.entity_id, entity)
        if not seeds:
            return ""

        lines: list[str] = []
        seen_edges: set[str] = set()
        for entity in tuple(seeds.values())[:limit]:
            lines.append(
                f"Entity: {entity.name} ({entity.entity_type.value})"
                + (f" — {entity.description}" if entity.description else "")
            )
            for relationship in self._relationships.find_related(entity.entity_id, limit=limit):
                edge_key = relationship.relationship_id
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                other_id = (
                    relationship.target_entity_id
                    if relationship.source_entity_id == entity.entity_id
                    else relationship.source_entity_id
                )
                other = self._entities.get(other_id)
                if other is None:
                    continue
                relation = relationship.relationship_type.value
                if relationship.source_entity_id == entity.entity_id:
                    lines.append(f"  {entity.name} -[{relation}]-> {other.name}")
                else:
                    lines.append(f"  {other.name} -[{relation}]-> {entity.name}")
                if len(seen_edges) >= limit:
                    break
            if len(seen_edges) >= limit:
                break
        return "\n".join(lines)

    def statistics(self) -> GraphStatistics:
        return self._entities.statistics()

    def reindex(self, documents: Iterable[KnowledgeDocument]) -> int:
        indexed = 0
        for document in documents:
            parsed = self._parser_service.parse_file(document.source_path)
            self.index_document(parsed, document.document_id)
            indexed += 1
        return indexed

    def rebuild(self, documents: Iterable[KnowledgeDocument]) -> int:
        entities = self._entities.list_all()
        if self._entity_vectors is not None and entities:
            self._entity_vectors.delete_embeddings(
                [entity.entity_id for entity in entities]
            )
        self._entities.clear_all()
        return self.reindex(documents)

    def delete_entity(self, entity_id: str) -> bool:
        if self._entity_vectors is not None:
            self._entity_vectors.delete_embeddings([entity_id])
        return self._entities.delete(entity_id)

    def _resolve_entity(
        self,
        name: str,
        entity_type: GraphEntityType,
        lookup: dict[tuple[str, GraphEntityType], GraphEntity],
        document_id: str,
        source_path: str,
    ) -> GraphEntity:
        normalized = normalize_entity_name(name)
        existing = lookup.get((normalized, entity_type))
        if existing is None and entity_type is GraphEntityType.UNKNOWN:
            existing = next(
                (
                    entity
                    for (candidate_name, _), entity in lookup.items()
                    if candidate_name == normalized
                ),
                None,
            )
        if existing is not None:
            return existing
        mention = EntityMention(
            name=name,
            entity_type=entity_type,
            confidence=0.75,
            evidence="Relationship endpoint",
        )
        entity = self._entities.upsert(
            mention,
            source_document_id=document_id,
            source_path=source_path,
        )
        lookup[(normalized, entity_type)] = entity
        return entity

    def _embed_entities(self, entities: tuple[GraphEntity, ...]) -> int:
        if not entities or self._embedding_service is None or self._entity_vectors is None:
            return 0
        texts = tuple(
            "\n".join(
                (
                    f"{entity.name} ({entity.entity_type.value})",
                    entity.description or "",
                    "Aliases: " + ", ".join(entity.aliases),
                    "Properties: "
                    + ", ".join(f"{key}={value}" for key, value in entity.properties.items()),
                )
            ).strip()
            for entity in entities
        )
        vectors = self._embedding_service.embed_texts(texts)
        records = tuple(
            EmbeddingRecord(
                chunk_id=entity.entity_id,
                model_name=self._embedding_service.model_name,
                dimensions=len(vector),
                vector=vector,
                source_path=entity.entity_id,
                document_title=entity.name,
                metadata={
                    "entity_id": entity.entity_id,
                    "entity_type": entity.entity_type.value,
                    "source_type": "graph_entity",
                },
            )
            for entity, vector in zip(entities, vectors, strict=True)
        )
        self._entity_vectors.upsert_embeddings(
            EmbeddingBatchResult(
                source_name="knowledge-graph-entities",
                source_path="graph://entities",
                model_name=self._embedding_service.model_name,
                chunk_count=len(records),
                embedded_count=len(records),
                cache_hits=0,
                cache_misses=len(records),
                records=records,
            )
        )
        for entity in entities:
            self._entities.add_embedding(
                entity.entity_id, entity.entity_id, self._embedding_service.model_name
            )
        return len(records)