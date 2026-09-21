from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.llm.base import (
    ChatMessage,
    LLMProvider,
    ProviderStatus,
    ProviderTimeout,
    ProviderUnavailable,
)

log = logging.getLogger("app.llm.ollama")


class OllamaProvider(LLMProvider):
    """Local models via the Ollama REST API — the provider used for the demo."""

    name = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 embedding_model: str | None = None):
        super().__init__(model or settings.ollama_model)
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.embedding_model = embedding_model or settings.ollama_embedding_model

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout or settings.llm_timeout_seconds, connect=5.0),
        )

    @staticmethod
    def _payload(messages: list[ChatMessage], system: str | None,
                 temperature: float, max_tokens: int, stream: bool) -> dict:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": m.role, "content": m.content} for m in messages
        ]
        return {
            "model": None,  # filled by caller
            "messages": msgs,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                # 8 GB machines: keep the context modest so the model does not
                # spill to disk. Raise NUM_CTX only if you have headroom.
                "num_ctx": 4096,
            },
        }

    async def generate(self, messages, *, system=None, temperature=0.3, max_tokens=2048) -> str:
        body = self._payload(messages, system, temperature, max_tokens, stream=False)
        body["model"] = self.model
        try:
            async with self._client() as client:
                resp = await client.post("/api/chat", json=body)
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(
                f"Ollama is not reachable at {self.base_url}. Start it with `ollama serve`.",
                provider=self.name, kind="unavailable") from exc
        except httpx.ReadTimeout as exc:
            raise ProviderTimeout(
                f"Ollama did not respond within {settings.llm_timeout_seconds}s.",
                provider=self.name, kind="timeout") from exc
        if resp.status_code == 404:
            raise ProviderUnavailable(
                f"Model '{self.model}' is not pulled. Run: ollama pull {self.model}",
                provider=self.name, kind="model_missing")
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    async def stream(self, messages, *, system=None, temperature=0.3,
                     max_tokens=2048) -> AsyncIterator[str]:
        body = self._payload(messages, system, temperature, max_tokens, stream=True)
        body["model"] = self.model
        try:
            async with self._client() as client:
                async with client.stream("POST", "/api/chat", json=body) as resp:
                    if resp.status_code == 404:
                        raise ProviderUnavailable(
                            f"Model '{self.model}' is not pulled. Run: ollama pull {self.model}",
                            provider=self.name, kind="model_missing")
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        piece = chunk.get("message", {}).get("content", "")
                        if piece:
                            yield piece
                        if chunk.get("done"):
                            break
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(
                f"Ollama is not reachable at {self.base_url}. Start it with `ollama serve`.",
                provider=self.name, kind="unavailable") from exc
        except httpx.ReadTimeout as exc:
            raise ProviderTimeout("Ollama stream timed out.",
                                  provider=self.name, kind="timeout") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        try:
            async with self._client(timeout=120) as client:
                for text in texts:
                    resp = await client.post(
                        "/api/embeddings", json={"model": self.embedding_model, "prompt": text}
                    )
                    if resp.status_code == 404:
                        raise ProviderUnavailable(
                            f"Embedding model '{self.embedding_model}' is not pulled. "
                            f"Run: ollama pull {self.embedding_model}",
                            provider=self.name, kind="model_missing")
                    resp.raise_for_status()
                    out.append(resp.json()["embedding"])
        except httpx.ConnectError as exc:
            raise ProviderUnavailable("Ollama is not reachable for embeddings.",
                                      provider=self.name, kind="unavailable") from exc
        return out

    async def status(self) -> ProviderStatus:
        try:
            async with self._client(timeout=5) as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                names = [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:  # noqa: BLE001
            return ProviderStatus(self.name, self.model, False, f"unreachable: {exc}"[:200])
        has = any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names)
        return ProviderStatus(
            self.name, self.model, has,
            "ready" if has else f"pull the model: ollama pull {self.model}",
            models_present=names,
        )
