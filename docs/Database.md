# Database

SQL Server stores repository metadata, indexing state, and relationships between documents and chunks.

## Core tables
- Documents
- DocumentVersions
- Chunks
- Tags
- DocumentTags
- Folders
- FileTypes
- IndexRuns
- SearchQueries
- SearchResults

## Notes
- Full file paths are stored for direct opening of source documents.
- Chunk-level metadata includes page number, heading, and offsets when available.
- Embedding vectors are stored in Qdrant, while SQL Server keeps the authoritative metadata.

## Ingestion queue

The backend queue repository requires `AI.IngestionQueue` in the configured
`AIKnowledge` database. For an existing database, run
[`database/migrations/001-create-ingestion-queue.sql`](../database/migrations/001-create-ingestion-queue.sql)
once using SQL Server Management Studio or `sqlcmd`. Fresh database bootstrap
also creates the queue table through [`database/bootstrap.sql`](../database/bootstrap.sql).
