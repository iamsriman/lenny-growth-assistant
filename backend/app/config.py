"""Central configuration.

Every knob the evaluator needs lives here and is driven by environment
variables, so the model, the embedding backend and the database can all be
swapped without touching application code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "anthropic", "openai", "groq"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- app -----------------------------------------------------------
    app_name: str = "Lenny Growth Assistant"
    environment: str = "local"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"

    # ---- database ------------------------------------------------------
    # Supabase / Railway / local docker all speak the same URL scheme.
    database_url: str = "postgresql+asyncpg://lenny:lenny@localhost:5432/lenny"
    db_echo: bool = False
    db_pool_size: int = 5

    # ---- model routing -------------------------------------------------
    # The provider actually used for chat completions.
    llm_provider: ProviderName = "ollama"
    # Used when the primary provider is unreachable. Set to "" to disable.
    llm_fallback_provider: str = ""
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    llm_timeout_seconds: int = 180

    # Embeddings are configured separately because Anthropic does not expose
    # an embeddings endpoint — see architecture.md, "Model toggle".
    embedding_provider: Literal["ollama", "openai", "hash"] = "ollama"

    # ---- ollama --------------------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_embedding_model: str = "nomic-embed-text"

    # ---- anthropic -----------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: str = "https://api.anthropic.com"

    # ---- openai --------------------------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_base_url: str = "https://api.openai.com/v1"

    # ---- groq ----------------------------------------------------------
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # ---- retrieval -----------------------------------------------------
    transcripts_dir: str = "data/transcripts"
    chunk_chars: int = 1100
    chunk_overlap_chars: int = 180
    retrieval_top_k: int = 6
    retrieval_candidate_k: int = 24
    # Below this hybrid score we treat the corpus as "no support" and say so.
    # Calibrated for a real embedding model (nomic-embed-text). The hash
    # fallback produces a flatter score distribution, so it gets its own,
    # lower threshold — using one number for both would either let everything
    # through on hash or reject everything on nomic.
    retrieval_min_score: float = 0.30
    retrieval_min_score_fallback: float = 0.18
    max_chunks_per_episode: int = 2
    embedding_batch_size: int = 16

    # ---- artifacts -----------------------------------------------------
    artifact_max_bytes: int = 400_000
    allow_artifact_scripts: bool = True  # scripts still run cross-origin only

    # ---- agent ---------------------------------------------------------
    router_mode: Literal["rules", "rules+llm"] = "rules+llm"
    ship30_target_words: int = 1250
    ship30_word_tolerance: float = 0.18
    history_turns: int = 8

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, value: str) -> str:
        """Accept the plain URLs Supabase/Railway hand out and make them async."""
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql://", 1)
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def provider_is_configured(self, name: str) -> bool:
        if name == "ollama":
            return bool(self.ollama_base_url)
        if name == "anthropic":
            return bool(self.anthropic_api_key)
        if name == "openai":
            return bool(self.openai_api_key)
        if name == "groq":
            return bool(self.groq_api_key)
        return False

    def model_for(self, name: str) -> str:
        return {
            "ollama": self.ollama_model,
            "anthropic": self.anthropic_model,
            "openai": self.openai_model,
            "groq": self.groq_model,
        }.get(name, "unknown")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
