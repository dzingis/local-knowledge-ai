# API / API sučelje

The backend API is available at `http://localhost:8000`. Open `/docs` for the
interactive API reference.

API pozadinskog sustava dostupan je na adresi `http://localhost:8000`.
Interaktivna dokumentacija API-ja nalazi se na `/docs`.

## Search / Pretraživanje

Send a question in Croatian or English:

Pošaljite pitanje na hrvatskom ili engleskom:

```http
POST /api/search
Content-Type: application/json
```

```json
{
  "query": "Koji je čarobni broj?",
  "limit": 5
}
```

The response contains matching passages and their source paths. / Odgovor
sadrži podudarajuće odlomke i putanje njihovih izvora. Exact contiguous phrase
matches are preferred; if none exist, search falls back to hybrid vector and
keyword retrieval.

Prednost imaju točna, neprekinuta podudaranja izraza; ako ih nema, pretraživanje
se vraća na kombinirano vektorsko pretraživanje i pretraživanje ključnih riječi.

To restrict search to a file type, prefix the query with `SQL:`, `PDF:`,
`DOCX:`, `DELPHI:`, `MARKDOWN:`, or `TEXT:` (for example, `SQL: IBAN`).
Without a recognized prefix, search includes all indexed file types.

Pretraživanje ograničite na vrstu datoteke prefiksom `SQL:`, `PDF:`, `DOCX:`,
`DELPHI:`, `MARKDOWN:` ili `TEXT:` (primjerice `SQL: IBAN`). Bez prepoznatog
prefiksa pretražuju se sve indeksirane vrste datoteka.

In retrieval-backed chat, a plain multiword phrase that exactly occurs in a
retrieved passage is returned as matching text with source links, without
waiting for Ollama to generate a response. Natural-language questions still
use the chat model.

U razgovoru s dohvatom dokumenata, običan višerječni izraz koji se točno
pojavljuje u dohvaćenom odlomku vraća se kao pronađeni tekst s poveznicama na
izvore, bez čekanja da Ollama sastavi odgovor. Pitanja na prirodnom jeziku i
dalje obrađuje jezični model.

## Retrieval-backed chat / Razgovor s dohvatom dokumenata

Open WebUI uses the backend's OpenAI-compatible endpoints:

Open WebUI koristi OpenAI-kompatibilne krajnje točke pozadinskog sustava:

- `GET /v1/models` lists models available through the retrieval-backed API. /
  Ispisuje modele dostupne putem API-ja s dohvatom dokumenata.
- `POST /v1/chat/completions` retrieves local passages before requesting an
  answer from Ollama. / Dohvaća lokalne odlomke prije nego što zatraži odgovor
  od Ollame.

Select a model whose name begins with `lkai-`. Chat responses follow the
language of the latest user message: standard Croatian or English. Responses
include links for each distinct retrieved document. The source endpoint opens
or previews the file where supported; add `?download=true` to download it.
Native `file://` links are included when `WATCH_HOST_PATH` maps `/knowledge`
to an absolute host path, but browser security may block them.
`SOURCE_PUBLIC_BASE_URL` controls the HTTP link base (default:
`http://localhost:8000`) and should be reachable from the user's browser.
Questions about SQL automatically search SQL files only. Questions such as
"Do I have SQL for ..." are answered from a relevant indexed SQL file or report
that no matching SQL file was found; they do not generate example schemas or
queries from model knowledge.

Odaberite model čiji naziv počinje s `lkai-`. Odgovori u razgovoru prate jezik
posljednje korisnikove poruke: standardni hrvatski ili engleski. Odgovori
sadrže poveznice za svaku jedinstvenu dohvaćenu datoteku. Krajnja točka izvora
otvara ili prikazuje datoteku ako preglednik to podržava; dodajte
`?download=true` za preuzimanje. Izravne poveznice `file://` dodaju se kada
`WATCH_HOST_PATH` povezuje `/knowledge` s apsolutnom putanjom na glavnom
računalu, no preglednik ih može blokirati. `SOURCE_PUBLIC_BASE_URL` određuje
osnovnu adresu HTTP poveznice (zadano: `http://localhost:8000`) i mora biti
dostupna pregledniku korisnika.

## Indexed source file / Indeksirana izvorna datoteka

`GET /api/documents/{document_id}/source` serves an indexed source file inline
where supported. Use `GET /api/documents/{document_id}/source?download=true`
to download it. The source must still exist under a configured watched folder.

`GET /api/documents/{document_id}/source` prikazuje indeksiranu izvornu
datoteku ako je podržana. Za preuzimanje upotrijebite
`GET /api/documents/{document_id}/source?download=true`. Datoteka mora i dalje
postojati unutar konfigurirane nadzirane mape.

## Re-indexing / Ponovno indeksiranje

`POST /api/reindex` adds completed queue items to the worker queue again and
rebuilds their SQL and Qdrant index.

`POST /api/reindex` ponovno dodaje dovršene stavke u red radnika te obnavlja
njihov indeks u SQL-u i Qdrantu.

## Knowledge graph / Graf znanja

Apply the graph database migration before using these endpoints. All routes
are under `/api/graph`:

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/graph/stats` | Counts, entity types, orphans, average degree, and most connected entities. |
| `GET` | `/api/graph/entity/search?q=...&entity_type=...&limit=...` | Search canonical names and aliases. `entity_type` and `limit` are optional. |
| `GET` | `/api/graph/entity/{id}` | Return an entity, aliases, properties, and source documents. |
| `GET` | `/api/graph/entity/{id}/relationships` | Return the entity's incoming and outgoing relationships. |
| `GET` | `/api/graph/document/{documentId}` | Return entities and relationships extracted from one document. |
| `POST` | `/api/graph/reindex` | Re-parse indexed documents and add or refresh graph data. |
| `POST` | `/api/graph/rebuild` | Clear the graph and rebuild it from indexed documents. |
| `DELETE` | `/api/graph/entity/{id}` | Delete an entity and its relationships. |

Entity search example:

```http
GET /api/graph/entity/search?q=IBAN&entity_type=procedure&limit=10
```

Chat continues to use document vector and keyword retrieval as its primary
source. It adds relevant graph entities and relationships to the prompt as
supporting context; graph data does not replace retrieved document passages.
Use `/api/graph/reindex` after applying the migration to populate graph records
for documents already indexed before this milestone.

Prije korištenja ovih krajnjih točaka primijenite migraciju baze za graf. Sve
su rute pod `/api/graph` i navedene u tablici iznad. Pretraživanje entiteta
obuhvaća kanonske nazive i njihove alternativne nazive.

Razgovor i dalje prvenstveno koristi vektorsko i tekstno dohvaćanje dokumenata.
Relevantne entitete i veze iz grafa dodaje u upit kao pomoćni kontekst; graf ne
zamjenjuje pronađene odlomke. Nakon migracije pokrenite `/api/graph/reindex`
kako biste popunili graf za dokumente indeksirane prije ove verzije.