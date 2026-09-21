"""Artifact generation skill (Markdown documents and HTML/CSS snippets)."""

from __future__ import annotations

import re

HTML_SYSTEM = """You produce a single self-contained HTML document for an in-app
artifact viewer.

Hard constraints — the renderer enforces these, so breaking them means your
output gets stripped:
- One complete HTML document. Inline <style> only. No external stylesheets,
  fonts, scripts or images; no fetch, XHR or network calls of any kind.
- No <iframe>, <object>, <embed>, <form>, <base> or <link> tags.
- No inline event handlers (onclick=...). If you need behaviour, use one
  <script> block with addEventListener.
- Inline SVG is allowed and is the right way to draw charts and diagrams.

Content constraints:
- Ground every claim in the transcript excerpts supplied. Cite as [S1], [S2].
- Never invent numbers to make a chart look good. If you have no data, design
  the structure and label it as a template.

Design: clean, readable, responsive down to 360px, sufficient contrast,
system font stack. Output ONLY the HTML. No commentary, no code fences."""

MARKDOWN_SYSTEM = """You produce a single Markdown document for an in-app artifact
viewer.

- Start with a `# ` title.
- Use headings, tables and bullets so the document is skimmable.
- Ground every claim in the transcript excerpts supplied and cite as [S1], [S2].
- Finish with a `## Sources` section listing the transcripts used.
- Output ONLY Markdown. No commentary, no code fences around the whole document."""


def build_user_prompt(request: str, context_block: str, conversation_digest: str,
                      kind: str) -> str:
    fmt = "HTML document" if kind == "html" else "Markdown document"
    return f"""Build a {fmt} for this request:

{request}

What the conversation has established so far:
{conversation_digest or "(this is the first turn)"}

Transcript excerpts you may draw on:

{context_block or "(no transcript context was retrieved — build the structure and say so in the document)"}

Produce the {fmt} now."""


_TITLE_MD = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_TITLE_HTML = re.compile(r"<title[^>]*>(.*?)</title>|<h1[^>]*>(.*?)</h1>",
                         re.IGNORECASE | re.DOTALL)


def extract_title(content: str, kind: str, fallback: str) -> str:
    if kind == "markdown":
        match = _TITLE_MD.search(content)
        if match:
            return match.group(1).strip()[:200]
    else:
        match = _TITLE_HTML.search(content)
        if match:
            raw = match.group(1) or match.group(2) or ""
            cleaned = re.sub(r"<[^>]+>", "", raw).strip()
            if cleaned:
                return cleaned[:200]
    return fallback[:200] or "Untitled artifact"
