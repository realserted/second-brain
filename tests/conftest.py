from dataclasses import replace
from pathlib import Path

import pytest

from second_brain import SecondBrain, Settings
from second_brain.embeddings import HashEmbedder

DOCS = Path(__file__).resolve().parent.parent / "data" / "docs"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return replace(
        Settings.from_env(),
        db_path=tmp_path / "test.db",
        docs_dir=tmp_path / "docs",
        embedder="hash",
        chunk_size=300,       # small chunks keep the lexical hash embedder focused
        chunk_overlap=50,
        min_score=0.12,
    )


@pytest.fixture
def brain(settings: Settings):
    settings.docs_dir.mkdir()
    b = SecondBrain(settings, embedder=HashEmbedder())
    yield b
    b.close()
