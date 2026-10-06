"""Shared helpers for the eval scripts."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator

import yaml

from second_brain import SecondBrain, Settings

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "evals" / "golden.yaml"
DOCS = ROOT / "data" / "docs"


def load_golden(path: Path = GOLDEN) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@contextmanager
def fresh_brain(docs: Path = DOCS) -> Iterator[SecondBrain]:
    """Index the docs into a throwaway database so every run starts clean."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = replace(Settings.from_env(), db_path=Path(tmp) / "eval.db", docs_dir=docs)
        brain = SecondBrain(settings)
        try:
            print(f"Indexed docs: {brain.ingest().summary()}")
            yield brain
        finally:
            brain.close()


def write_summary(markdown: str) -> None:
    """Append to the GitHub Actions job summary when running in CI."""
    target = os.getenv("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")
