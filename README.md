# Local Knowledge AI

A fully local AI knowledge platform for PDFs, Word documents, SQL, Delphi, Swagger and other technical documentation.

## Goals
- Keep all data local
- Search documents semantically and by keywords
- Open the original file directly from search results
- Support SQL Server for metadata and Qdrant for vectors
- Use Ollama and Open WebUI for local LLM chat

## Planned stack
- Ollama
- Open WebUI
- Qdrant
- Microsoft SQL Server
- FastAPI
- Python

## Repository structure
- `docs/` architecture and roadmap
- `database/` SQL Server schema and scripts
- `backend/` Python services
- `scripts/` setup helpers
- `config/` runtime configuration

## Milestone 1
Foundation work:
- local LLM setup
- chat UI
- metadata database
- vector database
- document indexing base
- configuration and service bootstrap

## Status
Initial project skeleton.

## Automatic folder watcher

Set `WATCH_ENABLED=true` to enqueue files created or changed in `WATCH_FOLDERS`.
The watcher uses the existing ingestion queue; parsing, chunking, embedding, and
indexing remain the responsibility of the background worker.

```dotenv
WATCH_ENABLED=true
WATCH_LOCAL_ENABLED=true
WATCH_NETWORK_ENABLED=false
WATCH_FOLDERS=/knowledge,\\server\share
WATCH_RECURSIVE=true
WATCH_DEBOUNCE_SECONDS=2
WATCH_POLL_INTERVAL=30
WATCH_IGNORE_PATTERNS=~$*,*.tmp,*.part
```

`WATCH_ENABLED` is the master switch. Local and network flags control their
respective paths in `WATCH_FOLDERS`; UNC paths beginning with `\\` (or `//`)
are treated as network paths. Set both flags to `true` to watch both. Multiple
folders can be provided as a comma-separated list or JSON array. For Docker,
folders must be mounted into the backend container. `WATCH_HOST_PATH` selects
the host folder mounted at `/knowledge` (default: `./knowledge`), while
`WATCH_FOLDERS` contains container paths.

The watcher health endpoint is available at `GET /watcher`.
