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

log = logging.getLogger("app.llm.openai")


class OpenAIProvider(LLMProvider):
    """Second cloud option. Also the only cloud embedding backend we support."""

    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        super().__init__(model or settings.openai_model)
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.base_url = settings.openai_base_url.rstrip("/")
        self.embedding_model = settings.openai_embedding_model

    def _client(self) -> httpx.AsyncClient:
        if not self.api_key:
            raise ProviderUnavailable("OPENAI_API_KEY is not set.",
                                      provider=self.name, kind="missing_key")
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )

    def _body(self, messages, system, temperature, max_tokens, stream) -> dict:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": m.role, "content": m.content} for m in messages
        ]
        return {"model": self.model, "messages": msgs, "temperature": temperature,
                "max_tokens": max_tokens, "stream": stream}

    async def generate(self, messages, *, system=None, temperature=0.3, max_tokens=2048) -> str:
        try:
            async with self._client() as client:
                resp = await client.post("/chat/completions",
                                         json=self._body(messages, system, temperature,
                                                         max_tokens, False))
        except httpx.ReadTimeout as exc:
            raise ProviderTimeout("OpenAI request timed out.",
                                  provider=self.name, kind="timeout") from exc
        if resp.status_code in (401, 403):
            raise ProviderUnavailable("OpenAI rejected the API key.",
                                      provider=self.name, kind="auth")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""

    async def stream(self, messages, *, system=None, temperature=0.3,
                     max_tokens=2048) -> AsyncIterator[str]:
        body = self._body(messages, system, temperature, max_tokens, True)
        async with self._client() as client:
            async with client.stream("POST", "/chat/completions", json=body) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    raise ProviderUnavailable(f"OpenAI error {resp.status_code}: {raw[:200]!r}",
                                              provider=self.name, kind="http_error")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload in ("", "[DONE]"):
                        continue
                    try:
                        evt = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    piece = evt["choices"][0].get("delta", {}).get("content")
                    if piece:
                        yield piece

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._client() as client:
            resp = await client.post("/embeddings",
                                     json={"model": self.embedding_model, "input": texts})
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]

    async def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(self.name, self.model, False, "OPENAI_API_KEY not set")
        return ProviderStatus(self.name, self.model, True, "key present (not verified on boot)")
