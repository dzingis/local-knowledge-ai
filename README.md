# Local Knowledge AI / Lokalna umjetna inteligencija za znanje

Local Knowledge AI is a fully local platform for searching PDFs, Word files,
SQL, Delphi, Swagger, and other technical documents.

Local Knowledge AI potpuno je lokalna platforma za pretraživanje PDF-ova,
Wordovih dokumenata, SQL-a, Delphija, Swaggera i druge tehničke dokumentacije.

## Goals / Ciljevi

- Keep all data local. / Svi podaci ostaju lokalno.
- Search documents semantically and by keywords. / Semantičko pretraživanje dokumenata i pretraživanje po ključnim riječima.
- Open the original file from search results. / Otvaranje izvorne datoteke iz rezultata pretraživanja.
- Use SQL Server for metadata and Qdrant for vectors. / SQL Server za metapodatke i Qdrant za vektore.
- Use Ollama and Open WebUI for local AI chat. / Ollama i Open WebUI za lokalni razgovor s umjetnom inteligencijom.

## Technology / Tehnologije

Ollama, Open WebUI, Qdrant, Microsoft SQL Server, FastAPI, and Python.

Ollama, Open WebUI, Qdrant, Microsoft SQL Server, FastAPI i Python.

## Repository structure / Struktura repozitorija

- `docs/` — architecture and guides. / arhitektura i vodiči.
- `database/` — SQL Server schema and scripts. / shema i skripte za SQL Server.
- `backend/` — Python services. / Python servisi.
- `scripts/` — setup helpers. / pomoćne skripte za postavljanje.
- `config/` — runtime configuration. / konfiguracija izvođenja.

## Project status / Stanje projekta

The project includes folder watching, document ingestion, indexing, and
retrieval-backed chat through the backend API.

The PDF parser also runs local Tesseract OCR on pages containing embedded
images. This makes text in scanned pages and screenshots searchable, including
English and Croatian error messages. Rebuild the backend image after updating
to install Tesseract and its English/Croatian language data:
`docker compose up -d --build backend`.

Projekt uključuje nadzor mapa, unos dokumenata, indeksiranje i razgovor
potpomognut dohvatom dokumenata putem API-ja pozadinskog sustava.

## Automatic folder watcher / Automatski nadzor mapa

Set `WATCH_ENABLED=true` to add new or changed files from `WATCH_FOLDERS` to
the ingestion queue. The background worker handles parsing, chunking, embedding,
and indexing.

Postavite `WATCH_ENABLED=true` kako bi se nove ili promijenjene datoteke iz
`WATCH_FOLDERS` dodale u red čekanja za unos. Pozadinski radnik obrađuje
datoteke, dijeli ih na odlomke, izrađuje vektore i indeksira ih.

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
respective paths. UNC paths beginning with `\\` or `//` are network paths.
Multiple folders can be supplied as a comma-separated list or JSON array. For
Docker, mount each watched host folder into the backend container.

`WATCH_ENABLED` je glavna sklopka. Zasebne postavke uključuju lokalne i mrežne
putanje. UNC putanje koje počinju s `\\` ili `//` smatraju se mrežnima. Više
mapa može se navesti odvojeno zarezima ili kao JSON polje. U Dockeru mapu s
računala domaćina treba montirati u spremnik pozadinskog sustava.

Watcher health endpoint: `GET /watcher`.

Provjera stanja nadzora mapa: `GET /watcher`.

## Indexing and search / Indeksiranje i pretraživanje

The worker stores document metadata and extracted chunks in SQL Server
(`AI.Document`, `AI.DocumentVersion`, `AI.DocumentChunk`, `AI.Embedding`, and
`AI.FileHash`). Vector values are stored in persistent Qdrant. SQL stores the
model name and Qdrant vector ID, not the vector values.

Radnik pohranjuje metapodatke dokumenata i izdvojene odlomke u SQL Server
(`AI.Document`, `AI.DocumentVersion`, `AI.DocumentChunk`, `AI.Embedding` i
`AI.FileHash`). Vrijednosti vektora pohranjuju se u trajnom Qdrantu. SQL sadrži
naziv modela i Qdrantov ID vektora, a ne same vrijednosti vektora.

Search: `POST /api/search`.

Pretraživanje: `POST /api/search`.

```json
{
  "query": "What is the magic number?",
  "limit": 5
}
```

The response contains the matching text and source path. Search uses Ollama
embeddings and SQL keyword matching. Re-index older files with
`POST /api/reindex`.

Odgovor sadrži podudarajući tekst i putanju izvornika. Pretraživanje koristi
Ollamine vektore i SQL pretraživanje ključnih riječi. Starije datoteke ponovno
indeksirajte pozivom `POST /api/reindex`.

Open WebUI connects to the backend at `http://backend:8000/v1`. Select a model
whose name starts with `lkai-` (for example, `lkai-qwen2.5:3b`) to use document
retrieval. Direct Ollama model access is disabled in Open WebUI so chats cannot
silently bypass document retrieval. Chat answers use Croatian or English,
following the language of the user's latest message. Croatian answers use
standard Croatian. Answers cite each distinct retrieved file. The filename
link opens or previews the indexed source through the backend, and a separate
download link is available. When `WATCH_HOST_PATH` is set to the absolute host
folder mounted at `/knowledge`, citations also include a best-effort native
file link; browsers may block opening local files directly. Set
`WATCH_HOST_PATH` in `.env` to the absolute host path of the watched folder to
enable that link.
Slow local model responses may take up to 180 seconds by default; configure
`OLLAMA_CHAT_TIMEOUT_SECONDS` in `.env` to change this limit.

Open WebUI povezuje se s pozadinskim sustavom na adresi
`http://backend:8000/v1`. Odaberite model čiji naziv počinje s `lkai-`
(primjerice `lkai-qwen2.5:3b`) kako biste koristili dohvat dokumenata. Odgovori
u razgovoru bit će na hrvatskom ili engleskom, ovisno o jeziku posljednje
korisnikove poruke. Odgovori na hrvatskom koriste standardni hrvatski jezik.
Izravan pristup Ollami u Open WebUIju isključen je kako razgovor ne bi zaobišao
dohvat dokumenata. Odgovori navode svaku jedinstvenu dohvaćenu datoteku.
Poveznica na naziv datoteke otvara ili prikazuje izvor putem pozadinskog
sustava, a dostupna je i zasebna poveznica za preuzimanje. Ako je
`WATCH_HOST_PATH` postavljen na apsolutnu putanju glavnog računala montiranu u
`/knowledge`, citati sadrže i izravnu poveznicu na datoteku; preglednici mogu
blokirati izravno otvaranje lokalnih datoteka. Za tu poveznicu postavite
`WATCH_HOST_PATH` u datoteci `.env` na apsolutnu putanju nadzirane mape na
glavnom računalu. Spori lokalni modeli imaju zadano do 180 sekundi za odgovor;
vrijednost se može promijeniti postavkom `OLLAMA_CHAT_TIMEOUT_SECONDS` u `.env`.
