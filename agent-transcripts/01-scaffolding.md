# Session 01 — scaffolding, config, database

## Goal

Project skeleton, settings, SQLAlchemy models, health endpoints. Get to a
running FastAPI app with a green test.

## Prompt 1

> Build a FastAPI backend skeleton with pydantic-settings config, async
> SQLAlchemy 2.0 models for chat sessions / messages / artifacts, and
> health + readiness endpoints. Postgres in production, SQLite for tests.

**Result:** good structure, three problems.

### Problem 1 — every test saw an empty database

The agent used `sqlite+aiosqlite:///:memory:` with the default pool. Every
connection to `:memory:` gets its *own* database, so `init_db()` created tables
on one connection and the test queried another.

Symptom: `no such table: chat_sessions`, but only in tests.

**Fix** — `StaticPool` when the URL is in-memory:

```python
if settings.is_sqlite and ":memory:" in settings.database_url:
    from sqlalchemy.pool import StaticPool
    kwargs["poolclass"] = StaticPool
    kwargs["connect_args"] = {"check_same_thread": False}
```

I asked for this specifically rather than switching to a file-backed test DB —
a file would have hidden the issue and left a cleanup problem.

### Problem 2 — `DELETE` returning 204 crashed at import time

```
AssertionError: Status code 204 must not have a response body
```

Not a runtime error — FastAPI asserts at route-registration time, so the whole
app failed to import. The agent had written `-> None` with
`status_code=204`, which FastAPI still treats as a JSON body.

**Fix:** `response_class=Response` and return an explicit
`Response(status_code=204)`.

Worth noting because it is a class of bug an agent produces often: code that is
*correct Python* and *wrong framework*.

### Problem 3 — the provider abstraction was too thin

The first version had `generate()` only. I pushed back:

> The provider interface needs `stream()` and `status()` as well. Streaming is
> not optional — a 3B local model takes 40 seconds and the UI has to show
> progress. `status()` is how the UI knows whether a provider is even reachable
> before the user picks it.

It also wanted to put embeddings on the same interface for every provider. I
rejected that: Anthropic has no embeddings endpoint, so the base class raises
`ProviderUnavailable(kind="unsupported")` and embeddings are configured by a
separate setting. That decision is now documented in `architecture.md` §7,
because it looks like an inconsistency until you know why.

## Prompt 2

> Add a request-id ContextVar, JSON structured logging with a `component`
> field, and exception handlers so every error response has the same shape.

Worked first time. The one change I made by hand: the JSON formatter's
`RESERVED` set was hand-written and missed `taskName` (added in Python 3.12),
which leaked into every log line. Replaced it with an introspected set:

```python
RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"asctime", "message", "taskName"}
```

## Outcome

App imports, 4 health/session tests green.

## Lesson

The two real bugs were both invisible to inspection and obvious to a test. From
here on I wrote the test in the same prompt as the feature.
