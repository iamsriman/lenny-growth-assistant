#!/usr/bin/env python3
"""Pull a transcript corpus into data/transcripts/.

Two ways to use it:

  # A git repository of transcripts
  python scripts/fetch_transcripts.py --repo https://github.com/<owner>/<repo>

  # A folder you already have (exports, Whisper output, a Drive download)
  python scripts/fetch_transcripts.py --local "D:/downloads/lenny-transcripts"

Files are copied flat, de-duplicated by content hash, normalised to .md, and
given front matter if they have none, so the ingester can read every one.
Nothing is deleted: the labelled sample-*.md files stay until you remove them.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXTS = {".md", ".txt", ".vtt", ".srt", ".json"}
FRONT_MATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "transcript"


def guess_title(path: Path) -> str:
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}[-_]?", "", path.stem)
    return stem.replace("-", " ").replace("_", " ").strip().title()


def ensure_front_matter(text: str, path: Path) -> str:
    if FRONT_MATTER.match(text):
        return text
    return (
        "---\n"
        f"title: {guess_title(path)}\n"
        f"id: {slugify(path.stem)}\n"
        "guest:\n"
        "url:\n"
        "synthetic: false\n"
        "---\n\n" + text
    )


def clone(repo: str, branch: str | None) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="lga-transcripts-"))
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo, str(tmp)]
    print(f"$ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit("git is not installed or not on PATH.")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"git clone failed ({exc.returncode}). Check the URL and your access.")
    return tmp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="git URL of a transcript repository")
    source.add_argument("--local", help="a folder already on disk")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--subdir", default="",
                        help="only copy from this path inside the source")
    parser.add_argument("--out", default="data/transcripts")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N files (useful on a small machine)")
    args = parser.parse_args()

    root = clone(args.repo, args.branch) if args.repo else Path(args.local).expanduser()
    if not root.exists():
        sys.exit(f"Source not found: {root}")
    if args.subdir:
        root = root / args.subdir

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    copied = skipped = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EXTS:
            continue
        if path.name.lower() == "readme.md":
            continue

        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            skipped += 1
            continue
        seen.add(digest)

        target = out / f"{slugify(path.stem)}{path.suffix.lower()}"
        if path.suffix.lower() in (".md", ".txt"):
            text = raw.decode("utf-8", errors="replace")
            target = out / f"{slugify(path.stem)}.md"
            target.write_text(ensure_front_matter(text, path), encoding="utf-8")
        else:
            shutil.copy2(path, target)

        copied += 1
        if args.limit and copied >= args.limit:
            break

    print(f"\nCopied {copied} transcript(s) into {out}  (skipped {skipped} duplicate(s))")
    print("Next:")
    print("  docker compose exec api python -m app.rag.ingest --path /app/data/transcripts")
    print("  # or, running locally:  cd backend && python -m app.rag.ingest --path ../data/transcripts")
    print("\nRemember to delete the sample-*.md placeholders once real transcripts are loaded.")


if __name__ == "__main__":
    main()
