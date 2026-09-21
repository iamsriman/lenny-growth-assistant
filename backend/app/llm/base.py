from __future__ import annotations

import abc
import hashlib
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


class LLMError(RuntimeError):
    """Base class for every recoverable model failure."""

    def __init__(self, message: str, *, provider: str, kind: str = "error"):
        super().__init__(message)
        self.provider = provider
        self.kind = kind


class ProviderUnavailable(LLMError):
    """The backend is not reachable or not configured (missing key, Ollama down)."""


class ProviderTimeout(LLMError):
    """The backend accepted the request but did not finish in time."""


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ProviderStatus:
    name: str
    model: str
    available: bool
    detail: str = ""
    models_present: list[str] = field(default_factory=list)


class LLMProvider(abc.ABC):
    name: str = "base"

    def __init__(self, model: str):
        self.model = model

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str: ...

    @abc.abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderUnavailable(
            f"{self.name} does not provide embeddings", provider=self.name, kind="unsupported"
        )

    @abc.abstractmethod
    async def status(self) -> ProviderStatus: ...


# Function words carry no topic signal but dominate a bag-of-words vector,
# which is what makes naive hashing embeddings score every document as "quite
# similar" to every query. Dropping them is what lets the fallback discriminate.
_FUNCTION_WORDS = frozenset("""
a an the and or but if of to in on for with is are was were be been being it its
this that these those as at by from how what when why who whom which do does did
you your i we they he she him her our us them their there here about can could
should would will shall may might must not no yes so than then too very just
into over under out up down off again more most some any each other such own
same only also most
""".split())


def hash_embedding(text: str, dim: int = 384) -> list[float]:
    """Deterministic bag-of-words embedding used as a last-resort fallback.

    Hashed trigrams of each content word, with sub-linear term frequency and L2
    normalisation. It is not semantically strong — it matches words, not
    meaning — but it keeps retrieval *working* (and the test suite hermetic)
    when no embedding backend is reachable, and the UI marks answers produced
    this way as degraded.
    """
    counts: dict[int, float] = {}

    def bump(key: str, weight: float) -> None:
        h = int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")
        counts[h % dim] = counts.get(h % dim, 0.0) + weight

    tokens = [t for t in _tokens(text) if t not in _FUNCTION_WORDS and len(t) > 2]
    for token in tokens:
        bump(token, 1.0)
        # Character trigrams give partial credit for morphology
        # ("pricing" / "price", "retention" / "retain").
        stem = token[:6]
        for i in range(len(stem) - 2):
            bump(f"#{stem[i:i + 3]}", 0.25)

    vec = [0.0] * dim
    for index, raw in counts.items():
        vec[index] = 1.0 + math.log(raw) if raw > 0 else 0.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _tokens(text: str) -> list[str]:
    out, buf = [], []
    for ch in text.lower():
        if ch.isalnum():
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


class HashEmbeddingProvider:
    """Embedding-only provider. Never fails, never leaves the process."""

    name = "hash"
    model = "blake2b-bow-384"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [hash_embedding(t) for t in texts]

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, self.model, True, "deterministic local fallback")
