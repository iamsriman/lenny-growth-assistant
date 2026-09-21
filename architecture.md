# Architecture

## 1. Component boundaries

```
frontend/src/
  App.jsx              session state, stream consumption, layout
  lib/api.js           the only module that knows the API exists
  components/          presentational; none of them fetch

backend/app/
  main.py              app factory, middleware, error handlers, lifespan
  config.py            every tunable, from the environment
  api/routes/          HTTP only: validation, status codes, serialisation
  agent/               routing and orchestration; the only module that
                       composes retrieval + skills + persistence
  agent/skills/        prompts and validators; no HTTP, no DB
  rag/                 chunking, ingestion, retrieval; no knowledge of HTTP
  llm/                 vendor SDKs live here and nowhere else
  security/            artifact sanitisation
  db/                  models and the session factory
```

The rule that keeps this honest: **dependencies point downward only.**
`api/routes` may import `agent`; `agent` may import `rag`, `llm`, `security`,
`db`; `rag` and `llm` import `config` and each other's interfaces, never
`agent` or `api`. Nothing below `api` imports FastAPI. That is why the test
suite can exercise routing, retrieval and the Ship 30 validator without an HTTP
client, and why swapping a vendor touches exactly one directory.

---

## 2. Database schema

PostgreSQL. `JSON` (not `JSONB`) is used deliberately so the identical models
run on SQLite during tests.

```
chat_sessions
  id              varchar(36) PK       uuid4
  title           varchar(200)         derived from the first user message
  user_id         varchar(120) IDX     "user metadata"; ready for auth
  user_agent      varchar(400)
  client_ip       varchar(64)
  provider        varchar(32)          provider active when the session ran
  model           varchar(120)
  meta            json
  created_at      timestamptz
  updated_at      timestamptz          onupdate
  archived        boolean

messages
  id              varchar(36) PK
  session_id      FK -> chat_sessions.id  ON DELETE CASCADE, IDX
  role            varchar(16)          user | assistant | system
  content         text
  skill           varchar(48)          which skill produced it
  provider        varchar(32)          per message, not per session: a session
  model           varchar(120)         that spans a toggle stays auditable
  latency_ms      integer
  grounded        boolean
  citations       json                 frozen at answer time
  meta            json                 route decision, retrieval stats, critique
  created_at      timestamptz

artifacts
  id                 varchar(36) PK
  session_id         FK -> chat_sessions.id  ON DELETE CASCADE, IDX
  message_id         varchar(36)       the assistant turn that produced it
  kind               varchar(16)       markdown | html
  title              varchar(240)
  source             text              raw model output, kept for auditing
  rendered           text              sanitised, safe to embed
  sanitiser_report   json              what was removed and why
  version            integer
  created_at         timestamptz

transcript_documents
  id              varchar(36) PK
  external_id     varchar(255) UNIQUE IDX   stable id from the file
  title           varchar(400)
  guest           varchar(240)
  show            varchar(120)
  url             varchar(600)
  published_at    varchar(40)
  synthetic       boolean            true for the shipped samples
  content_hash    varchar(64) IDX    sha256; drives incremental ingestion
  n_chunks        integer
  meta            json
  ingested_at     timestamptz

transcript_chunks
  id              varchar(36) PK
  document_id     FK -> transcript_documents.id  ON DELETE CASCADE, IDX
  ordinal         integer
  text            text
  speaker         varchar(160)
  start_label     varchar(32)        timestamp as it appeared
  token_estimate  integer
  embedding       json               float vector
  embedding_model varchar(120)       which model produced it — see §4.4
  INDEX (document_id, ordinal)

run_events                           observability trail, one row per agent leg
  id              varchar(36) PK
  session_id      varchar(36) IDX
  request_id      varchar(32) IDX
  component       varchar(32)        agent | retrieval | llm | artifact
  event           varchar(64)        route | retrieve | ship30_critique | ...
  status          varchar(16)        ok | error
  duration_ms     float
  detail          json
  created_at      timestamptz
```

**Two decisions worth defending.**

*Citations are denormalised onto `messages` rather than joined from
`transcript_chunks`.* An answer must remain reproducible after the corpus is
re-ingested. If the chunk text changed, a join would silently show the user a
different quote from the one the model actually read.

*`embedding_model` is stored per chunk.* Mixing embedding models in one index
is the classic RAG bug: the vectors are incomparable and retrieval degrades in
a way that looks like a model-quality problem. Storing the label lets the
retriever detect a dimension mismatch, degrade to lexical-only, and *say so*
rather than silently returning noise.

**Migrations.** The app calls `create_all` at startup to honour the
one-command requirement. For a real deployment: `pip install alembic`,
`alembic init`, point `target_metadata` at `db.models.Base.metadata`, autogenerate
the baseline, and replace the `init_db()` call in `main.py`'s lifespan with
`alembic upgrade head`. The models are already fully declarative, so the
baseline autogenerates cleanly.

---

## 3. API

Every error response has the same shape, so the client never has to guess:

```json
{ "error": {
    "code": "provider_unavailable",
    "message": "Ollama is not reachable at http://localhost:11434.",
    "remediation": "Start Ollama (`ollama serve`) or switch provider.",
    "request_id": "8f2c1a9b4e07",
    "detail": { "provider": "ollama" }
} }
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness. Touches nothing. Docker's healthcheck. |
| GET | `/health/ready` | Readiness. Per-dependency status: `ok` / `degraded` / `down`. |
| POST | `/api/sessions` | Start a chat. Captures user agent and IP as metadata. |
| GET | `/api/sessions` | List, with message counts. `user_id`, `include_archived`, `limit`, `offset`. |
| GET | `/api/sessions/{id}` | Session with messages and artifact summaries. |
| PATCH | `/api/sessions/{id}` | Rename, archive. |
| DELETE | `/api/sessions/{id}` | Cascades to messages and artifacts. |
| GET | `/api/sessions/{id}/messages` | Messages only. |
| POST | `/api/chat` | One turn, blocking. Returns the full result object. |
| POST | `/api/chat/stream` | The same turn as SSE. |
| GET | `/api/artifacts` | List, filterable by session. |
| GET | `/api/artifacts/{id}` | Sanitised content plus the sanitiser report. |
| GET | `/api/artifacts/{id}/raw` | Unsanitised model output, for auditing. |
| GET | `/api/artifacts/{id}/download` | Attachment, with CSP and `nosniff`. |
| GET | `/api/artifacts/meta/policy` | What the viewer permits and blocks. |
| GET | `/api/knowledge/documents` | Corpus inventory, incl. `synthetic_present`. |
| POST | `/api/knowledge/ingest` | Load or refresh transcripts. Idempotent. |
| POST | `/api/knowledge/reconcile` | Remove stale persisted documents and rebuild from the configured transcript directory. |
| POST | `/api/knowledge/reindex` | Rebuild the in-process index from the DB. |
| GET | `/api/knowledge/search` | **Retrieval without generation.** Debugging seam. |
| GET | `/api/config` | Active provider, model, corpus stats, thresholds. |
| GET | `/api/config/providers` | Live reachability per provider. |
| PATCH | `/api/config` | Runtime model toggle. Empty body resets to `.env`. |

### 3.1 The SSE contract

`POST /api/chat/stream` emits named events. The blocking endpoint drains the
same generator, so the two can never disagree about what the agent did.

| Event | Payload | When |
|---|---|---|
| `status` | `stage`, plus stage-specific context | routing, retrieving, generating, critiquing, revising |
| `route` | `skill`, `reason`, `confidence`, `stage`, `artifact_kind` | after routing |
| `citations` | `citations[]`, `grounded`, `top_score`, `degraded`, `note` | **before generation starts** |
| `token` | `text` | repeatedly |
| `artifact` | `id`, `kind`, `title`, `content`, `sanitiser_report` | if one was produced |
| `done` | `message_id`, `skill`, `provider`, `model`, `latency_ms`, `grounded` | success |
| `error` | `message`, `kind`, `provider`, `remediation` | failure |
| `close` | `{}` | always, in a `finally` |

Citations are emitted *before* the first token on purpose. On a slow local
model the user sees which transcripts are being used within ~2 s and can start
judging the answer before it arrives. `close` is always sent, so the client's
read loop terminates even on an unexpected server error.

EventSource is not used: it cannot issue a POST, and a turn needs a JSON body.
The client parses frames by hand in `lib/api.js`.

---

## 4. Ingestion and retrieval

### 4.1 Ingestion flow

```
discover files ──► parse ──► hash ──► unchanged? ──► skip
                     │                    │
                     │                    ▼ changed or new
                     │              chunk on speaker turns
                     │                    │
                     │                    ▼
                     │              embed (batch)
                     │                    │
                     │                    ▼
                     └──────────►  upsert document + replace chunks
                                          │
                                          ▼
                                   rebuild the index
```

Formats: Markdown/plain text with optional front matter, `.vtt`, `.srt`,
`.json`. Speaker turns and timestamps are recovered from all of them.

**Chunking is on speaker-turn boundaries, not fixed windows.** A podcast answer
cut mid-sentence loses the argument it was making, and that is exactly the
material this product exists to surface. Whole turns are greedily packed to
~1,100 characters; a turn longer than that is split on sentence boundaries; the
trailing ~180 characters of each chunk are carried into the next so a claim
that straddles a boundary is still retrievable.

**Normal refresh is additive/update-only.** Documents are keyed by
`external_id` and compared by `content_hash`, so re-running ingestion skips
unchanged files and costs nothing. Records for files removed from disk are
retained by normal ingestion. The explicit reconciliation endpoint parses all
current files first, refuses to prune when parsing fails, removes persisted
documents absent from the configured directory, re-ingests current files, and
rebuilds the in-process index. `--force` re-embeds everything, which is what
you want after changing the embedding model.

The `/api/knowledge/documents` response derives counts from the persisted
database: `total_documents` counts `transcript_documents`, `total_chunks`
counts `transcript_chunks`, and `index_chunks` reports the currently loaded
in-process index.

**Traceability.** Every chunk carries its document, ordinal, speaker and
timestamp, and every citation shown to the user is built from that row — so a
claim in an answer traces to a passage, a speaker and a point in an episode.

### 4.2 Retrieval

```
query ──► embed ──► cosine over the index ─┐
     └──► tokenize ──► BM25 ───────────────┴──► 0.62·dense + 0.38·lexical
                                                      │
                                       sort, then per-episode cap (max 2)
                                                      │
                                       top score ≥ threshold ?
                                          │                  │
                                        yes                  no
                                          │                  │
                                    grounded answer    "not covered" path
```

**Why hybrid.** Dense retrieval catches paraphrase — "how do I know if people
want this" against a passage about retention curves. It reliably blurs proper
nouns and jargon: "PLG", "NPS", "Superhuman", "week eight". BM25 catches
exactly those. Neither alone is adequate for a corpus where the valuable
material is specific.

**Why a per-episode cap.** Without it a single well-matched episode fills all
six slots and the answer becomes one guest's opinion presented as consensus.
Capping at two chunks per document is a cheap approximation of MMR that costs
nothing and materially improves answer breadth.

**Why the threshold is per-embedder.** The hash fallback produces a flatter
score distribution than a real embedding model. A single threshold would either
admit everything on hash or reject everything on `nomic-embed-text`, so the
retriever picks `RETRIEVAL_MIN_SCORE_FALLBACK` when the index was built by the
fallback and `RETRIEVAL_MIN_SCORE` otherwise.

**BM25 normalisation.** Scores are divided by the maximum *achievable* score
for that query, not the observed maximum. Normalising by the observed peak —
the obvious implementation — makes the top result score 1.0 for every query
including nonsense ones, which destroys any threshold. This was a real bug
caught by the off-topic test; see `agent-transcripts/`.

### 4.3 Why not pgvector

At a few thousand chunks an in-process NumPy matrix answers in under a
millisecond, needs no Postgres extension, and works identically against local
Postgres, Supabase, Railway and SQLite-in-tests. pgvector would add an
extension dependency and an index-tuning surface for no measurable gain at this
size.

`VectorIndex` in `rag/retriever.py` is the swap point. Move when: the corpus
passes ~100k chunks, the API needs to scale horizontally (each process
currently holds its own copy), or the index rebuild at startup becomes slow
enough to matter. The change is one class plus an `ivfflat` index; nothing
above `rag/` moves.

### 4.4 Embedding model drift

If the index was built with one model and queries are embedded with another,
the vectors are incomparable. The retriever detects the dimension mismatch,
falls back to lexical-only scoring, sets `degraded: true`, and the UI tells the
user the ranking is weaker than usual. Fix: `python -m app.rag.ingest --force`.

---

## 5. Agent routing and skills

### 5.1 Two-stage routing

```
user message
     │
     ▼
stage 1: deterministic rules — keywords, verb shape, question shape
     │
     ├── confidence ≥ 0.8 ──────────────► decision
     │
     ▼ undecided
stage 2: single-word LLM classification  (only if ROUTER_MODE=rules+llm)
     │
     ├── valid label ───────────────────► decision
     │
     ▼ model unavailable or garbage
fall back to the stage-1 guess, else "grounded answer"
```

Stage 1 is free, instant, and unit-tested, and it covers the overwhelming
majority of real requests. Running an LLM classifier on *every* turn would add
latency and a new failure mode to a 3B local model for no benefit. Stage 2 is
for genuine ambiguity only.

Every decision carries its `reason`, `confidence` and `stage`. These are
logged, stored on the message, and shown in the UI — so a mis-route is a thing
you can see and fix, not a mystery. The user can also override the router
entirely with the mode chips in the composer; that path is tested.

Specificity wins ties: "write a Ship 30 essay and format it as a markdown doc"
routes to the essay skill, because the essay skill produces its own artifact.

### 5.2 The Ship 30 skill

Three parts, and the third is the important one:

1. **`PRINCIPLES`** — the writing rules as structured data. Quotable in the UI,
   diffable in review, editable without touching prompt strings.
2. **Prompt builders** — principles plus retrieved context plus a fixed output
   contract.
3. **`validate()`** — a deterministic checker returning an `EssayCritique`:
   word count, heading count, bullet count, bold spans, takeaway section,
   sources section, banned phrasing, a score, and a list of specific failures.

A failing draft produces a revision prompt that names the defect precisely —
*"the draft is 480 words; it needs about 1,250. Add roughly 770 words by
deepening existing sections with detail from the excerpts. Do not add new
sections and do not pad."* Local models respond to that; they do not respond to
being asked more nicely.

The revision is kept only if it scores at least as well as the draft, so the
second pass can never make the output worse. The critique is stored on the
message and shown in the UI.

### 5.3 Orchestration

`agent/orchestrator.run_turn()` is the single path. It yields typed events; the
SSE endpoint serialises them and the blocking endpoint drains them. Skills that
need a complete document before validating (Ship 30, artifacts) still emit
their output as `token` events in chunks, so the client renders every skill
identically.

**Follow-up handling.** A short follow-up ("and cycle time?") retrieves nothing
on its own. The orchestrator prepends the previous user turn — to the
*retrieval query only*, never to the prompt — which restores recall without
letting stale context contaminate the answer.

---

## 6. Security

### 6.1 Artifact isolation — three layers

| Layer | Where | Blocks | Load-bearing? |
|---|---|---|---|
| 1. Server sanitiser | `security/sanitizer.py` | `<script>` (unless allowed), `<iframe>`, `<object>`, `<embed>`, `<base>`, `<link>`, `<form>`, meta-refresh, `on*` handlers, `javascript:` and `data:text/html` URLs, disallowed tags and attributes | No |
| 2. CSP | `<meta http-equiv>` injected into the document | `default-src 'none'`, `connect-src 'none'`, `form-action 'none'`, `frame-src 'none'`, `base-uri 'none'` | No |
| 3. Sandboxed iframe | `ArtifactPane.jsx` | `srcdoc` with `sandbox` that **never** includes `allow-same-origin` | **Yes** |

Layer 3 is the one that contains an attacker. Because the frame has an opaque
origin, artifact script cannot read the app's DOM, cookies, `localStorage`, or
call the API — even with a perfect bypass of layers 1 and 2. DOMPurify also
runs client-side before the content reaches `srcdoc`, so a compromised backend
still cannot hand raw markup to the browser.

Layers 1 and 2 exist to catch *accidents* — a model pasting a tracking pixel or
a `fetch` — early and visibly. The Security tab shows the user exactly what was
removed, which sandbox is in force, and the CSP applied. Scripts, when present,
do not execute until the user explicitly opts in.

A script that references `document.cookie` or `localStorage` is dropped even
when scripts are allowed. It cannot reach anything useful from inside the
sandbox, but there is no legitimate reason for an artifact to contain it, so
its presence is treated as a signal rather than a nuisance.

Markdown artifacts are rendered from the AST. `rehype-raw` is deliberately not
installed, so HTML inside a Markdown artifact prints as text instead of
becoming markup.

### 6.2 Everything else

- **Secrets.** Only ever from the environment. `.gitignore` excludes `.env`;
  CI fails if one is ever tracked. Keys are never logged or returned by
  `/api/config`.
- **Input validation.** Pydantic on every request body; message length capped;
  artifact size capped at `ARTIFACT_MAX_BYTES`.
- **SQL.** SQLAlchemy Core throughout — no string-built queries.
- **CORS.** Explicit origin list. In the Docker deployment nginx proxies `/api`
  on the same origin, so CORS is not in the path at all.
- **Error messages.** Actionable but not leaky: no stack traces to the client;
  a `request_id` correlates the user's screen with the server log.
- **Auth.** Not implemented — see PRD §1.3 A1. The `user_id` column is
  populated and indexed, so adding it is a dependency plus query filters.
  `PATCH /api/config` is unauthenticated and process-global; that is acceptable
  for a single-tenant internal tool and must change before multi-tenancy.

---

## 7. Model toggle

```
         chat_provider()                    embedding_provider()
              │                                     │
    ┌─────────┴─────────┐                 ┌─────────┴────────┐
    │ runtime override  │                 │ EMBEDDING_       │
    │ (PATCH /api/config)                 │ PROVIDER         │
    │        ↓ else     │                 └─────────┬────────┘
    │ LLM_PROVIDER      │                           │
    └─────────┬─────────┘                 ollama / openai / hash
              │
   ollama / anthropic / openai
              │
     fails?  ─┴─► LLM_FALLBACK_PROVIDER (one retry)
```

**Embeddings are configured separately from chat, and that is not an
oversight.** Anthropic has no embeddings endpoint. If embeddings followed the
chat toggle, switching to Claude would silently break retrieval — or, worse,
re-embed the corpus with a different model and quietly degrade every future
answer. Keeping them independent means a chat-model switch never invalidates
the index.

**Fallback semantics.** Blocking calls retry once on the fallback provider.
Streaming falls back only *before the first token*; once tokens are flowing,
switching vendors mid-answer would produce incoherent text, so the error is
surfaced instead. Embeddings degrade to the in-process hash embedder, which
never fails and never leaves the process — retrieval keeps working and the UI
marks it degraded.

Adding a provider: implement `LLMProvider` in `llm/`, register it in
`_BUILDERS`. Nothing above `llm/` knows which vendor is answering.

---

## 8. Observability

**Structured logs.** JSON by default, `console` for demos. Every line carries
`component`, `request_id` and `session_id`.

```bash
docker compose logs -f api | grep '"component":"retrieval"'
docker compose logs -f api | grep '"level":"ERROR"'
```

**Per-request correlation.** A `x-request-id` header is accepted or generated,
attached to every log line for that request via a `ContextVar`, returned in the
response header, and shown in the UI when something fails — so a user can read
an id off the screen and an engineer can find the exact turn.

**`run_events`.** Route decisions, retrieval scores and timings, Ship 30
critiques, and failures are persisted, so a problem is diagnosable after the
container is gone.

```sql
SELECT created_at, component, event, status, duration_ms, detail
FROM run_events WHERE status = 'error' ORDER BY created_at DESC LIMIT 20;
```

**Diagnosing the four failure classes the brief names:**

| Failure | Where to look |
|---|---|
| Model | `/health/ready` → `checks.llm.providers[]`; logs `component=llm` |
| Retrieval | `/api/knowledge/search?q=...` — retrieval with no model in the path |
| Database | `/health/ready` → `checks.database`; logs `component=db` |
| Artifact rendering | the artifact's Security tab, or `/api/artifacts/{id}/raw` |

---

## 9. Resilience

| Condition | Behaviour |
|---|---|
| Ollama not running | Retrieval still runs and citations still render. The error names the URL and the command to fix it. |
| Model not pulled | 404 is translated to `ollama pull <model>`. |
| Model timeout | Distinct `timeout` kind; remediation suggests a smaller model or a higher `LLM_TIMEOUT_SECONDS`. |
| Missing API key | Provider reports unavailable at `/health/ready` and is disabled in the model menu; it never fails mid-turn. |
| Rate limited | Distinct kind; falls back if one is configured. |
| Empty retrieval | Different system prompt: decline, and suggest what the corpus covers. |
| Embedding backend down | Degrade to the hash embedder; mark the answer degraded in the UI. |
| Embedding dimension mismatch | Lexical-only scoring; marked degraded; remediation is a `--force` reingest. |
| Database down at boot | Startup is logged as degraded rather than crashing, so `/health/ready` can report the cause. |
| Database down mid-request | Session rolls back; structured 500 with a request id. |
| One corrupt transcript | Logged, counted in the ingest report, skipped. The run continues. |
| Client disconnects mid-stream | Generator's `finally` closes the DB scope; the turn is persisted up to that point. |

---

## 10. Deployment topology

### 10.1 Local demo (what the brief asks for)

```
  host ──► Ollama :11434  (models on a non-system drive)
    │
  docker compose
    ├── web  :5173   nginx: serves the SPA, proxies /api to api:8000
    ├── api  :8000   uvicorn, reaches Ollama via host.docker.internal
    └── db   :5432   postgres:16-alpine, named volume
```

Ollama runs on the host, not in a container. On an 8 GB laptop a containerised
Ollama competes with Docker's VM for memory, and model files land on the Docker
disk — usually the system drive, which is where space is tightest.

### 10.2 Hosted

```
  Vercel / Netlify  ── static SPA, VITE_API_BASE=https://api.example.com
          │ https
  Railway / Render  ── FastAPI container, LLM_PROVIDER=anthropic
          │
  Supabase          ── Postgres (Session pooler URI)
```

Notes:

- A hosted box has no Ollama. Set `LLM_PROVIDER=anthropic` (or `openai`) and
  `EMBEDDING_PROVIDER=openai`; otherwise embeddings silently fall back to the
  hash embedder and retrieval quality drops.
- Use Supabase's **Session pooler** URI. The transaction pooler is pgbouncer,
  where asyncpg's prepared-statement cache breaks; `db/session.py` already
  disables that cache, but the session pooler is the safer default.
- Set `CORS_ORIGINS` to the frontend origin. If the API is behind the same
  domain, CORS is not in the path at all.
- Ingestion must run once after deploy: `python -m app.rag.ingest`, or
  `POST /api/knowledge/ingest`. Cold-start ingestion also runs automatically on
  first boot when the index is empty.
- Set `LOG_FORMAT=json` and ship logs to the platform's aggregator.

### 10.3 Scaling notes

The in-process index is per-process, so running two API replicas means two
copies in memory and a `reindex` call that only reaches one of them. Before
scaling out: move to pgvector (§4.3), or put the index behind a shared service.
Until then, one replica is the correct topology, and it is more than enough for
an internal tool.
