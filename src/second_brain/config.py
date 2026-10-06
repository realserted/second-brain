"""Runtime settings, read from environment variables with sensible defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REDACTIONS = "ssn,credit_card,bank_account,routing_number"


def _env(name: str, default: str) -> str:
    return os.getenv(f"SECOND_BRAIN_{name}", default)


@dataclass(frozen=True)
class Settings:
    db_path: Path
    docs_dir: Path
    wiki_dir: Path         # LLM wiki maintained by Claude Code (see docs/wiki-schema.md)
    embedder: str          # "fastembed" (real model) or "hash" (offline tests)
    embed_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    min_score: float       # results below this similarity are dropped (abstention)
    redact: frozenset[str]

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=Path(_env("DB", "data/second_brain.db")),
            docs_dir=Path(_env("DOCS", "data/docs")),
            wiki_dir=Path(_env("WIKI", "wiki")),
            embedder=_env("EMBEDDER", "fastembed"),
            embed_model=_env("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
            chunk_size=int(_env("CHUNK_SIZE", "900")),
            chunk_overlap=int(_env("CHUNK_OVERLAP", "150")),
            top_k=int(_env("TOP_K", "5")),
            min_score=float(_env("MIN_SCORE", "0.56")),
            redact=frozenset(
                c.strip() for c in _env("REDACT", DEFAULT_REDACTIONS).split(",") if c.strip()
            ),
        )
