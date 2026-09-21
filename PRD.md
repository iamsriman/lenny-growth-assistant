# PRD — The Lenny Growth Assistant

**Status:** v1.0, built during a one-week forward-deployment engagement
**Owner:** Forward Deployed Engineer
**Audience:** the client's product and growth team, and the engineer who will
inherit this system

---

## 1. Forward deployment brief

### 1.1 The user and the job

**Primary user: the product or growth lead at a 20–200 person company.** They
are two to six people, they ship weekly, and they do not have a research
function.

The job is not "search a podcast." The job is: *"I have to make a call this
week — pricing model, activation metric, whether to add sales — and I want the
reasoning of people who have already made that call, without spending an
evening scrubbing episodes."*

The pain today has three parts, and only the first is obvious:

1. **The knowledge is trapped in audio.** Lenny's Podcast is one of the densest
   sources of operator judgment available, and it is unsearchable at the level
   that matters. You can find the episode; you cannot find the six minutes
   where the guest explains why seat-based pricing broke their business.
2. **The output is always a second task.** Finding the answer is half the work.
   The lead then has to turn it into something a team can act on — a memo, a
   post, a one-pager for the exec review. Today that means a second tool, a
   blank document, and an hour.
3. **A general chatbot is worse than nothing here.** Asked about pricing
   strategy, a general model produces confident, fluent, average advice with no
   provenance. The lead cannot tell the difference between "an operator said
   this on the record" and "the model generalised from a marketing blog," and
   in a decision meeting that distinction is the entire value.

The assistant removes all three: it searches inside the transcripts, it shows
which passage every claim came from, and it hands back the essay or the
one-pager as a finished artifact.

**Secondary user: the platform engineer** who inherits this after the
engagement ends. Their job is to swap the model, load a new corpus, and
diagnose a bad answer without reading the whole codebase. That user shaped as
much of the architecture as the primary one — see §5.

### 1.2 Success metrics

**Primary (product): grounded-answer rate ≥ 85%.**
The share of answers that (a) cite at least one transcript passage above the
grounding threshold and (b) survive a spot-check that the cited passage
actually supports the claim. Measured from the `messages.grounded` column and
the `run_events` retrieval scores, spot-checked weekly on a sample of 20.

This is the right primary metric because it is the thing that differentiates
this product from the free alternative. If it drops below 85%, the assistant
is a chatbot with a podcast theme and the user should stop trusting it.

**Secondary (product): artifact reuse rate ≥ 40%.**
The share of generated artifacts that are copied or downloaded. Measured from
client events on the copy/save controls. This tests hypothesis 2 above: if
people read the essays but never take them, the generation half of the product
is theatre and should be cut.

**Operational: p95 time-to-first-token < 8 s on the reference laptop**
(AMD Ryzen 5 5500U, 8 GB, `llama3.2:3b`). Measured from `run_events`. Local
models are slow; the streaming architecture exists so the user sees routing and
citations within ~2 s even when the full answer takes 40. If p95 TTFT goes
above 8 s the product feels broken regardless of answer quality.

**Counter-metric: refusal rate.** The share of turns answered with "the
transcripts don't cover this." It should sit between 5% and 20%. Near 0% means
the grounding threshold is too loose and the model is padding with general
knowledge. Above 25% means retrieval is broken or the corpus is too small, and
users will stop coming back.

### 1.3 Assumptions

The brief was deliberately incomplete. These are the calls I made, and what
would change if a call is wrong:

| # | Assumption | Why | If wrong |
|---|---|---|---|
| A1 | Internal tool, trusted network, no auth needed for v1 | The engagement scope is an internal assistant for one team; auth would consume build time that grounding quality needs more | Add an auth dependency on the router and a `user_id` filter on sessions — the column already exists and is populated |
| A2 | Corpus is hundreds, not hundreds of thousands, of transcripts | Lenny's catalogue is in that range | The in-process NumPy index stops fitting in memory; swap `VectorIndex` for pgvector (§5.3) |
| A3 | The evaluator runs this on a laptop, not a GPU box | The brief mandates a local Ollama demo | Model defaults and `num_ctx` would rise; nothing structural changes |
| A4 | Transcripts are text with speaker turns, not diarised audio | Standard transcript repo format | The parser already handles VTT/SRT/JSON as well |
| A5 | "Ship 30 for 30 style" means the public guide's principles: atomic idea, strong hook, skimmable structure, proof over assertion, a concrete takeaway | The guide is linked but its rules are not enumerated in the brief | The principles are structured data in `skills/ship30.py` — editing them is a data change, not a code change |
| A6 | Citations must be visible but not intrusive | Growth leads skim; a wall of footnotes defeats the purpose | Inline `[S1]` markers plus a collapsed source list was the compromise |
| A7 | One user at a time per deployment | It is a local demo | The runtime model toggle is process-global and would need to become per-session |
| A8 | I may not redistribute the real transcript corpus | It is someone else's content and the repo is public | Shipped labelled synthetic samples plus a fetch script (§3.3) |

### 1.4 Scope

**In scope**

- Multi-session chat with independent context, persisted in Postgres
- Hybrid retrieval with visible citations and an explicit "not covered" path
- Three skills: grounded answer, Ship 30 essay, artifact generation
- Artifact viewer with real isolation, a source view, and a security report
- Runtime model toggle across Ollama / Anthropic / OpenAI with fallback
- One-command Docker startup, health and readiness endpoints, structured logs
- 55 automated tests plus a manual UI plan

**Deliberately excluded, with reasons**

| Excluded | Why | Cost of adding later |
|---|---|---|
| Authentication and multi-tenancy | A1. The schema carries `user_id` and `client_ip` already | Low — one dependency plus query filters |
| Alembic migrations | `create_all` keeps startup to one command, which the brief asks for explicitly | Low — the models are already declarative |
| pgvector | A2. Adds a Postgres extension that breaks the plain-Postgres and some managed-Postgres paths, for no gain at this corpus size | Medium — `VectorIndex` is the only class that changes |
| A reranker model | Doubles latency on an 8 GB laptop for a modest precision gain. The per-episode diversity cap recovers most of the benefit for free | Medium |
| Streaming the Ship 30 essay token-by-token | The validator needs the whole draft before it can critique it. The UI streams the finished text in chunks so the experience is identical | n/a |
| Artifact editing and versioning | The `version` column exists; inline editing is a week of UI work and was not asked for | Medium |
| Evaluation harness (golden Q&A set) | Highest-value next thing, but needs the real corpus to be meaningful | Medium — `/api/knowledge/search` is already the right seam |
| Speaker diarisation, audio ingestion | Out of scope; transcripts are the input | High |

### 1.5 Risks and trade-offs

**Hallucination — the risk that matters most.** A fluent, wrong, confident
answer with a plausible citation is worse than no product, because it is
trusted. Four mitigations, deliberately layered:

1. Retrieval returns a *score*, and below `RETRIEVAL_MIN_SCORE` the turn is
   routed to a different system prompt that instructs the model to decline and
   suggest what the corpus *does* cover.
2. The context block uses stable `[S1..Sn]` labels and the system prompt bans
   claims not traceable to one. Inline markers make an uncited paragraph
   visually obvious.
3. Every citation is a real database row with the verbatim passage, shown in
   the UI. The user can check the model in one click — that is the actual
   safeguard, not the prompt.
4. The threshold is calibrated per embedding backend, because the fallback
   embedder produces a flatter score distribution. One shared number would
   either let everything through or reject everything.

*Residual risk:* a small local model can still misread a passage it correctly
retrieved. The citation UI makes that discoverable; it does not prevent it.
This is the argument for the evaluation harness being the next investment.

**Local model quality.** `llama3.2:3b` is not Claude. It under-writes long
essays badly, sometimes ignores output contracts, and occasionally loses the
citation format. Mitigation: the Ship 30 skill *checks the output in code* and
issues a specific revision instruction ("you wrote 480 words, add ~770 by
deepening these sections, do not add new sections"). Deterministic validation
is what makes a 3B model usable for a 1,250-word deliverable. Trade-off: the
revision pass roughly doubles essay latency. Worth it — an essay at 40% of
target length is not a deliverable at any latency.

**Latency and cost.** Local inference on 8 GB is slow and the machine will
swap if the model is too large. Mitigations: `num_ctx` pinned to 4096, SSE so
routing and citations appear within ~2 s, a stop control, and documented
guidance to drop to `llama3.2:1b`. Cloud providers cost money but no data
leaves the machine in the default configuration — that is the point of making
Ollama the default rather than the fallback.

**Unsafe artifact rendering.** Model-generated HTML is untrusted input, and a
naive `dangerouslySetInnerHTML` here is a straightforward XSS. Three layers,
described fully in `architecture.md` §6. The load-bearing one is the
cross-origin sandboxed iframe: no `allow-same-origin`, so artifact script
cannot touch the app's origin, cookies or storage even if both sanitisers were
bypassed. The other two layers catch accidents early and make them *visible* in
the Security tab rather than silent. Trade-off: some legitimate HTML gets
stripped. Accepted, and mitigated by showing the user exactly what was removed.

**Data leakage.** With `LLM_PROVIDER=ollama` nothing leaves the machine. With a
cloud provider, transcript excerpts and the user's questions go to that vendor.
The active provider is visible in the UI at all times and recorded per message,
so this is never accidental. `.gitignore` excludes `.env` and CI fails if one
is ever committed.

**Corpus provenance.** Shipping invented transcripts that look real would be
the worst failure mode in a grounding product. The samples are labelled
`synthetic: true` in three places — the file, the API response, and every
citation chip in the UI — and the sidebar warns while they are loaded.

---

## 2. User flows

### 2.1 Ask a grounded question

1. User opens the app; a session exists or is created automatically.
2. They type a question and press Enter.
3. Within ~1 s: the routing decision appears. Within ~2 s: the retrieved
   passages appear, before any text is generated.
4. The answer streams in with `[S1]` markers.
5. The source list expands to show the passage, guest, timestamp and score.
6. A follow-up ("and cycle time?") reuses the session's context; because a
   three-word follow-up retrieves nothing on its own, the previous user turn is
   prepended to the *retrieval query only*, not to the answer.

### 2.2 Generate a Ship 30 essay

1. User asks for an essay, or picks the "Ship 30 essay" mode chip.
2. The router selects the skill and shows why.
3. Retrieval widens to 10 passages — an essay needs more material than an answer.
4. Draft → validate → revise if needed. The status line names what is being
   fixed, so a 60-second wait is legible rather than a spinner.
5. The essay is saved as a Markdown artifact and opens in the viewer with its
   critique score shown.

### 2.3 Generate and inspect an artifact

1. User asks for an HTML one-pager.
2. The model produces HTML; the sanitiser strips what the policy forbids and
   records it.
3. The viewer opens beside the chat. Scripts, if present, do not run until the
   user opts in.
4. The Security tab lists exactly what was removed, the sandbox in force, and
   the CSP applied.
5. Copy, or Save to download the sanitised document.

### 2.4 Switch models mid-conversation

1. User opens the provider menu; it shows live reachability per provider.
2. They pick another provider; the next message uses it.
3. Each message records the provider and model that produced it, so a session
   that spans a switch stays auditable.

---

## 3. Acceptance criteria

### 3.1 Conversation and grounding

- [x] A new chat can be started; each session keeps independent context
- [x] Sessions, messages, timestamps, provider, model, latency and user
      metadata persist in Postgres and survive a restart
- [x] Answers cite the transcripts used; citations expand to the verbatim passage
- [x] Follow-up questions resolve against the session's history
- [x] When nothing clears the threshold, the assistant says so and suggests what
      the corpus does cover, rather than answering from general knowledge
- [x] Deleting a session cascades to its messages and artifacts

### 3.2 Ship 30 skill

- [x] Principles are structured data, not an inline prompt string
- [x] Output is validated in code: word count within ±18% of 1,250, 4–6 H2
      sections, ≥3 bullet items, bold present but not excessive, a takeaway
      section, a sources section, no banned phrasing
- [x] A failing draft triggers one targeted revision naming the specific defect
- [x] A revision is only kept if it scores at least as well as the draft
- [x] The essay is stored as a retrievable artifact

### 3.3 Artifacts

- [x] Markdown and complete HTML/CSS both render in-app, beside the chat
- [x] Generated HTML is sanitised server-side and client-side and rendered in a
      cross-origin sandboxed iframe with no `allow-same-origin`
- [x] The viewer states what it permits, what it blocked, and why
- [x] The unsanitised model output is retained for auditing at `/raw`
- [x] Artifacts can be copied and downloaded

### 3.4 Operability

- [x] `docker compose up --build` starts the whole stack
- [x] `.env.example` documents every variable; no secret is committed
- [x] `/health` is a pure liveness check; `/health/ready` reports each
      dependency separately
- [x] Missing API keys, unavailable Ollama, an unpulled model, model timeouts,
      empty retrieval and a down database each produce a specific, actionable
      message rather than a stack trace
- [x] Structured logs with a per-request id, echoed in the response header and
      shown in the UI on failure
- [x] 55 automated tests, hermetic; CI runs lint, tests, build, and a
      committed-secret check

---

## 4. Implementation plan

Shipped in this order, deliberately — each stage was demonstrable before the
next began.

| Stage | Scope | Rationale |
|---|---|---|
| 1 | Config, DB models, health endpoints | Everything else needs somewhere to land and something to report |
| 2 | Provider abstraction + Ollama + registry | The model toggle is structural; retrofitting it is a rewrite |
| 3 | Chunker, ingest, hybrid retriever | Grounding is the product; it was built and tested before any chat existed |
| 4 | Sessions, chat, SSE orchestrator | Streaming was designed in from the start because local latency demands it |
| 5 | Router + three skills | Skill boundaries stay clean because the orchestrator was already the single path |
| 6 | Sanitiser + artifact endpoints | Security before UI, so the UI could not accidentally depend on unsafe behaviour |
| 7 | Frontend | Built against a real, already-tested API |
| 8 | Docker, docs, CI, tests | Handoff is a deliverable, not a postscript |

### Next three things, in priority order

1. **Evaluation harness.** A golden set of ~50 question/passage pairs and a CI
   job that fails when grounded-answer rate regresses. Everything else is
   guesswork without it.
2. **Authentication and per-user sessions.** The schema is ready; this is what
   stands between the demo and a team actually using it.
3. **Retrieval quality pass.** A cross-encoder reranker behind a feature flag,
   plus query rewriting for pronoun-heavy follow-ups, measured against (1).

---

## 5. Notes for the inheriting engineer

- The seams that matter are `llm/registry.py` (vendor), `rag/retriever.py`
  (`VectorIndex`), and `agent/skills/` (behaviour). Everything else is plumbing.
- `run_events` is the first place to look when an answer is wrong — it records
  the route decision, the retrieval scores, and the Ship 30 critique for every
  turn.
- `/api/knowledge/search` runs retrieval without generation. It is the fastest
  way to tell a retrieval problem from a model problem, and it is the right
  seam for the evaluation harness.
- The grounding threshold is the product's main tuning dial. Raising it makes
  the assistant more cautious and more trustworthy; lowering it makes it more
  useful and more risky. Move it with the counter-metric in §1.2 in view, not
  on the basis of one bad answer.
