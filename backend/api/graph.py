from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api import dependencies
from backend.api.schemas import (
    GraphDocumentResponse,
    GraphEntityResponse,
    GraphOperationResponse,
    GraphRelationshipResponse,
    GraphStatisticsResponse,
)
from backend.graph.models import GraphEntity, GraphEntityType, GraphRelationship
from backend.repositories.graph_entity_repository import GraphEntityRepository
from backend.repositories.graph_relationship_repository import GraphRelationshipRepository
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.services.graph_indexing_service import GraphIndexingService


router = APIRouter(prefix="/api/graph", tags=["knowledge-graph"])


def _entity_response(entity: GraphEntity) -> GraphEntityResponse:
    return GraphEntityResponse(
        entity_id=entity.entity_id,
        name=entity.name,
        normalized_name=entity.normalized_name,
        entity_type=entity.entity_type.value,
        description=entity.description,
        metadata=entity.metadata,
        aliases=list(entity.aliases),
        properties=entity.properties,
        source_document_ids=list(entity.source_document_ids),
    )


def _relationship_response(
    relationship: GraphRelationship,
    entities: GraphEntityRepository,
) -> GraphRelationshipResponse:
    source = entities.get(relationship.source_entity_id)
    target = entities.get(relationship.target_entity_id)
    return GraphRelationshipResponse(
        relationship_id=relationship.relationship_id,
        source_entity_id=relationship.source_entity_id,
        source_name=source.name if source else None,
        target_entity_id=relationship.target_entity_id,
        target_name=target.name if target else None,
        relationship_type=relationship.relationship_type.value,
        confidence=relationship.confidence,
        source_document_id=relationship.source_document_id,
        evidence=relationship.evidence,
        metadata=relationship.metadata,
    )


@router.get("/stats", response_model=GraphStatisticsResponse)
def get_graph_statistics(
    service: GraphIndexingService = Depends(dependencies.get_graph_indexing_service),
) -> GraphStatisticsResponse:
    stats = service.statistics()
    return GraphStatisticsResponse(
        entity_count=stats.entity_count,
        relationship_count=stats.relationship_count,
        entity_types=stats.entity_types,
        most_connected=list(stats.most_connected),
        orphan_entity_count=stats.orphan_entity_count,
        average_degree=stats.average_degree,
    )


@router.get("/entity/search", response_model=list[GraphEntityResponse])
def search_graph_entities(
    q: str = Query(min_length=1, max_length=500),
    entity_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    repository: GraphEntityRepository = Depends(dependencies.get_graph_entity_repository),
) -> list[GraphEntityResponse]:
    selected_type: GraphEntityType | None = None
    if entity_type is not None:
        try:
            selected_type = GraphEntityType(entity_type.casefold())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in GraphEntityType)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown entity type. Allowed values: {allowed}.",
            ) from exc
    return [
        _entity_response(entity)
        for entity in repository.search(q, selected_type, limit)
    ]


@router.get("/entity/{entity_id}", response_model=GraphEntityResponse)
def get_graph_entity(
    entity_id: UUID,
    repository: GraphEntityRepository = Depends(dependencies.get_graph_entity_repository),
) -> GraphEntityResponse:
    entity = repository.get(str(entity_id))
    if entity is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return _entity_response(entity)


@router.get(
    "/entity/{entity_id}/relationships",
    response_model=list[GraphRelationshipResponse],
)
def get_entity_relationships(
    entity_id: UUID,
    entity_repository: GraphEntityRepository = Depends(
        dependencies.get_graph_entity_repository
    ),
    relationship_repository: GraphRelationshipRepository = Depends(
        dependencies.get_graph_relationship_repository
    ),
) -> list[GraphRelationshipResponse]:
    if entity_repository.get(str(entity_id)) is None:
        raise HTTPException(status_code=404, detail="Graph entity not found.")
    return [
        _relationship_response(relationship, entity_repository)
        for relationship in relationship_repository.find_related(str(entity_id))
    ]


@router.get("/document/{document_id}", response_model=GraphDocumentResponse)
def get_document_graph(
    document_id: UUID,
    service: GraphIndexingService = Depends(dependencies.get_graph_indexing_service),
    entity_repository: GraphEntityRepository = Depends(
        dependencies.get_graph_entity_repository
    ),
) -> GraphDocumentResponse:
    graph = service.document_graph(str(document_id))
    if not graph.entities:
        raise HTTPException(status_code=404, detail="No graph data found for this document.")
    return GraphDocumentResponse(
        document_id=graph.document_id,
        source_path=graph.source_path,
        entities=[_entity_response(entity) for entity in graph.entities],
        relationships=[
            _relationship_response(relationship, entity_repository)
            for relationship in graph.relationships
        ],
    )


@router.post("/reindex", response_model=GraphOperationResponse)
def reindex_graph(
    service: GraphIndexingService = Depends(dependencies.get_graph_indexing_service),
    documents: KnowledgeRepository = Depends(dependencies.get_knowledge_repository),
) -> GraphOperationResponse:
    processed = service.reindex(documents.list_documents())
    stats = service.statistics()
    return GraphOperationResponse(
        success=True,
        documents_processed=processed,
        entities_processed=stats.entity_count,
        relationships_processed=stats.relationship_count,
        message="Knowledge graph reindex completed.",
    )


@router.post("/rebuild", response_model=GraphOperationResponse)
def rebuild_graph(
    service: GraphIndexingService = Depends(dependencies.get_graph_indexing_service),
    documents: KnowledgeRepository = Depends(dependencies.get_knowledge_repository),
) -> GraphOperationResponse:
    processed = service.rebuild(documents.list_documents())
    stats = service.statistics()
    return GraphOperationResponse(
        success=True,
        documents_processed=processed,
        entities_processed=stats.entity_count,
        relationships_processed=stats.relationship_count,
        message="Knowledge graph rebuild completed.",
    )


@router.delete("/entity/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_graph_entity(
    entity_id: UUID,
    service: GraphIndexingService = Depends(dependencies.get_graph_indexing_service),
) -> None:
    if not service.delete_entity(str(entity_id)):
        raise HTTPException(status_code=404, detail="Graph entity not found.")
