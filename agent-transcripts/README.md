# Coding-agent transcripts

The brief asks for these including the failed attempts. Each file is one
working session: what I asked for, what came back, what was wrong with it, and
what I changed. Secrets and keys were never present in these sessions — the
project uses a `.env` that is gitignored and CI fails if one is committed.

The pattern that produced the most useful output: **let the agent write the
code, but insist on a deterministic check for anything that matters.** Almost
every bug below was caught because a test existed, not because I read the diff
carefully.

| File | Session | What went wrong |
|---|---|---|
| [01-scaffolding.md](01-scaffolding.md) | Project skeleton, config, DB layer | Async SQLite in tests, 204 responses, provider abstraction was too thin |
| [02-retrieval.md](02-retrieval.md) | Chunking, embeddings, hybrid retrieval | BM25 normalisation bug that broke the grounding threshold entirely |
| [03-agent-and-ship30.md](03-agent-and-ship30.md) | Router, skills, orchestrator | Router over-fired on "write"; essays came back at 38% of target length |
| [04-artifacts-and-security.md](04-artifacts-and-security.md) | Sanitiser and viewer | First sanitiser was regex-only and trivially bypassable |
| [05-frontend.md](05-frontend.md) | React app, SSE client, artifact pane | SSE frames split across chunks; autoscroll fought the reader |
