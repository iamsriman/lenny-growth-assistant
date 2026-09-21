"""Transcript parsing and chunking.

Supported inputs: Markdown/plain text with optional YAML front matter, .vtt,
.srt and .json. Everything is normalised into `ParsedTranscript`, then chunked
on **speaker-turn boundaries** rather than fixed character windows, because a
podcast answer that gets cut mid-sentence loses the point it was making.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TIMESTAMP = re.compile(r"^\(?\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\)?\s*")
_SPEAKER = re.compile(r"^([A-Z][\w .'\-]{1,40}):\s+")
_VTT_CUE_TIME = re.compile(r"(\d{2}:\d{2}:\d{2})[.,]\d{3}\s*-->")


@dataclass
class Turn:
    speaker: str | None
    start_label: str | None
    text: str


@dataclass
class ParsedTranscript:
    external_id: str
    title: str
    guest: str | None
    url: str | None
    published_at: str | None
    synthetic: bool
    turns: list[Turn]
    meta: dict = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n".join(t.text for t in self.turns)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.full_text.encode("utf-8")).hexdigest()


@dataclass
class Chunk:
    ordinal: int
    text: str
    speaker: str | None
    start_label: str | None

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.text) // 4)


def _parse_front_matter(raw: str) -> tuple[dict, str]:
    """Minimal `key: value` front matter reader — no YAML dependency needed."""
    match = _FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    meta: dict = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip('"').strip("'")
        key = key.strip().lower()
        if value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value
    return meta, raw[match.end():]


def _turns_from_text(body: str) -> list[Turn]:
    turns: list[Turn] = []
    current: Turn | None = None
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):          # markdown section heading
            if current:
                turns.append(current)
                current = None
            turns.append(Turn(None, None, line.lstrip("# ").strip()))
            continue
        work = line.strip()
        start_label = None
        ts = _TIMESTAMP.match(work)
        if ts:
            start_label = ts.group(1)
            work = work[ts.end():]
        speaker_match = _SPEAKER.match(work)
        if speaker_match:
            if current:
                turns.append(current)
            current = Turn(speaker_match.group(1).strip(), start_label,
                           work[speaker_match.end():].strip())
        elif current:
            current.text = f"{current.text} {work}".strip()
        else:
            current = Turn(None, start_label, work)
    if current:
        turns.append(current)
    return [t for t in turns if t.text]


def _turns_from_vtt(raw: str) -> list[Turn]:
    turns: list[Turn] = []
    start_label: str | None = None
    buffer: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("WEBVTT") or stripped.isdigit():
            continue
        cue = _VTT_CUE_TIME.search(stripped)
        if cue:
            if buffer:
                turns.append(Turn(None, start_label, " ".join(buffer)))
                buffer = []
            start_label = cue.group(1)[3:] if cue.group(1).startswith("00:") else cue.group(1)
            continue
        if stripped:
            buffer.append(re.sub(r"<[^>]+>", "", stripped))
    if buffer:
        turns.append(Turn(None, start_label, " ".join(buffer)))
    # Merge the tiny caption cues into readable paragraphs.
    merged: list[Turn] = []
    for turn in turns:
        if merged and len(merged[-1].text) < 600:
            merged[-1].text = f"{merged[-1].text} {turn.text}".strip()
        else:
            merged.append(turn)
    return merged


def parse_file(path: Path) -> ParsedTranscript:
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()

    if suffix == ".json":
        data = json.loads(raw)
        turns = [
            Turn(seg.get("speaker"), seg.get("start") or seg.get("timestamp"),
                 (seg.get("text") or "").strip())
            for seg in data.get("segments", data.get("transcript", []))
            if (seg.get("text") or "").strip()
        ]
        return ParsedTranscript(
            external_id=str(data.get("id") or path.stem),
            title=data.get("title") or path.stem.replace("-", " ").title(),
            guest=data.get("guest"),
            url=data.get("url"),
            published_at=data.get("published_at") or data.get("date"),
            synthetic=bool(data.get("synthetic", False)),
            turns=turns,
            meta={"source_file": path.name, "format": "json"},
        )

    if suffix in (".vtt", ".srt"):
        return ParsedTranscript(
            external_id=path.stem,
            title=path.stem.replace("-", " ").replace("_", " ").title(),
            guest=None, url=None, published_at=None, synthetic=False,
            turns=_turns_from_vtt(raw),
            meta={"source_file": path.name, "format": suffix.lstrip(".")},
        )

    meta, body = _parse_front_matter(raw)
    title = meta.get("title") or path.stem.replace("-", " ").replace("_", " ").title()
    return ParsedTranscript(
        external_id=str(meta.get("id") or path.stem),
        title=title,
        guest=meta.get("guest"),
        url=meta.get("url"),
        published_at=meta.get("date") or meta.get("published_at"),
        synthetic=bool(meta.get("synthetic", False)),
        turns=_turns_from_text(body),
        meta={"source_file": path.name, "format": "markdown",
              **{k: v for k, v in meta.items()
                 if k not in ("title", "guest", "url", "date", "published_at", "id", "synthetic")}},
    )


def chunk_turns(
    turns: list[Turn],
    target_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[Chunk]:
    """Greedily pack whole turns into ~`target_chars` chunks with overlap.

    A turn longer than the target is split on sentence boundaries so we never
    cut mid-word, and the trailing sentences of chunk N are prepended to chunk
    N+1 so a claim that straddles the boundary is still retrievable.
    """
    target = target_chars or settings.chunk_chars
    overlap = overlap_chars or settings.chunk_overlap_chars

    units: list[Turn] = []
    for turn in turns:
        if len(turn.text) <= target:
            units.append(turn)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", turn.text)
        buf = ""
        for sentence in sentences:
            if buf and len(buf) + len(sentence) + 1 > target:
                units.append(Turn(turn.speaker, turn.start_label, buf.strip()))
                buf = sentence
            else:
                buf = f"{buf} {sentence}".strip()
        if buf:
            units.append(Turn(turn.speaker, turn.start_label, buf.strip()))

    chunks: list[Chunk] = []
    buf_parts: list[str] = []
    buf_len = 0
    lead_speaker: str | None = None
    lead_label: str | None = None

    def flush() -> None:
        nonlocal buf_parts, buf_len, lead_speaker, lead_label
        if not buf_parts:
            return
        text = "\n".join(buf_parts).strip()
        if text:
            chunks.append(Chunk(len(chunks), text, lead_speaker, lead_label))
        tail = text[-overlap:] if overlap else ""
        buf_parts = [tail] if tail else []
        buf_len = len(tail)
        lead_speaker, lead_label = None, None

    for unit in units:
        rendered = f"{unit.speaker}: {unit.text}" if unit.speaker else unit.text
        if buf_len and buf_len + len(rendered) > target:
            flush()
        if lead_speaker is None:
            lead_speaker, lead_label = unit.speaker, unit.start_label
        buf_parts.append(rendered)
        buf_len += len(rendered) + 1
    flush()
    # The final flush leaves only the overlap tail behind; drop it.
    return [c for c in chunks if len(c.text) > 80]


def discover_transcripts(directory: str | Path) -> list[Path]:
    root = Path(directory)
    if not root.exists():
        return []
    exts = {".md", ".txt", ".vtt", ".srt", ".json"}
    return sorted(p for p in root.rglob("*")
                  if p.suffix.lower() in exts and p.is_file()
                  and not p.name.startswith("_") and p.name.lower() != "readme.md")
