"""The model toggle.

Nothing above this module knows which vendor is answering. Callers ask for
`chat_provider()` / `embedding_provider()`; swapping models is an env var or a
single PATCH to /api/config.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.config import settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import (
    ChatMessage,
    HashEmbeddingProvider,
    LLMError,
    LLMProvider,
    ProviderStatus,
    ProviderUnavailable,
)
from app.llm.groq_provider import GroqProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_provider import OpenAIProvider

log = logging.getLogger("app.llm.registry")

_BUILDERS = {
    "ollama": OllamaProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "groq": GroqProvider,
}

# Runtime overrides set through PATCH /api/config. Empty means "use .env".
_overrides: dict[str, str] = {}


def available_providers() -> list[str]:
    return list(_BUILDERS)


def active_provider_name() -> str:
    return _overrides.get("llm_provider", settings.llm_provider)


def active_model_name() -> str:
    name = active_provider_name()
    return _overrides.get("model") or settings.model_for(name)


def set_override(*, provider: str | None = None, model: str | None = None) -> None:
    if provider is not None:
        if provider not in _BUILDERS:
            raise ValueError(f"unknown provider '{provider}'")
        _overrides["llm_provider"] = provider
        _overrides.pop("model", None)
    if model:
        _overrides["model"] = model
    log.info("model toggle changed", extra={"component": "llm",
                                            "provider": active_provider_name(),
                                            "model": active_model_name()})


def clear_overrides() -> None:
    _overrides.clear()


def build_provider(name: str, model: str | None = None) -> LLMProvider:
    if name not in _BUILDERS:
        raise ValueError(f"unknown provider '{name}'")
    return _BUILDERS[name](model or settings.model_for(name))


def chat_provider() -> LLMProvider:
    return build_provider(active_provider_name(), _overrides.get("model"))


def fallback_provider() -> LLMProvider | None:
    name = settings.llm_fallback_provider.strip()
    if not name or name == active_provider_name():
        return None
    if not settings.provider_is_configured(name):
        return None
    return build_provider(name)


def embedding_provider():
    """Embeddings follow their own setting because Anthropic has none."""
    choice = settings.embedding_provider
    if choice == "hash":
        return HashEmbeddingProvider()
    if choice == "openai":
        return OpenAIProvider()
    return OllamaProvider()


async def embed_texts(texts: list[str]) -> tuple[list[list[float]], str]:
    """Embed with the configured backend, degrading to the hash embedder.

    Returns (vectors, model_label) so every stored vector records how it was
    produced — mixing embedding models silently is the classic RAG bug.
    """
    provider = embedding_provider()
    try:
        vectors = await provider.embed(texts)
        label = f"{provider.name}:{getattr(provider, 'embedding_model', provider.model)}"
        return vectors, label
    except LLMError as exc:
        log.warning("embedding backend unavailable, using hash fallback",
                    extra={"component": "llm", "error": str(exc), "provider": provider.name})
        fb = HashEmbeddingProvider()
        return await fb.embed(texts), f"{fb.name}:{fb.model}"


async def generate_with_fallback(
    messages: list[ChatMessage],
    *,
    system: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str, str]:
    """Return (text, provider_used, model_used), trying the fallback once."""
    temperature = settings.llm_temperature if temperature is None else temperature
    max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens
    primary = chat_provider()
    try:
        text = await primary.generate(messages, system=system,
                                      temperature=temperature, max_tokens=max_tokens)
        return text, primary.name, primary.model
    except LLMError as exc:
        fb = fallback_provider()
        if fb is None:
            raise
        log.warning("primary provider failed, falling back",
                    extra={"component": "llm", "primary": primary.name,
                           "fallback": fb.name, "error": str(exc)})
        text = await fb.generate(messages, system=system,
                                 temperature=temperature, max_tokens=max_tokens)
        return text, fb.name, fb.model


async def stream_with_fallback(
    messages: list[ChatMessage],
    *,
    system: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (token, provider_name).

    Fallback only happens before the first token; once we have started
    streaming, switching vendors mid-answer would produce incoherent text, so
    we surface the error instead.
    """
    temperature = settings.llm_temperature if temperature is None else temperature
    max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens

    async def _run(provider: LLMProvider):
        started = False
        async for token in provider.stream(messages, system=system,
                                           temperature=temperature, max_tokens=max_tokens):
            started = True
            yield token, provider.name
        if not started:
            raise ProviderUnavailable(f"{provider.name} returned an empty stream",
                                      provider=provider.name, kind="empty")

    primary = chat_provider()
    try:
        async for item in _run(primary):
            yield item
        return
    except LLMError as exc:
        fb = fallback_provider()
        if fb is None:
            raise
        log.warning("stream fallback engaged", extra={"component": "llm",
                                                      "primary": primary.name,
                                                      "fallback": fb.name,
                                                      "error": str(exc)})
        async for item in _run(fb):
            yield item


async def provider_statuses() -> list[ProviderStatus]:
    out = []
    for name in _BUILDERS:
        try:
            out.append(await build_provider(name).status())
        except Exception as exc:  # noqa: BLE001
            out.append(ProviderStatus(name, settings.model_for(name), False, str(exc)[:200]))
    return out
