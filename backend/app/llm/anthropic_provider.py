from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.llm.base import (
    LLMProvider,
    ProviderStatus,
    ProviderTimeout,
    ProviderUnavailable,
)

log = logging.getLogger("app.llm.anthropic")


class AnthropicProvider(LLMProvider):
    """Cloud provider. Used for the published deployment and as a fallback.

    Anthropic has no embeddings endpoint, so `embed` intentionally raises and
    the embedding backend is chosen separately via EMBEDDING_PROVIDER.
    """

    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        super().__init__(model or settings.anthropic_model)
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.base_url = settings.anthropic_base_url.rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        if not self.api_key:
            raise ProviderUnavailable(
                "ANTHROPIC_API_KEY is not set.", provider=self.name, kind="missing_key"
            )
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    def _body(self, messages, system, temperature, max_tokens, stream) -> dict:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages
                         if m.role in ("user", "assistant")],
            "stream": stream,
        }
        if system:
            body["system"] = system
        return body

    async def generate(self, messages, *, system=None, temperature=0.3, max_tokens=2048) -> str:
        try:
            async with self._client() as client:
                resp = await client.post(
                    "/v1/messages", json=self._body(messages, system, temperature,
                                                    max_tokens, False)
                )
        except httpx.ReadTimeout as exc:
            raise ProviderTimeout("Anthropic request timed out.",
                                  provider=self.name, kind="timeout") from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailable("Cannot reach api.anthropic.com.",
                                      provider=self.name, kind="unavailable") from exc
        if resp.status_code in (401, 403):
            raise ProviderUnavailable("Anthropic rejected the API key.",
                                      provider=self.name, kind="auth")
        if resp.status_code == 429:
            raise ProviderUnavailable("Anthropic rate limit hit.",
                                      provider=self.name, kind="rate_limit")
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    async def stream(self, messages, *, system=None, temperature=0.3,
                     max_tokens=2048) -> AsyncIterator[str]:
        body = self._body(messages, system, temperature, max_tokens, True)
        try:
            async with self._client() as client:
                async with client.stream("POST", "/v1/messages", json=body) as resp:
                    if resp.status_code >= 400:
                        raw = await resp.aread()
                        raise ProviderUnavailable(
                            f"Anthropic error {resp.status_code}: {raw[:200]!r}",
                            provider=self.name, kind="http_error")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            evt = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if evt.get("type") == "content_block_delta":
                            piece = evt.get("delta", {}).get("text", "")
                            if piece:
                                yield piece
        except httpx.ReadTimeout as exc:
            raise ProviderTimeout("Anthropic stream timed out.",
                                  provider=self.name, kind="timeout") from exc

    async def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(self.name, self.model, False, "ANTHROPIC_API_KEY not set")
        return ProviderStatus(self.name, self.model, True, "key present (not verified on boot)")
