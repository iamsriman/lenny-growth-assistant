# The Lenny Growth Assistant

A grounded product-and-growth assistant over Lenny's Podcast transcripts. It
answers questions with transcript citations, turns those answers into Ship 30
for 30 essays, and renders Markdown or HTML artifacts beside the chat.

Runs locally via Ollama, with Anthropic, OpenAI, and Groq available as optional
cloud providers. Cloud providers are a toggle, not a requirement.

---

## What it does

| | |
|---|---|
| **Grounded answers** | Hybrid retrieval over transcript chunks. Every claim carries an `[S1]`-style citation you can expand to see the passage, the guest and the timestamp. When nothing clears the grounding threshold the assistant says so instead of inventing an answer. |
| **Ship 30 for 30 essays** | A skill, not a prompt: the writing principles are structured data, and a deterministic validator checks word count, headings, bullets, bold density, the takeaway and the sources list, then drives one targeted revision pass. |
| **Artifacts** | Markdown documents and self-contained HTML/CSS render in a viewer next to the chat. Generated HTML is treated as hostile: sanitised server-side, sanitised again client-side, then rendered in a cross-origin sandboxed iframe. |
| **Model toggle** | Switch between Ollama, Anthropic, OpenAI, and Groq from the UI or `PATCH /api/config`, with no restart and no code change. |
| **Sessions** | Independent context per chat, persisted in Postgres with timestamps, provider, model, latency and user metadata. |

---

## Architecture

```
                    ┌──────────────────────────────────────────┐
  Browser  ────────▶│ React + Vite  (nginx in prod)            │
                    │  chat · sessions rail · artifact viewer  │
                    └───────────────┬──────────────────────────┘
                                    │ REST + Server-Sent Events
                    ┌───────────────▼──────────────────────────┐
                    │ FastAPI                                  │
                    │                                          │
                    │  api/routes   contracts, validation,     │
                    │               structured errors          │
                    │  agent/       router → skill → stream    │
                    │  rag/         chunk · embed · retrieve   │
                    │  llm/         provider registry (toggle) │
                    │  security/    artifact sanitiser         │
                    └───┬──────────────┬───────────────────┬───┘
                        │              │                   │
              ┌─────────▼────┐  ┌──────▼───────┐   ┌───────▼────────┐
              │ PostgreSQL   │  │ Ollama       │   │ Anthropic /    │
              │ sessions     │  │ (host, local)│   │ OpenAI         │
              │ messages     │  │ chat + embed │   │ (optional)     │
              │ artifacts    │  └──────────────┘   └────────────────┘
              │ chunks       │
              │ run_events   │
              └──────────────┘
```

A turn flows: **route** (rules, LLM tie-break only when undecided) → **retrieve**
(BM25 + dense cosine, per-episode diversity cap, grounding threshold) →
**generate** (skill-specific system prompt over the retrieved context) →
**validate/sanitise** → **persist** → stream.

Full detail, including the schema and every endpoint, is in
[`architecture.md`](architecture.md). Product reasoning is in
[`PRD.md`](PRD.md); interface decisions are in [`design.md`](design.md).

---

## Prerequisites

- **Docker Desktop** (or Python 3.11+ and Node 20+ for the native path)
- **[Ollama](https://ollama.com/download)** running on the host
- ~3 GB of disk for the two models
- 8 GB RAM is enough with `llama3.2:3b`

---

## Quick start

```bash
git clone <your-repo-url>
cd lenny-growth-assistant
cp .env.example .env        # Windows: copy .env.example .env
```

Pull the models (Ollama must be installed and running):

```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Start everything:

```bash
docker compose up --build
```

- Web UI — <http://localhost:5173>
- API docs — <http://localhost:8000/docs>
- Readiness — <http://localhost:8000/health/ready>

On first boot the API creates its schema and ingests `data/transcripts/` only
when the persistent knowledge base is empty. Transcript files are mounted into
the API container at `/app/data/transcripts`; documents and chunks persist in
PostgreSQL.

### Windows with a nearly-full C: drive

Docker Desktop and Ollama both default to the system drive. Point Ollama's
model store elsewhere **before** pulling anything:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1 -ModelDrive D
```

That script sets `OLLAMA_MODELS=D:\ollama\models`, restarts Ollama, pulls both
models, creates `.env`, and warns about busy ports. To move Docker's own disk
too: Docker Desktop → Settings → Resources → Advanced → *Disk image location*.

If C: is still too tight for Docker, use the **native path** below with a free
[Supabase](https://supabase.com) database — that needs no local Postgres and no
Docker at all.

---

## Native path (no Docker)

```bash
# 1. Database — either a local Postgres, or a free Supabase project.
#    Put the URL in .env as DATABASE_URL. Supabase URLs paste in unchanged.

# 2. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
# In .env set OLLAMA_BASE_URL=http://localhost:11434 (not host.docker.internal)
uvicorn app.main:app --reload --port 8000

# 3. Frontend, in a second terminal
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies /api to :8000
```

---

## Environment variables

Every variable lives in [`.env.example`](.env.example) with inline notes. The
ones that matter:

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | yes | local compose Postgres | `postgres://`, `postgresql://` and Supabase/Railway URLs are all accepted and rewritten to asyncpg automatically |
| `LLM_PROVIDER` | yes | `ollama` | `ollama` \| `anthropic` \| `openai` \| `groq` |
| `OLLAMA_BASE_URL` | yes for local | `http://host.docker.internal:11434` | use `http://localhost:11434` outside Docker |
| `OLLAMA_MODEL` | yes for local | `llama3.2:3b` | `llama3.2:1b` if memory is tight |
| `EMBEDDING_PROVIDER` | yes | `ollama` | separate from chat — Anthropic has no embeddings API |
| `ANTHROPIC_API_KEY` | no | empty | only needed to use Claude |
| `OPENAI_API_KEY` | no | empty | only needed to use GPT |
| `GROQ_API_KEY` | no | empty | only needed to use Groq |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` | active Groq chat model |
| `LLM_FALLBACK_PROVIDER` | no | empty | one retry on this provider if the active one fails |
| `RETRIEVAL_MIN_SCORE` | no | `0.30` | below this the assistant declines to answer |
| `ALLOW_ARTIFACT_SCRIPTS` | no | `true` | scripts still run only inside the cross-origin sandbox |

No secret is ever committed: `.gitignore` excludes `.env`, and CI fails the
build if a `.env` file is ever tracked.

---

## Loading and reconciling transcripts

The API reads supported transcript files from `data/transcripts/` (mounted as
`/app/data/transcripts` in Docker). Markdown, plain text, VTT, SRT, and JSON
files are discovered recursively.

```bash
# ingest current files and rebuild the in-process index
docker compose exec api python -m app.rag.ingest --path /app/data/transcripts
# native: cd backend && python -m app.rag.ingest --path ../data/transcripts
```

Normal ingestion is additive/update-only: unchanged documents are skipped and
records for files removed from disk are retained. To make the persisted corpus
exactly match the currently mounted directory, create a database backup first,
then call the explicit reconciliation endpoint:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/knowledge/reconcile |
  ConvertTo-Json -Depth 8
```

The response reports `scanned`, `ingested`, `chunks`, `pruned`, and `failed`.
Reconciliation parses current files before pruning and refuses to prune when a
current file fails to parse.

Check the persisted and in-memory counts with:

```powershell
Invoke-RestMethod http://localhost:8000/api/knowledge/documents |
  Select-Object total_documents,total_chunks,index_chunks,embedding_model
```

---

## Switching models

**From the UI** — the provider button at the bottom of the sessions rail. It
shows live availability (green = reachable and the model is pulled) and
switches on the next message.

**From the API**

```bash
curl -X PATCH localhost:8000/api/config -H 'content-type: application/json' \
  -d '{"provider":"anthropic"}'

curl -X PATCH localhost:8000/api/config -H 'content-type: application/json' \
  -d '{"provider":"groq"}'

curl -X PATCH localhost:8000/api/config -d '{}' -H 'content-type: application/json'  # reset to .env
```

**Fallback behaviour.** If `LLM_FALLBACK_PROVIDER` is set and configured, a
failed request is retried once on it. Streaming only falls back *before* the
first token — switching vendors mid-answer would produce incoherent text, so
after that the error is surfaced instead. Embeddings never follow the chat
toggle; if the embedding backend is unreachable the app degrades to a
deterministic in-process embedder, marks the answer as degraded in the UI, and
keeps working.

---

## Tests

```bash
cd backend
python -m pytest        # 55 tests
ruff check .
```

The suite is hermetic — SQLite in memory, a stub model provider, the
deterministic embedder. No network, no Ollama, no API keys. It covers the API
contracts and error shapes, session isolation and cascade deletes, chunking and
front-matter parsing, ingestion idempotency, hybrid retrieval including the
"corpus doesn't cover this" path, skill routing, the model toggle, SSE event
ordering, artifact sanitisation against a realistic XSS payload, and the
provider-down path.

A manual UI test plan is in [`docs/manual-test-plan.md`](docs/manual-test-plan.md).

---

## Observability

Structured JSON logs, one `component` per subsystem — `api`, `agent`,
`retrieval`, `llm`, `db`, `artifact`, `ingest`. Every request gets an
`x-request-id` that is echoed in the response header, attached to every log
line for that request, and shown in the UI on failure.

```bash
docker compose logs -f api | grep '"component":"retrieval"'
```

Agent legs are also written to the `run_events` table (route decisions,
retrieval scores, Ship 30 critiques, failures), so a problem is diagnosable
after the container is gone:

```sql
SELECT created_at, component, event, status, duration_ms, detail
FROM run_events ORDER BY created_at DESC LIMIT 40;
```

`GET /health/ready` reports each dependency separately, because the app stays
useful with a cold index or an unreachable cloud provider.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| *"Ollama is not reachable"* | Ollama isn't running, or the container is pointed at `localhost` | `ollama serve`; in Docker set `OLLAMA_BASE_URL=http://host.docker.internal:11434` |
| *"Model 'x' is not pulled"* | model missing from the Ollama store | `ollama pull llama3.2:3b` |
| Answers are slow, machine swaps | 3B model on 8 GB with other apps open | switch to `llama3.2:1b`, close browsers, or raise `LLM_TIMEOUT_SECONDS` |
| *"Knowledge base empty"* banner | no transcripts ingested | `docker compose exec api python -m app.rag.ingest` |
| Everything says "not supported by the corpus" | index built by a different embedder than the one now configured | check `embedding_model` at `/health/ready`, then `python -m app.rag.ingest --force` |
| Ranking marked "degraded" | embedding backend unreachable, running on the hash fallback | start Ollama and `--force` reingest |
| `connection refused` on the database | Postgres still starting, or a wrong `DATABASE_URL` | `docker compose logs db`; for Supabase use the **Session pooler** URI |
| Supabase: *prepared statement already exists* | pgbouncer + asyncpg statement cache | already handled in `db/session.py`; make sure you used the pooler URI, not a hand-edited one |
| Artifact renders blank | the sanitiser removed the whole body | open the artifact's **Security** tab — it lists exactly what was stripped and why |
| Port already in use | something else on 8000/5173/5432 | change `API_PORT` / `WEB_PORT` / `POSTGRES_PORT` in `.env` |
| SSE arrives all at once | a proxy is buffering | nginx config already sets `proxy_buffering off`; check any proxy in front of it |

---

## Extending it

- **A new skill** — add a module under `backend/app/agent/skills/`, add
  patterns to `agent/router.py`, add a branch in `agent/orchestrator.py`. The
  router returns its reasoning, so a mis-route is visible rather than mysterious.
- **A new model provider** — implement `LLMProvider` in `backend/app/llm/`, add
  it to `_BUILDERS` in `llm/registry.py`. Nothing above that module knows which
  vendor is answering.
- **A different vector store** — `rag/retriever.py` isolates the index behind
  `VectorIndex`. Swapping in pgvector or a dedicated store means replacing that
  class only; see `architecture.md` for when that becomes necessary.
- **Migrations** — the app currently uses `create_all` to keep startup to one
  command. `architecture.md` has the Alembic path for a real deployment.

---

## Deploying

The demo is local by design. For a hosted build, see the *Deployment topology*
section of [`architecture.md`](architecture.md): Postgres on Supabase, API on
Railway or Render, static frontend on Vercel or Netlify with `VITE_API_BASE`
set to the API origin, and `LLM_PROVIDER=anthropic` because a hosted box has no
Ollama.

---

## Repository layout

```
backend/app/
  api/routes/   health, sessions, chat (+SSE), artifacts, knowledge, config
  agent/        router, orchestrator, skills/{qa,ship30,artifact}
  rag/          chunker, ingest, retriever
  llm/          base, ollama, anthropic, openai, groq, registry
  security/     sanitizer
  db/           models, session
backend/tests/  55 hermetic tests
frontend/src/   App, components/, lib/, styles/
data/           transcripts (labelled samples included)
agent-transcripts/  coding-agent logs, including the failures and the fixes
docs/           manual test plan
```
