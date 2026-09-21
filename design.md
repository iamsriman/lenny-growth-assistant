# Design

## 1. What this interface is for

A product lead opens this between meetings with a decision to make. They are
not browsing. They want an answer they can trust and, often, something they can
paste into a doc within five minutes.

Two consequences shaped every decision below:

1. **Provenance is the product.** A fluent answer with no visible source is
   indistinguishable from a general chatbot, which the user already has for
   free. The interface must make "where did this come from" a one-second
   question, not a research task.
2. **The output is a document.** This tool produces essays and briefs. It
   should feel like a reading and writing surface, not a messaging app.

## 2. Principles

**Show the work before the answer.** Routing and retrieved passages appear
*before* the first token. On a local 3B model the full answer can take forty
seconds; within two the user already knows which transcripts are in play and
can start forming a judgement. A spinner would waste those thirty-eight
seconds.

**Colour means exactly one thing: provenance.** Moss = grounded in a
transcript. Amber = degraded or unsupported. Rust = failed. Nothing else in the
interface is coloured, so the code is learnable in one session and a scan of
the thread tells you which answers to trust before reading a word.

**Legibility over density.** Assistant output is set in a serif at 17px with a
64-character measure, because it is prose meant to be read, not a chat bubble
to be skimmed. Chrome is a quiet sans at 11–14px and gets out of the way.

**Failure states are instructions.** "Ollama is not reachable at
localhost:11434. Start it with `ollama serve`." — what happened, then what to
do, then the request id. Never "Something went wrong."

**No decoration.** Every border, chip and divider encodes something: a
provenance state, a skill, a provider, a latency. Nothing is there to fill
space.

## 3. Visual language

### Typography

| Role | Face | Why |
|---|---|---|
| Assistant answers, essays, Markdown artifacts | **Newsreader**, 17px/1.68 | A reading serif with a text optical size. The product's output is essays; setting them in the same UI sans as the buttons makes a 1,250-word essay feel like a system message. |
| All chrome: rails, chips, labels, composer, tables | **Inter**, 11–15px | Neutral, dense, unmistakably interface. The contrast with the serif is the signal that you have crossed from tool into content. |
| Source view, request ids, CSP | system monospace | Content that is code should look like code. |

Two families, clearly distinct — not a display face and a body face from the
same superfamily, which would blur exactly the boundary that matters here.

### Colour

| Token | Light | Dark | Job |
|---|---|---|---|
| `--paper` | `#f4f5f2` | `#12171d` | App background |
| `--panel` | `#ffffff` | `#181e26` | Rails, cards, composer |
| `--ink` | `#16212e` | `#e8ebe6` | Body text |
| `--navy` | `#1d3f5e` | `#8fb4d6` | The one action colour: primary buttons, active tab, focus ring |
| `--moss` | `#4f6b46` | `#a3c294` | Grounded in transcripts |
| `--amber` | `#8a6415` | `#d8b169` | Degraded retrieval, unsupported question, synthetic corpus |
| `--rust` | `#8f3a2b` | `#e0917f` | Failure |

A muted, slightly cool palette on near-white paper. The point is that the three
state colours are the only saturated things on screen, so they carry real
signal. Dark mode follows the system and is redefined token-by-token rather
than inverted.

## 4. Information architecture

```
┌──────────┬────────────────────────────┬──────────────────────┐
│ sessions │ chat                       │ artifact viewer      │
│          │                            │ (only when there is  │
│ new chat │ ── title · state chips ──  │  something to show)  │
│          │                            │                      │
│ recent   │  trace line                │ preview │ source │   │
│ chats    │  answer (serif)            │ security             │
│          │  ▸ 6 transcript passages   │                      │
│          │                            │ sandboxed iframe or  │
│ corpus   │  ──────────────────────    │ rendered markdown    │
│ status   │  mode chips                │                      │
│ provider │  composer                  │                      │
└──────────┴────────────────────────────┴──────────────────────┘
   248px          flexible                   equal split
```

Three columns, one job each: **what I asked before**, **the conversation**,
**the thing I am making**. The artifact pane has no permanent slot — it appears
when an artifact exists and closes without disturbing the layout, because most
turns do not produce one and a permanently empty third of the screen is a
permanent reminder of an unused feature.

The provider control sits at the *bottom* of the sessions rail, next to the
corpus status. Both answer the same question — "what is producing these
answers" — so they belong together, and neither belongs in the path of the
primary task.

## 5. Interaction states

### Empty state

A sentence stating the product's actual claim (*"Ask the podcast archive, not
the internet"*), one line of explanation, and four real prompts — one per
capability, each labelled with what it demonstrates. An empty screen is an
invitation to act, not a logo.

### Generating

The trace line above the response names the current stage in the user's
language, not the system's:

| Stage | Shown as |
|---|---|
| routing | Choosing a skill |
| retrieving | Searching transcripts |
| generating | Writing / drafting essay |
| critiquing | Checking against the Ship 30 rules |
| revising | Revising — 2 issues to fix |

The Ship 30 revision pass can take a minute. "Revising — 2 issues to fix" makes
that minute legible; a spinner makes it feel broken. When a critique fails, the
first failure is shown verbatim — the user learns what the skill actually
enforces.

A stop control replaces send while streaming.

### Completed answer

The trace line becomes a permanent record: skill, grounded state, provider and
model, latency, and for essays the word count and Ship 30 score. Hovering the
route chip shows *why* that skill was chosen. This is debugging information,
but it is also trust-building information, so it lives in the primary surface
rather than a developer panel.

### Citations

Inline `[S1]` markers in the prose. Below the answer, a collapsed row: *"6
transcript passages."* Expanded, each shows index, episode title, guest,
timestamp, score, and the verbatim quote in the reading serif — so the quote
looks like the transcript it is, not like metadata.

Collapsed by default because the user asked a question, not for a
bibliography. One click away because checking must be trivial.

Citations from the shipped synthetic samples carry an explicit *"Synthetic
sample transcript, not a real episode"* tag. Nothing invented is ever shown as
if it were real.

### Not supported by the corpus

The grounded chip flips to amber and reads *"Not supported by the corpus."* The
answer itself says so in its first sentence and suggests what the corpus does
cover. The closest passages are still shown, labelled as below-threshold — the
user can judge the near-miss themselves, which is often enough to reformulate.

This state is treated as a normal outcome, not an error. It is the behaviour
that makes the rest of the answers worth trusting.

### Artifact viewer

Three tabs. **Preview** is the default — the user asked for a document, so they
see a document. **Source** for the raw text. **Security** carries a dot when the
sanitiser changed something.

Scripts in an HTML artifact do not run until the user presses *Run scripts*.
The button states the fact plainly rather than warning about it; the sandbox is
what makes it safe, and the Security tab explains exactly how.

The Security tab is written for a person, not a compliance form: what was
removed, which sandbox is in force, what is blocked and why the frame's
cross-origin isolation is the part that matters.

### Errors

A rust-bordered notice inside the thread — where the answer would have been,
not in a corner toast that can be missed. Three lines: what happened, what to
do, and the request id with a note that it appears in the backend logs.

## 6. Responsive behaviour

| Width | Layout |
|---|---|
| ≥ 1100px | Three columns. Artifact splits the remaining space with the chat. |
| 760–1100px | Sessions rail stays. The artifact viewer becomes a full-height overlay — at this width a split pane gives neither side a usable measure. |
| < 760px | Single column. The rail becomes a slide-over with a scrim; the artifact viewer is full-screen. Composer and mode chips stay pinned to the bottom. |

`env(safe-area-inset-*)` is honoured throughout, so the composer clears the
home indicator and the sticky header clears the status bar on a phone.

## 7. Accessibility

- **Semantics first.** `<nav>`, `<main>`, `<aside>`, `<article>` per message,
  real `role="tablist"`/`role="tab"` on the artifact tabs, `role="menu"` with
  `aria-checked` on the provider picker.
- **Keyboard.** Everything interactive is a real button or link. Visible focus
  ring on every focusable element. Escape closes the provider menu. Enter sends,
  Shift+Enter breaks a line. The delete control on a session is keyboard
  reachable and does not require hover.
- **Screen readers.** The composer has a real label; icon-only controls carry
  `aria-label`; errors are `role="alert"`; the typing indicator is labelled.
- **Motion.** One animation exists — the three-dot generating indicator — and
  `prefers-reduced-motion` reduces it to nothing. Messages do not fade or slide
  in; a thread that animates on every token is unusable.
- **Contrast.** Body text is ≥ 12:1 on paper; the lightest chrome text is ≥ 4.5:1.
  State is never carried by colour alone — every coloured chip has a text label.
- **Autoscroll respects the reader.** The thread follows new tokens only while
  the user is already near the bottom. Scrolling up to re-read a citation is
  never interrupted.

## 8. Writing in the interface

Sentence case everywhere, no ALL-CAPS labels. Actions say what happens: *New
chat*, *Run scripts*, *Save*, *Hide artifact* — and the resulting state uses
the same word.

The mode chips are named for outcomes the user recognises (*Answer*, *Ship 30
essay*, *Markdown doc*, *HTML artifact*), not for the internal skill
identifiers.

Where a technical fact affects the user's decision, it is stated plainly rather
than hidden: *"Embeddings stay on ollama — Anthropic has no embeddings API, so
the index is never re-embedded by a model change."* The user switching models
deserves to know the consequence.

## 9. Decisions and what they cost

| Decision | Alternative | Why this one |
|---|---|---|
| Citations before the first token | Citations after the answer | On a slow local model this is the difference between a two-second and a forty-second wait before the user has anything to evaluate. |
| Collapsed sources | Always-expanded | Six quotes above the answer buries it. One click is a small enough tax on verification. |
| Serif for answers | One sans throughout | The output is documents. The typeface is what tells you that. |
| Artifact pane appears on demand | Permanent third column | Most turns produce no artifact; a permanently empty pane is dead weight. |
| Exposed trace line (skill, provider, latency) | Hidden in a dev panel | For an internal tool, "why did it answer that way" is a user question, not a developer one. It also makes the demo self-explaining. |
| Manual mode chips alongside auto-routing | Auto-routing only | Routing is confident, not infallible. An override is cheaper than a mis-route, and it lets an evaluator test each skill deliberately. |
| Scripts off until opted in | Always run | The sandbox makes running them safe; defaulting to off makes the safety *visible*, which is the thing the brief asks to be explained. |
| System-driven dark mode | A theme switcher | One fewer control, and it matches what the user already chose at the OS level. |
