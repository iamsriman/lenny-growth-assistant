"""Ship 30 for 30 essay skill.

The brief asks for the writing principles to be *encoded in the skill* rather
than living in an ad-hoc prompt. So this module has three parts:

  1. `PRINCIPLES` — the rules distilled from the Ship 30 for 30 guide, as
     structured data. They are quotable in the UI and diffable in review.
  2. A prompt builder that turns those principles plus retrieved transcript
     context into an instruction set with a fixed output contract.
  3. `validate()` — a deterministic checker that scores the draft against the
     same principles. Failures drive one targeted revision pass, which is what
     makes a 3B local model produce an acceptable essay at all.

The validator is the important half. Local models under-write badly (a
"1,250-word essay" comes back at 400 words); catching that in code and asking
for a specific expansion beats asking more nicely.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import settings

log = logging.getLogger("app.agent.ship30")

PRINCIPLES: list[dict] = [
    {
        "id": "atomic_idea",
        "name": "One atomic idea",
        "rule": "The essay defends exactly one specific, arguable claim. "
                "If the title could head three different essays, it is too broad.",
    },
    {
        "id": "hook",
        "name": "Earn the second line",
        "rule": "Open with a concrete scene, a number, or a contrarian statement in "
                "under 25 words. No throat-clearing, no 'In today's fast-paced world', "
                "no restating the question.",
    },
    {
        "id": "proof_over_opinion",
        "name": "Proof, not adjectives",
        "rule": "Every claim is carried by a named example, a number, or a quote from "
                "the source material. Cut any sentence that only asserts.",
    },
    {
        "id": "skimmable",
        "name": "Written for the scroll",
        "rule": "Short paragraphs (1-3 sentences). Descriptive H2 headings that make "
                "sense read on their own. Bullets for anything enumerable.",
    },
    {
        "id": "selective_bold",
        "name": "Bold the argument, not the nouns",
        "rule": "Bold only the sentences a skimmer must read — roughly one per section. "
                "Bolding everything bolds nothing.",
    },
    {
        "id": "plain_language",
        "name": "Speak, do not present",
        "rule": "Short sentences, active voice, concrete nouns. Ban: leverage, synergy, "
                "utilize, delve, landscape, tapestry, game-changer, unlock, elevate.",
    },
    {
        "id": "takeaway",
        "name": "End with something to do",
        "rule": "Close with one specific action the reader can take this week, not a "
                "summary of what they just read.",
    },
]

BANNED_WORDS = [
    "leverage", "synergy", "utilize", "delve", "landscape", "tapestry",
    "game-changer", "game changer", "unlock", "elevate", "in today's fast-paced",
    "in conclusion", "furthermore", "moreover", "it is important to note",
    "navigate the complexities", "ever-evolving",
]


@dataclass
class EssayCritique:
    word_count: int = 0
    heading_count: int = 0
    bullet_count: int = 0
    bold_count: int = 0
    has_takeaway: bool = False
    has_sources: bool = False
    banned_used: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict:
        return {
            "word_count": self.word_count, "headings": self.heading_count,
            "bullets": self.bullet_count, "bold_spans": self.bold_count,
            "has_takeaway": self.has_takeaway, "has_sources": self.has_sources,
            "banned_used": self.banned_used, "failures": self.failures,
            "score": round(self.score, 2), "passed": self.passed,
        }


def principles_text() -> str:
    return "\n".join(f"{i}. {p['name']}: {p['rule']}" for i, p in enumerate(PRINCIPLES, 1))


def build_system_prompt() -> str:
    target = settings.ship30_target_words
    return f"""You write Ship 30 for 30 style essays for a product and growth team.

You write ONLY from the transcript excerpts supplied in the context block.
You never invent a statistic, a company outcome or a quote. If the excerpts do
not support a point, you leave the point out.

The Ship 30 for 30 principles you must follow:
{principles_text()}

Output contract — follow it exactly:
- Markdown only. No preamble, no "Here is your essay", no code fences.
- Line 1: `# ` followed by a specific title (max 12 words).
- Then the hook paragraph: under 25 words, no heading above it.
- Then 4 to 6 `## ` sections with descriptive headings.
- At least two bulleted lists somewhere in the body.
- Bold (**like this**) roughly one key sentence per section. Not more.
- A final `## The one thing to do this week` section with a specific action.
- A final `## Sources` section listing each transcript you used as
  `- [S1] Episode title — guest` matching the labels in the context.
- Cite inline as [S1], [S2] where a claim comes from a specific excerpt.
- Length: about {target} words. Write the full essay; do not summarise it."""


def build_user_prompt(topic: str, context_block: str, history_note: str = "") -> str:
    return f"""Write the essay on this topic:

{topic}

{history_note}

Transcript excerpts you may use (cite these as [S1], [S2], ...):

{context_block}

Write the complete essay now, following the output contract exactly."""


def build_revision_prompt(draft: str, critique: EssayCritique, context_block: str) -> str:
    target = settings.ship30_target_words
    instructions = []
    if any("too short" in f for f in critique.failures):
        gap = target - critique.word_count
        instructions.append(
            f"The draft is {critique.word_count} words; it needs about {target}. "
            f"Add roughly {gap} words by DEEPENING existing sections with more detail "
            f"from the excerpts — add examples, mechanisms and counterpoints. "
            f"Do not add new sections and do not pad with filler."
        )
    if any("too long" in f for f in critique.failures):
        instructions.append(
            f"The draft is {critique.word_count} words; cut it to about {target} by "
            f"removing repetition and any sentence that only asserts."
        )
    if any("heading" in f for f in critique.failures):
        instructions.append("Add `## ` sections so the essay has 4 to 6 of them.")
    if any("bullet" in f for f in critique.failures):
        instructions.append("Add at least two bulleted lists where content is enumerable.")
    if any("bold" in f for f in critique.failures):
        instructions.append("Bold exactly one key sentence per section — no more, no fewer.")
    if any("takeaway" in f for f in critique.failures):
        instructions.append(
            "End with `## The one thing to do this week` and one specific action."
        )
    if any("Sources" in f for f in critique.failures):
        instructions.append(
            "Add a `## Sources` section listing each cited transcript as `- [S1] Title — guest`."
        )
    if critique.banned_used:
        instructions.append(
            "Remove and rewrite these words/phrases: " + ", ".join(critique.banned_used) + "."
        )

    numbered = "\n".join(f"- {i}" for i in instructions)
    return f"""Revise the essay below. Fix exactly these problems and change nothing else:

{numbered}

Return the complete revised essay in Markdown. No commentary.

Transcript excerpts (still the only permitted source):

{context_block}

--- DRAFT ---
{draft}"""


_HEADING = re.compile(r"^##\s+\S", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+\S", re.MULTILINE)
_BOLD = re.compile(r"\*\*[^*\n]{3,}?\*\*")
_TAKEAWAY = re.compile(r"^##\s+.*(one thing|takeaway|do this week|start here|"
                       r"your next move)", re.IGNORECASE | re.MULTILINE)
_SOURCES = re.compile(r"^##\s+sources", re.IGNORECASE | re.MULTILINE)


def word_count(markdown: str) -> int:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"[#*_>`\[\]()-]", " ", text)
    return len([w for w in text.split() if any(ch.isalnum() for ch in w)])


def validate(markdown: str) -> EssayCritique:
    target = settings.ship30_target_words
    tol = settings.ship30_word_tolerance
    low, high = int(target * (1 - tol)), int(target * (1 + tol))

    critique = EssayCritique(
        word_count=word_count(markdown),
        heading_count=len(_HEADING.findall(markdown)),
        bullet_count=len(_BULLET.findall(markdown)),
        bold_count=len(_BOLD.findall(markdown)),
        has_takeaway=bool(_TAKEAWAY.search(markdown)),
        has_sources=bool(_SOURCES.search(markdown)),
    )
    lowered = markdown.lower()
    critique.banned_used = [w for w in BANNED_WORDS if w in lowered]

    if critique.word_count < low:
        critique.failures.append(f"too short: {critique.word_count} words (target {target})")
    elif critique.word_count > high:
        critique.failures.append(f"too long: {critique.word_count} words (target {target})")
    if critique.heading_count < 4:
        critique.failures.append(f"too few headings: {critique.heading_count} (need 4-6)")
    if critique.bullet_count < 3:
        critique.failures.append(f"too few bullet items: {critique.bullet_count} (need 3+)")
    if critique.bold_count == 0:
        critique.failures.append("no bold emphasis")
    elif critique.bold_count > max(8, critique.heading_count * 2):
        critique.failures.append(f"over-bolded: {critique.bold_count} bold spans")
    if not critique.has_takeaway:
        critique.failures.append("missing takeaway section")
    if not critique.has_sources:
        critique.failures.append("missing Sources section")
    if critique.banned_used:
        critique.failures.append(f"banned phrasing: {', '.join(critique.banned_used[:4])}")

    checks = 7
    critique.score = max(0.0, (checks - len(critique.failures)) / checks)
    return critique


def extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return match.group(1).strip()[:200] if match else "Ship 30 essay"
