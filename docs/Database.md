# Database / Baza podataka

SQL Server stores document metadata, indexing state, and relationships between
documents and chunks.

SQL Server pohranjuje metapodatke dokumenata, stanje indeksiranja i veze između
dokumenata i odlomaka.

## Tables used by ingestion / Tablice koje koristi unos

- `AI.Document` — document path, name, size, checksum, and indexing dates. / putanja, naziv, veličina, sažetak i datumi indeksiranja.
- `AI.DocumentVersion` — indexed document versions. / indeksirane verzije dokumenta.
- `AI.DocumentChunk` — extracted text chunks. / odlomci izdvojenog teksta.
- `AI.Embedding` — embedding model and Qdrant vector ID. / embedding model i Qdrantov ID vektora.
- `AI.FileHash` — hash-based file tracking. / praćenje datoteka pomoću sažetka.
- `AI.IngestionQueue` — watcher and worker queue state. / stanje reda čekanja nadzora i radnika.
- `AI.Tag` and `AI.DocumentTag` — document labels. / oznake dokumenata.

The vector values themselves are stored in Qdrant, not in SQL Server. Chunk
text is stored in SQL Server and is used to return readable search results.

Same vrijednosti vektora pohranjuju se u Qdrantu, a ne u SQL Serveru. Tekst
odlomaka pohranjuje se u SQL Serveru i koristi se za čitljive rezultate
pretraživanja.

## Knowledge graph / Graf znanja

Run
[`database/migrations/002-create-knowledge-graph.sql`](../database/migrations/002-create-knowledge-graph.sql)
once against the configured `AIKnowledge` database before starting the updated
backend. If an earlier Knowledge Graph schema already created
`Graph.Entity` or `Graph.Relationship`, rerun the updated script: it adds and
backfills current columns from legacy `EntityName`, `SourceEntity`,
`TargetEntity`, and `Weight` columns. Legacy columns and their values are
retained; no graph tables are dropped. The script is safe to rerun.

Migration creates:

- `Graph.Entity` — normalized canonical entities and metadata.
- `Graph.EntityAlias` — searchable aliases for canonical entities.
- `Graph.EntityProperty` — extensible key/value properties.
- `Graph.EntityDocument` — per-document provenance, evidence, and confidence.
- `Graph.Relationship` — directed typed edges with confidence and provenance.
- `Graph.EntityEmbedding` — entity-to-Qdrant point and model references.

Entity vectors are stored in the dedicated Qdrant collection
`local-knowledge-entities`; the existing chunk collection is not changed.
Document IDs in graph rows use the same UUID values as the application
document repository.

Pokrenite skriptu
[`database/migrations/002-create-knowledge-graph.sql`](../database/migrations/002-create-knowledge-graph.sql)
jednom nad konfiguriranom bazom `AIKnowledge` prije pokretanja ažuriranog
pozadinskog sustava. Ako je ranija verzija grafa već stvorila
`Graph.Entity` ili `Graph.Relationship`, ponovno pokrenite ažuriranu skriptu:
dodaje trenutačne stupce i popunjava ih iz starih stupaca `EntityName`,
`SourceEntity`, `TargetEntity` i `Weight`. Stari stupci i njihovi podaci ostaju;
tablice grafa se ne brišu. Skripta se može sigurno ponovno pokretati.

Skripta stvara:

- `Graph.Entity` — normalizirane kanonske entitete i metapodatke.
- `Graph.EntityAlias` — pretražive nazive entiteta.
- `Graph.EntityProperty` — proširiva svojstva ključ/vrijednost.
- `Graph.EntityDocument` — porijeklo, dokaze i pouzdanost po dokumentu.
- `Graph.Relationship` — usmjerene veze s vrstom i pouzdanošću.
- `Graph.EntityEmbedding` — reference na Qdrant točke i modele.

Vektori entiteta pohranjuju se u zasebnoj Qdrant kolekciji
`local-knowledge-entities`; postojeća kolekcija odlomaka ostaje nepromijenjena.
ID-ovi dokumenata u grafu jednaki su UUID vrijednostima iz repozitorija
dokumenata aplikacije.

## Ingestion queue / Red čekanja za unos

The backend requires `AI.IngestionQueue` in the configured `AIKnowledge`
database. For an existing database, run
[`database/migrations/001-create-ingestion-queue.sql`](../database/migrations/001-create-ingestion-queue.sql)
once in SQL Server Management Studio or with `sqlcmd`. Fresh database setup
also creates the table through [`database/bootstrap.sql`](../database/bootstrap.sql).

Pozadinski sustav zahtijeva tablicu `AI.IngestionQueue` u konfiguriranoj bazi
`AIKnowledge`. Za postojeću bazu jednom pokrenite skriptu
[`database/migrations/001-create-ingestion-queue.sql`](../database/migrations/001-create-ingestion-queue.sql)
u SQL Server Management Studiju ili pomoću alata `sqlcmd`. Skripta
[`database/bootstrap.sql`](../database/bootstrap.sql) stvara tablicu pri
postavljanju nove baze.
