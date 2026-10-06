"""CLI: index a folder of documents.

    python -m second_brain.ingest                  # incremental
    python -m second_brain.ingest --rebuild        # wipe and re-index
    python -m second_brain.ingest --docs path/to/folder
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

from .brain import SecondBrain
from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Index documents into the Second Brain.")
    parser.add_argument("--docs", type=Path, help="Folder to index (default: SECOND_BRAIN_DOCS)")
    parser.add_argument("--db", type=Path, help="Index file (default: SECOND_BRAIN_DB)")
    parser.add_argument("--rebuild", action="store_true", help="Delete the index and start over")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    if args.db:
        settings = replace(settings, db_path=args.db)
    if args.rebuild and settings.db_path.exists():
        settings.db_path.unlink()

    brain = SecondBrain(settings)
    try:
        report = brain.ingest(args.docs)
    finally:
        brain.close()
    print(report.summary())


if __name__ == "__main__":
    main()
