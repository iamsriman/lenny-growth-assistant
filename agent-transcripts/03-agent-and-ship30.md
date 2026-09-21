# Session 03 — router, skills, orchestrator

## Goal

Route a message to one of three skills, run the skill over retrieved context,
stream the result, persist everything.

## Prompt 1 — routing

> Build a router that picks between grounded_answer, ship30_essay and artifact.
> Deterministic rules first; only ask the model when the rules are unsure.

First version classified with an LLM call on *every* turn. I rejected it:

> That adds a model round-trip and a new failure mode to every single message,
> on a 3B local model, to answer a question that keyword matching gets right
> almost always. Rules first. The LLM is the tie-break, not the default.

Second version was rules-first but over-fired. "Write a Ship 30 essay and
format it as a markdown doc" routed to `artifact` because `markdown doc`
appeared later in the string and the artifact branch was checked first.

**Fix:** specificity wins ties — the essay check runs first, because the essay
skill produces its own artifact. Encoded as a parametrised test:

```python
def test_essay_beats_generic_artifact_language():
    assert route_by_rules("Write a Ship 30 essay and format it as a markdown doc").skill == SKILL_SHIP30
```

I also made every decision return `reason`, `confidence` and `stage`. A
mis-route you can see is a bug; a mis-route you cannot see is a mystery. Those
fields are now in the logs, on the message row, and in the UI.

## Prompt 2 — Ship 30, and the failure that shaped the skill

> Read the Ship 30 for 30 principles and write a skill that produces a
> ~1,250-word essay from retrieved transcript context.

The agent produced a single large prompt string. It worked against a large
model and failed completely against `llama3.2:3b`:

| Attempt | Word count | Headings | Sources section |
|---|---|---|---|
| 1 | 478 | 3 | missing |
| 2 | 512 | 4 | missing |
| 3 | 604 | 5 | present |

Asking more emphatically ("you MUST write 1,250 words") moved it to ~650 and no
further. Small models do not have a reliable sense of length.

**The fix that made this skill work:** stop asking, and check.

1. `PRINCIPLES` became structured data rather than prose in a prompt string —
   quotable in the UI, diffable in review, editable without touching code.
2. `validate()` returns an `EssayCritique`: word count, headings, bullets, bold
   spans, takeaway section, sources section, banned phrasing, failures, score.
3. A failure produces a revision prompt that names the defect and the remedy:

> The draft is 478 words; it needs about 1,250. Add roughly 772 words by
> DEEPENING existing sections with more detail from the excerpts — add
> examples, mechanisms and counterpoints. Do not add new sections and do not
> pad with filler.

That instruction reliably produces 1,100–1,400 words from the same 3B model
that would not go past 650 when asked directly.

**Guard I added after a bad run:** one revision came back *shorter* and less
structured than the draft. Now the revision is kept only if its score is at
least as good:

```python
if after.score >= critique.score:
    draft, critique = revised, after
```

**Lesson:** deterministic validation plus a specific, mechanical revision
instruction is what makes a small local model usable for a long-form
deliverable. This is the single most important thing in the repo.

## Prompt 3 — orchestrator

> One `run_turn` generator yielding typed events. SSE serialises them; the
> blocking endpoint drains the same generator.

Two bugs:

1. **`_event() got multiple values for argument 'kind'`** — the helper's first
   parameter was named `kind`, and the artifact payload also has a `kind` key,
   so `_event("artifact", **payload)` collided. Renamed the parameter to
   `event_type`. A pure naming bug, invisible until the artifact path ran,
   caught by the artifact test.

2. **Short follow-ups retrieved nothing.** "and cycle time?" is three words and
   embeds to noise. I had the orchestrator prepend the previous user turn — to
   the *retrieval query only*, never to the prompt, so stale context cannot
   contaminate the answer:

```python
def _retrieval_query(user_text, history):
    if len(user_text.split()) >= 8:
        return user_text
    previous = [m.content for m in history if m.role == "user"]
    return f"{previous[-1]} {user_text}" if previous else user_text
```

Test: `test_follow_up_carries_prior_turn_into_retrieval`.

## Outcome

Router, three skills and the orchestrator green, including a test that the
provider-down path returns an actionable error rather than a stack trace.
