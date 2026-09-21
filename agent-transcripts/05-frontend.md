# Session 05 — React app, SSE client, artifact viewer

## Goal

A chat UI that makes provenance obvious, renders artifacts beside the
conversation, and stays usable while a local model takes 40 seconds.

## Prompt 1 — the SSE client

> Consume `POST /api/chat/stream`. EventSource cannot POST, so parse the stream
> manually.

First version split on newlines and assumed each `read()` delivered whole
frames:

```js
const lines = decoder.decode(value).split("\n");
```

Network chunks do not respect frame boundaries. A long citations payload
arrived split across two reads and the JSON parse threw, silently dropping the
citations for that turn — the answer rendered with no sources, intermittently,
which is the worst kind of bug.

**Fix:** a buffer, split on `\n\n`, and `decoder.decode(value, {stream: true})`
so multi-byte characters are not cut in half either:

```js
buffer += decoder.decode(value, { stream: true });
let split;
while ((split = buffer.indexOf("\n\n")) !== -1) {
  const frame = buffer.slice(0, split);
  buffer = buffer.slice(split + 2);
  ...
}
```

The backend test `test_stream_emits_ordered_events` asserts frame ordering, but
it reads through httpx which reassembles for you — so this was only reproducible
in the browser. Noted as a gap: a true chunk-boundary test would need a fake
`ReadableStream`.

## Prompt 2 — autoscroll

The agent wrote the obvious `useEffect` that scrolls to the bottom on every
token. Scrolling up to re-read a citation while the answer streamed yanked you
straight back down.

**Fix:** a `pinnedRef` updated on scroll — follow only when the reader is
already within 120px of the bottom.

```js
pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
```

## Prompt 3 — what to show while waiting

First version: a spinner. Forty seconds of spinner reads as broken.

Rewritten to show the pipeline in the user's language — *Choosing a skill →
Searching transcripts → Writing*, and for essays *Checking against the Ship 30
rules → Revising — 2 issues to fix*. The backend already emitted `status`
events; the UI just had to stop throwing them away.

Citations render **before** the first token, which is the single biggest
perceived-latency win in the app.

## Prompt 4 — the artifact pane

Two corrections:

1. The agent gave the iframe `sandbox="allow-scripts allow-same-origin"`.
   Those two together are equivalent to no sandbox at all — the frame can reach
   into the parent origin. Removed `allow-same-origin` permanently and left a
   comment saying why, because it looks like an omission otherwise.
2. It keyed the iframe only by artifact id, so toggling *Run scripts* did not
   re-mount the frame and scripts never started. Changed the key to
   `${artifact.id}-${scriptsOn}`.

## Prompt 5 — design direction

I rejected the first pass: rounded cards, one accent colour, sans throughout —
a generic SaaS chat. The brief here is a *reading and writing* tool whose
output is essays.

Direction I gave, and what the tokens encode:

- Answers in **Newsreader** at a 64-character measure; chrome in **Inter**.
  Crossing from tool into content should be visible.
- Colour means exactly one thing: provenance. Moss grounded, amber degraded,
  rust failed. Nothing else is coloured, so the code is learnable at a glance.
- The trace line (skill, grounded, provider, latency, Ship 30 score) stays in
  the primary surface, not a developer panel. For an internal tool "why did it
  answer that way" is a user question.

Full rationale in `design.md`.

## Outcome

`npm run build` clean at 365 kB / 116 kB gzipped. Manual test plan in
`docs/manual-test-plan.md`.

## Lesson from the whole project

The agent wrote most of the lines. Every bug that mattered — BM25
normalisation, the stopword-dominated fallback embedder, SSE chunk boundaries,
`allow-same-origin`, essays at 38% of target — was a *plausible-looking*
decision that only an adversarial test or a specific product requirement
exposed. Directing the work meant knowing which properties to assert, not
reading the diffs more carefully.
