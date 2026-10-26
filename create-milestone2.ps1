# ===========================================
# Local Knowledge AI - Milestone 2 Structure
# ===========================================

$root = "D:\Projects\local-knowledge-ai"

$files = @(

# -----------------------------
# Indexer
# -----------------------------
"backend\indexer\scanner.py",
"backend\indexer\hashing.py",
"backend\indexer\index_manager.py",
"backend\indexer\sql_queue_repository.py",
"backend\indexer\processing_worker.py",
"backend\indexer\background_scheduler.py",

# -----------------------------
# Parsers
# -----------------------------
"backend\parsers\__init__.py",
"backend\parsers\base_parser.py",
"backend\parsers\parser_result.py",
"backend\parsers\sql_parser.py",
"backend\parsers\pdf_parser.py",
"backend\parsers\word_parser.py",
"backend\parsers\delphi_parser.py",
"backend\parsers\markdown_parser.py",
"backend\parsers\text_parser.py",

# -----------------------------
# Chunking
# -----------------------------
"backend\chunking\__init__.py",
"backend\chunking\chunk_engine.py",
"backend\chunking\chunk_models.py",
"backend\chunking\token_counter.py",

# -----------------------------
# Embeddings
# -----------------------------
"backend\embeddings\__init__.py",
"backend\embeddings\embedding_service.py",
"backend\embeddings\embedding_cache.py",
"backend\embeddings\ollama_client.py",

# -----------------------------
# Qdrant
# -----------------------------
"backend\vectorstore\__init__.py",
"backend\vectorstore\qdrant_client.py",
"backend\vectorstore\collection_manager.py",
"backend\vectorstore\vector_repository.py",

# -----------------------------
# SQL Repository
# -----------------------------
"backend\repositories\__init__.py",
"backend\repositories\document_repository.py",
"backend\repositories\chunk_repository.py",
"backend\repositories\embedding_repository.py",
"backend\repositories\conversation_repository.py",
"backend\repositories\prompt_repository.py",
"backend\repositories\model_repository.py",
"backend\repositories\source_repository.py",

# -----------------------------
# API
# -----------------------------
"backend\api\scan.py",
"backend\api\documents.py",
"backend\api\queue.py",
"backend\api\status.py",
"backend\api\stats.py",
"backend\api\models.py",

# -----------------------------
# Services
# -----------------------------
"backend\services\ingestion_service.py",
"backend\services\document_service.py",
"backend\services\search_service.py",
"backend\services\conversation_service.py",

# -----------------------------
# Workers
# -----------------------------
"backend\workers\worker.py",
"backend\workers\worker_pool.py",
"backend\workers\retry_manager.py",

# -----------------------------
# Logging
# -----------------------------
"backend\logging\logger.py",
"backend\logging\performance_logger.py",
"backend\logging\audit_logger.py",

# -----------------------------
# Tests
# -----------------------------
"tests\test_scanner.py",
"tests\test_hashing.py",
"tests\test_sql_parser.py",
"tests\test_pdf_parser.py",
"tests\test_word_parser.py",
"tests\test_delphi_parser.py",
"tests\test_markdown_parser.py",
"tests\test_text_parser.py",
"tests\test_chunking.py",
"tests\test_embeddings.py",
"tests\test_qdrant.py",
"tests\test_api.py",
"tests\test_worker.py",

# -----------------------------
# Documentation
# -----------------------------
"docs\architecture.md",
"docs\database.md",
"docs\api.md",
"docs\deployment.md",
"docs\developer-guide.md",
"docs\parsers.md",
"docs\sequence-diagrams.md",
"docs\milestone2.md"
)

foreach ($file in $files)
{
    $full = Join-Path $root $file

    $dir = Split-Path $full

    if (!(Test-Path $dir))
    {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    if (!(Test-Path $full))
    {
        New-Item -ItemType File -Force -Path $full | Out-Null
        Write-Host "Created $file"
    }
    else
    {
        Write-Host "Exists  $file"
    }
}

Write-Host ""
Write-Host "Milestone 2 structure complete."