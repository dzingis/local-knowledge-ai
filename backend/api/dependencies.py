from __future__ import annotations

from functools import lru_cache

from backend.chunking.chunk_engine import ChunkEngine, ChunkingConfig
from backend.embeddings.embedding_cache import InMemoryEmbeddingCache
from backend.embeddings.embedding_service import EmbeddingService, OllamaEmbeddingProvider
from backend.indexer.index_manager import IndexManager
from backend.indexer.sql_queue_repository import SqlQueueRepository
from backend.parsers.parser_service import ParserService
from backend.repositories.chunk_repository import ChunkRepository
from backend.repositories.conversation_repository import ConversationRepository
from backend.repositories.document_repository import DocumentRepository
from backend.repositories.embedding_repository import EmbeddingRepository
from backend.repositories.model_repository import ModelRepository
from backend.repositories.prompt_repository import PromptRepository
from backend.vectorstore.qdrant_client import InMemoryQdrantClient
from backend.vectorstore.qdrant_repository import QdrantRepository
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
def get_qdrant_client() -> InMemoryQdrantClient:
    return InMemoryQdrantClient()


@lru_cache(maxsize=1)
def get_qdrant_repository() -> QdrantRepository:
    return QdrantRepository(client=get_qdrant_client())


@lru_cache(maxsize=1)
def get_processing_worker() -> ProcessingWorker:
    return ProcessingWorker(
        repository=get_sql_queue_repository(),
        processor=ParserQueueProcessor(
            parser_service=get_parser_service(),
            chunk_engine=get_chunk_engine(),
            embedding_service=get_embedding_service(),
            qdrant_repository=get_qdrant_repository(),
        ),
    )


@lru_cache(maxsize=1)
def get_index_manager() -> IndexManager:
    return IndexManager()


@lru_cache(maxsize=1)
def get_document_repository() -> DocumentRepository:
    return DocumentRepository(
        chunk_repository=get_chunk_repository(),
        embedding_repository=get_embedding_repository(),
        qdrant_repository=get_qdrant_repository(),
    )


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
