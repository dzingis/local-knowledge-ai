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
