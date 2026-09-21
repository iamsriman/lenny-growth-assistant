# Session 02 — chunking, embeddings, hybrid retrieval

## Goal

Ingest transcripts, chunk them usefully, embed them, retrieve with a score good
enough to drive a grounding threshold.

## Prompt 1

> Write a transcript chunker. Input is Markdown with YAML-ish front matter and
> `Speaker: text` lines, plus .vtt/.srt/.json. Chunk on speaker-turn
> boundaries, not fixed windows, with overlap. Preserve speaker and timestamp
> per chunk.

Good output. Two corrections:

1. It pulled in `pyyaml` for five lines of `key: value`. Removed — a 30-line
   parser has no dependency and no surprises. Dependencies on an 8 GB laptop
   running Docker are not free.
2. The final `flush()` emitted the trailing overlap tail as its own chunk, so
   every document ended with a ~180-character duplicate fragment. Caught by
   asserting chunk count against a known file. Fixed with a minimum-length
   filter on the way out.

## Prompt 2 — the bug that mattered

> Add hybrid retrieval: dense cosine over stored embeddings plus BM25 over
> tokens, combined, with a per-episode diversity cap and a grounding threshold.

The agent wrote BM25 correctly and then normalised it like this:

```python
peak = float(scores.max())
return scores / peak if peak > 0 else scores
```

This looks harmless and destroys the entire feature. Dividing by the *observed*
maximum means the top-ranked document scores exactly 1.0 for **every** query,
including nonsense. So this test:

```python
async def test_off_topic_question_is_not_grounded(seeded_client):
    result = await retrieve("what is the melting point of tungsten carbide in kelvin")
    assert result.grounded is False
```

failed with `top_score=0.368` — comfortably over the threshold, because the
lexical component had been renormalised up to 1.0 by the very function meant to
make scores comparable.

I had written that test *before* the retriever, for exactly this reason.

**Fix** — normalise against the maximum *achievable* score for the query:

```python
ceiling += idf * (k1 + 1)          # accumulated per matched term
...
return np.clip(scores / ceiling, 0.0, 1.0)
```

Now a query whose terms are absent from the corpus scores near zero, and the
value means the same thing across queries, which is what a threshold requires.

**Lesson:** an agent will reach for the normalisation that makes numbers look
tidy. Whether a score is *comparable across inputs* is a property no amount of
code review reveals — you need an adversarial input and an assertion.

## Prompt 3 — the fallback embedder

For hermetic tests and for when Ollama is down, I asked for a deterministic
in-process embedder. The first version hashed every token including stopwords:

```python
for token in _tokens(text):          # "the", "of", "in" ...
    vec[h % dim] += 1.0
```

Function words dominate a bag-of-words vector, so every document scored ~0.6
cosine against every query. Combined with the BM25 bug this made *everything*
grounded.

**Fix:** drop function words, add character trigrams for partial morphological
credit ("pricing"/"price"), sub-linear term frequency, L2 normalise. Off-topic
separation went from nothing to 0.15 vs 0.32.

## Prompt 4 — one threshold does not fit two embedders

With the fallback fixed, the real embedder and the hash embedder still produced
different score distributions, so one `RETRIEVAL_MIN_SCORE` either admitted
everything on hash or rejected everything on `nomic-embed-text`.

I added a second setting and made the retriever choose based on what actually
built the index:

```python
threshold = (settings.retrieval_min_score_fallback
             if idx.embedding_model.startswith("hash")
             else settings.retrieval_min_score)
```

This is why `embedding_model` is stored per chunk rather than assumed globally.

## Prompt 5 — pgvector

I asked the agent to argue both sides before writing anything. Its case for
pgvector was "it scales" — true and irrelevant at a few thousand chunks, and it
would add a Postgres extension that breaks plain Postgres and some managed
instances. Chose an in-process NumPy index behind a `VectorIndex` class, and
documented in `architecture.md` §4.3 exactly when to switch.

## Outcome

10 retrieval tests green, including the off-topic case and per-episode
diversity.
