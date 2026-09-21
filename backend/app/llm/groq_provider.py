from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.llm.base import LLMProvider, ProviderStatus, ProviderTimeout, ProviderUnavailable

log = logging.getLogger("app.llm.groq")


class GroqProvider(LLMProvider):
    """Groq's OpenAI-compatible chat completions API."""

    name = "groq"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        super().__init__(model or settings.groq_model)
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.base_url = settings.groq_base_url.rstrip("/")

    def _client(self) -> httpx.AsyncClient:
        if not self.api_key:
            raise ProviderUnavailable("GROQ_API_KEY is not set.",
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
        except httpx.ConnectError as exc:
            raise ProviderUnavailable("Cannot reach api.groq.com.",
                                      provider=self.name, kind="unavailable") from exc
        except httpx.ReadTimeout as exc:
            raise ProviderTimeout("Groq request timed out.",
                                  provider=self.name, kind="timeout") from exc
        if resp.status_code in (401, 403):
            raise ProviderUnavailable("Groq rejected the API key.",
                                      provider=self.name, kind="auth")
        if resp.status_code == 429:
            raise ProviderUnavailable("Groq rate limit hit.",
                                      provider=self.name, kind="rate_limit")
        if resp.status_code >= 400:
            raw = resp.text[:200]
            if resp.status_code == 404 and "model" in raw.lower():
                raise ProviderUnavailable(
                    f"Groq model '{self.model}' is unavailable. "
                    "Set GROQ_MODEL to an active Groq model, such as "
                    "'openai/gpt-oss-120b'.",
                    provider=self.name, kind="model_missing")
            raise ProviderUnavailable(f"Groq error {resp.status_code}: {raw}",
                                      provider=self.name, kind="http_error")
        return resp.json()["choices"][0]["message"].get("content") or ""

    async def stream(self, messages, *, system=None, temperature=0.3,
                     max_tokens=2048) -> AsyncIterator[str]:
        body = self._body(messages, system, temperature, max_tokens, True)
        try:
            async with self._client() as client:
                async with client.stream("POST", "/chat/completions", json=body) as resp:
                    if resp.status_code >= 400:
                        raw = await resp.aread()
                        kind = "rate_limit" if resp.status_code == 429 else (
                            "auth" if resp.status_code in (401, 403) else "http_error"
                        )
                        message = "Groq rate limit hit." if kind == "rate_limit" else (
                            "Groq rejected the API key." if kind == "auth" else
                            (
                                f"Groq model '{self.model}' is unavailable. "
                                "Set GROQ_MODEL to an active Groq model, such as "
                                "'openai/gpt-oss-120b'."
                                if resp.status_code == 404 and b"model" in raw.lower()
                                else f"Groq error {resp.status_code}: {raw[:200]!r}"
                            )
                        )
                        raise ProviderUnavailable(
                            message,
                            provider=self.name,
                            kind="model_missing" if resp.status_code == 404 and b"model" in raw.lower()
                            else kind,
                        )
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
        except httpx.ConnectError as exc:
            raise ProviderUnavailable("Cannot reach api.groq.com.",
                                      provider=self.name, kind="unavailable") from exc
        except httpx.ReadTimeout as exc:
            raise ProviderTimeout("Groq stream timed out.",
                                  provider=self.name, kind="timeout") from exc

    async def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(self.name, self.model, False, "GROQ_API_KEY not set")
        return ProviderStatus(self.name, self.model, True, "key present (not verified on boot)")
