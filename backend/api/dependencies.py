from __future__ import annotations

from functools import lru_cache

from backend.chat.ollama_chat import OllamaRagChatService
from backend.chunking.chunk_engine import ChunkEngine, ChunkingConfig
from backend.config.settings import get_settings
from backend.embeddings.embedding_cache import InMemoryEmbeddingCache
from backend.embeddings.embedding_service import EmbeddingService, OllamaEmbeddingProvider
from backend.indexer.index_manager import IndexManager
from backend.indexer.sql_queue_repository import SqlQueueRepository
from backend.parsers.parser_service import ParserService
from backend.repositories.chunk_repository import ChunkRepository
from backend.repositories.conversation_repository import ConversationRepository
from backend.repositories.embedding_repository import EmbeddingRepository
from backend.repositories.graph_entity_repository import GraphEntityRepository
from backend.repositories.graph_relationship_repository import GraphRelationshipRepository
from backend.repositories.knowledge_repository import KnowledgeRepository
from backend.repositories.model_repository import ModelRepository
from backend.repositories.prompt_repository import PromptRepository
from backend.search.service import KnowledgeSearchService
from backend.services.entity_extraction_service import EntityExtractionService
from backend.services.graph_indexing_service import GraphIndexingService
from backend.services.relationship_extraction_service import RelationshipExtractionService
from backend.vectorstore.qdrant_client import QdrantServiceClient
from backend.vectorstore.qdrant_repository import QdrantRepository, QdrantRepositoryConfig
from backend.watchers.watch_service import WatchService
from backend.workers.processing_worker import ParserQueueProcessor, ProcessingWorker


@lru_cache(maxsize=1)
def get_sql_queue_repository() -> SqlQueueRepository:
    return SqlQueueRepository()


@lru_cache(maxsize=1)
def get_parser_service() -> ParserService:
    return ParserService()


@lru_cache(maxsize=1)
def get_chunk_engine() -> ChunkEngine:
    return ChunkEngine(ChunkingConfig())


@lru_cache(maxsize=1)
def get_embedding_cache() -> InMemoryEmbeddingCache:
    return InMemoryEmbeddingCache()


@lru_cache(maxsize=1)
def get_embedding_provider() -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider()


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(
        provider=get_embedding_provider(),
        cache=get_embedding_cache(),
    )


@lru_cache(maxsize=1)
def get_search_service() -> KnowledgeSearchService:
    return KnowledgeSearchService(
        embedding_service=get_embedding_service(),
        qdrant_repository=get_qdrant_repository(),
        knowledge_repository=get_knowledge_repository(),
        graph_indexing_service=get_graph_indexing_service(),
    )


@lru_cache(maxsize=1)
def get_chat_service() -> OllamaRagChatService:
    return OllamaRagChatService(search_service=get_search_service())


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantServiceClient:
    settings = get_settings()
    return QdrantServiceClient(host=settings.qdrant_host, port=settings.qdrant_port)


@lru_cache(maxsize=1)
def get_qdrant_repository() -> QdrantRepository:
    return QdrantRepository(client=get_qdrant_client())


@lru_cache(maxsize=1)
def get_graph_entity_vector_repository() -> QdrantRepository:
    return QdrantRepository(
        client=get_qdrant_client(),
        config=QdrantRepositoryConfig(
            collection_name="local-knowledge-entities",
            default_limit=10,
        ),
    )


@lru_cache(maxsize=1)
def get_graph_entity_repository() -> GraphEntityRepository:
    return GraphEntityRepository()


@lru_cache(maxsize=1)
def get_graph_relationship_repository() -> GraphRelationshipRepository:
    return GraphRelationshipRepository()


@lru_cache(maxsize=1)
def get_entity_extraction_service() -> EntityExtractionService:
    return EntityExtractionService()


@lru_cache(maxsize=1)
def get_relationship_extraction_service() -> RelationshipExtractionService:
    return RelationshipExtractionService()


@lru_cache(maxsize=1)
def get_graph_indexing_service() -> GraphIndexingService:
    return GraphIndexingService(
        entity_extraction_service=get_entity_extraction_service(),
        relationship_extraction_service=get_relationship_extraction_service(),
        entity_repository=get_graph_entity_repository(),
        relationship_repository=get_graph_relationship_repository(),
        parser_service=get_parser_service(),
        embedding_service=get_embedding_service(),
        entity_vector_repository=get_graph_entity_vector_repository(),
    )


@lru_cache(maxsize=1)
def get_processing_worker() -> ProcessingWorker:
    return ProcessingWorker(
        repository=get_sql_queue_repository(),
        processor=ParserQueueProcessor(
            parser_service=get_parser_service(),
            chunk_engine=get_chunk_engine(),
            embedding_service=get_embedding_service(),
            qdrant_repository=get_qdrant_repository(),
            knowledge_repository=get_knowledge_repository(),
            graph_indexing_service=get_graph_indexing_service(),
        ),
    )


@lru_cache(maxsize=1)
def get_background_worker_service() -> ProcessingWorker:
    return get_processing_worker()


@lru_cache(maxsize=1)
def get_watch_service() -> WatchService:
    return WatchService(repository=get_sql_queue_repository())


@lru_cache(maxsize=1)
def get_index_manager() -> IndexManager:
    return IndexManager()


@lru_cache(maxsize=1)
def get_document_repository() -> KnowledgeRepository:
    return get_knowledge_repository()


@lru_cache(maxsize=1)
def get_knowledge_repository() -> KnowledgeRepository:
    return KnowledgeRepository(qdrant_repository=get_qdrant_repository())


@lru_cache(maxsize=1)
def get_chunk_repository() -> ChunkRepository:
    return ChunkRepository()


@lru_cache(maxsize=1)
def get_embedding_repository() -> EmbeddingRepository:
    return EmbeddingRepository()


@lru_cache(maxsize=1)
def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository()


@lru_cache(maxsize=1)
def get_prompt_repository() -> PromptRepository:
    return PromptRepository()


@lru_cache(maxsize=1)
def get_model_repository() -> ModelRepository:
    return ModelRepository()
