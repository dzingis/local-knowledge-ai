# Architecture

## Overview
Local Knowledge AI is a fully local document intelligence platform that indexes technical files and exposes semantic search plus direct file access.

## Core components
- **Ollama** for local LLM inference
- **Open WebUI** for chat and user interaction
- **Qdrant** for vector similarity search
- **Microsoft SQL Server** for metadata, relationships, and audit data
- **Python backend** for indexing, parsing, and API services

## Data flow
1. A file watcher detects new or changed files.
2. Parsers extract text and structural metadata.
3. Chunks are stored in Qdrant with embeddings.
4. Metadata and file paths are stored in SQL Server.
5. The API combines semantic search, keyword search, and metadata lookup.
6. The UI displays answers with direct links to the original files.

## Supported content types
- PDF
- DOCX
- SQL
- Delphi source
- Swagger/OpenAPI
- XML / JSON
- Markdown and text

## Design principles
- Local first
- Reproducible and auditable
- Metadata rich
- Easy to extend
- Direct access to original files
