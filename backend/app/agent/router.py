"""Skill routing.

Two-stage on purpose. Stage 1 is deterministic keyword + shape matching: it is
free, instant, and testable, and it covers the overwhelming majority of real
requests. Stage 2 asks the model to classify, but only when stage 1 is
genuinely undecided — on a 3B local model an LLM classifier on *every* turn
would add latency and a new failure mode for no benefit.

Every decision returns its reason, which is logged and shown in the UI, so a
mis-route is diagnosable rather than mysterious.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.llm.base import ChatMessage, LLMError
from app.llm.registry import generate_with_fallback

log = logging.getLogger("app.agent.router")

SKILL_QA = "grounded_answer"
SKILL_SHIP30 = "ship30_essay"
SKILL_ARTIFACT = "artifact"
SKILLS = (SKILL_QA, SKILL_SHIP30, SKILL_ARTIFACT)

_ESSAY_PATTERNS = [
    r"\bship\s*30\b", r"\bship30\b", r"\bessay\b", r"\bnewsletter\b",
    r"\bblog post\b", r"\blinkedin post\b", r"\bwrite (?:me )?(?:a|an) .{0,20}post\b",
    r"\b1,?250 words\b", r"\bthought leadership\b", r"\blong[- ]form\b",
]
_ARTIFACT_PATTERNS = [
    r"\bartifact\b", r"\bhtml\b", r"\bcss\b", r"\blanding page\b", r"\bweb page\b",
    r"\bwebpage\b", r"\bone[- ]pager\b", r"\bcheat ?sheet\b", r"\bdashboard\b",
    r"\bmock ?up\b", r"\bwireframe\b", r"\btemplate\b", r"\bchecklist\b",
    r"\bmarkdown (?:doc|document|file)\b", r"\bslide\b", r"\bcanvas\b",
    r"\brender\b", r"\bdiagram\b", r"\btable of\b", r"\bscorecard\b",
]
_ARTIFACT_STRONG = re.compile(
    r"\b(build|create|make|generate|render|design|draft|produce|mock up|give me)\b",
    re.IGNORECASE,
)
_HTML_HINT = re.compile(r"\b(html|css|page|dashboard|mockup|mock up|wireframe|"
                        r"landing|visual|chart|card)\b", re.IGNORECASE)


@dataclass
class RouteDecision:
    skill: str
    reason: str
    confidence: float
    artifact_kind: str | None = None  # "html" | "markdown"
    stage: str = "rules"

    def as_dict(self) -> dict:
        return {"skill": self.skill, "reason": self.reason,
                "confidence": round(self.confidence, 2),
                "artifact_kind": self.artifact_kind, "stage": self.stage}


def _hits(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def route_by_rules(message: str) -> RouteDecision | None:
    text = message.strip()
    essay = _hits(_ESSAY_PATTERNS, text)
    artifact = _hits(_ARTIFACT_PATTERNS, text)

    # "Write a Ship 30 essay" beats "write a markdown doc" — the essay skill
    # produces its own artifact, so the more specific skill wins.
    if essay:
        return RouteDecision(
            SKILL_SHIP30,
            f"matched essay intent ({len(essay)} signal(s): {essay[0]})",
            0.92 if len(essay) > 1 else 0.8,
        )

    if artifact and _ARTIFACT_STRONG.search(text):
        kind = "html" if _HTML_HINT.search(text) else "markdown"
        if re.search(r"\bmarkdown\b", text, re.IGNORECASE):
            kind = "markdown"
        return RouteDecision(
            SKILL_ARTIFACT,
            f"build verb + artifact noun ({artifact[0]})",
            0.88, artifact_kind=kind,
        )

    if text.endswith("?") or re.match(r"^(what|how|why|when|who|which|should|is|are|"
                                      r"can|do|does|tell me|explain|compare|summar)",
                                      text, re.IGNORECASE):
        return RouteDecision(SKILL_QA, "question shape", 0.85)

    if artifact:
        kind = "html" if _HTML_HINT.search(text) else "markdown"
        return RouteDecision(SKILL_ARTIFACT, f"artifact noun ({artifact[0]})",
                             0.6, artifact_kind=kind)
    return None


_CLASSIFIER_SYSTEM = """You are a request classifier for a product-growth assistant.
Reply with exactly one word and nothing else:

grounded_answer  - the user wants an answer, explanation or comparison
ship30_essay     - the user wants a long-form essay, newsletter or blog post
artifact         - the user wants a document, page, table or visual to be rendered

Reply with one word only."""


async def route(message: str, *, mode: str | None = None) -> RouteDecision:
    decision = route_by_rules(message)
    if decision and decision.confidence >= 0.8:
        log.info("routed", extra={"component": "agent", **decision.as_dict()})
        return decision

    mode = mode or settings.router_mode
    if mode == "rules+llm":
        try:
            raw, provider, _ = await generate_with_fallback(
                [ChatMessage("user", message[:1500])],
                system=_CLASSIFIER_SYSTEM, temperature=0.0, max_tokens=8,
            )
            label = re.sub(r"[^a-z_]", "", raw.strip().lower().split()[0]) if raw.strip() else ""
            if label in SKILLS:
                kind = None
                if label == SKILL_ARTIFACT:
                    kind = "html" if _HTML_HINT.search(message) else "markdown"
                out = RouteDecision(label, f"llm classifier via {provider}", 0.75,
                                    artifact_kind=kind, stage="llm")
                log.info("routed", extra={"component": "agent", **out.as_dict()})
                return out
        except LLMError as exc:
            log.warning("classifier unavailable, keeping rule decision",
                        extra={"component": "agent", "error": str(exc)})

    out = decision or RouteDecision(SKILL_QA, "default: answer from transcripts", 0.5)
    log.info("routed", extra={"component": "agent", **out.as_dict()})
    return out
