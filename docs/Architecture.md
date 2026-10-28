# Architecture / Arhitektura

## Overview / Pregled

Local Knowledge AI is a fully local platform that indexes technical files and
provides semantic search and direct access to source documents.

Local Knowledge AI potpuno je lokalna platforma koja indeksira tehničke
datoteke te omogućuje semantičko pretraživanje i izravan pristup izvornim
dokumentima.

## Core components / Glavne komponente

- **Ollama** — local language-model inference. / lokalno izvođenje jezičnih modela.
- **Open WebUI** — chat interface. / sučelje za razgovor.
- **Qdrant** — vector similarity search. / vektorsko pretraživanje sličnosti.
- **Microsoft SQL Server** — metadata and audit data. / metapodaci i podaci za reviziju.
- **Python backend** — indexing, parsing, and API services. / indeksiranje, parsiranje i API servisi.

## Data flow / Tijek obrade

1. A file watcher detects new or changed files and enqueues them in `AI.IngestionQueue`. / Nadzor mapa otkriva nove ili promijenjene datoteke i dodaje ih u `AI.IngestionQueue`.
2. The existing processing worker parses and chunks each file. SQL Server scripts use SQLGlot's T-SQL AST to record definitions, parameters, and read/write dependencies, with a regex fallback for unsupported syntax. The PDF parser uses local Tesseract OCR for embedded page images (English and Croatian). / Postojeći radnik parsira datoteke i dijeli ih na odlomke. SQL Server skripte koriste SQLGlotov T-SQL AST za bilježenje definicija, parametara i ovisnosti čitanja/pisanja, uz rezervni regex parser za nepodržanu sintaksu. Parser PDF-a koristi lokalni Tesseract OCR za ugrađene slike stranica (engleski i hrvatski).
3. The graph extraction services derive entities and confidence-scored relationships from the parsed document. SQL stores the graph and document provenance; entity vectors are stored separately from chunk vectors in Qdrant. / Servisi grafa izdvajaju entitete i veze s pouzdanošću iz parsiranog dokumenta. SQL pohranjuje graf i porijeklo podataka, a vektori entiteta odvojeni su od vektora odlomaka u Qdrantu.
4. SQL Server stores document metadata, chunks, hashes, and vector references. Persistent Qdrant stores chunk vectors keyed by SQL chunk IDs. / SQL Server pohranjuje metapodatke dokumenata, odlomke, sažetke i reference na vektore. Trajni Qdrant pohranjuje vektore odlomaka povezane s ID-ovima odlomaka u SQL-u.
5. `POST /api/search` combines vector search and SQL keyword matching. Chat also expands retrieved context through the graph; semantic document search remains the primary retrieval path. / `POST /api/search` objedinjuje vektorsko pretraživanje i SQL pretraživanje po ključnim riječima. Razgovor dodatno proširuje kontekst grafom; semantičko pretraživanje dokumenata ostaje glavni način dohvaćanja.
6. Open WebUI sends chat requests to the backend's OpenAI-compatible `/v1` API. The backend adds retrieved passages and graph facts to the Ollama prompt. / Open WebUI šalje upite za razgovor na pozadinski sustav putem OpenAI-kompatibilnog API-ja `/v1`. Pozadinski sustav dodaje dohvaćene odlomke i činjenice iz grafa u upit za Ollamu.

## Knowledge graph / Graf znanja

The graph is an extension of the existing parser queue pipeline, not a second
ingestion path. `EntityExtractionService` and
`RelationshipExtractionService` process the shared `ParsedDocument` before
embedding; `GraphIndexingService` persists entities and document-scoped edges
after the SQL document ID is available. `Graph.EntityEmbedding` tracks entity
vectors in the dedicated `local-knowledge-entities` Qdrant collection.
Hybrid chat search combines those graph matches and their neighbors with the
existing retrieved passages. Use `/api/graph/reindex` to add or refresh graph
data for indexed documents and `/api/graph/rebuild` to clear and recreate it.

The existing dependency-injected `ParserQueueProcessor` coordinates this
sequence: parse, chunk, establish the SQL document ID, extract entities and
relationships, persist graph data, then embed and index the original chunks.
Graph services do not parse files independently and do not replace the
existing chunk-ingestion path. SQL definitions and dependencies use the
SQLGlot T-SQL parser metadata; Python, Delphi, Swagger/OpenAPI JSON or YAML,
XML, and prose use syntax-aware or deterministic pattern extraction.
Relationships retain their type, confidence, evidence, and source document.

At chat time, `KnowledgeSearchService` still retrieves document passages
through the existing vector and keyword routes. `GraphIndexingService`
expands matching graph entities to their relationships; the chat service adds
those facts beside (not instead of) the retrieved excerpts in its grounding
prompt. SQL persistence is provided by `GraphEntityRepository` and
`GraphRelationshipRepository`; `backend/api/graph.py` exposes graph reads,
statistics, deletion, and rebuild operations.

## Supported content types / Podržane vrste sadržaja

PDF, DOCX, SQL, Delphi, Swagger/OpenAPI, XML, JSON, Markdown, and plain text.

PDF, DOCX, SQL, Delphi, Swagger/OpenAPI, XML, JSON, Markdown i običan tekst.

## Design principles / Načela dizajna

- Local first. / Lokalna obrada ima prednost.
- Reproducible and auditable. / Ponovljivost i mogućnost revizije.
- Metadata rich. / Bogati metapodaci.
- Easy to extend. / Jednostavno proširivanje.
- Direct access to original files. / Izravan pristup izvornim datotekama.
