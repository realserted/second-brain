"""The SecondBrain service: one object that ingests and searches.
The MCP server, the CLI and the eval suite all go through this class."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import chunk_text
from .config import Settings
from .embeddings import Embedder, build_embedder
from .loaders import discover, load_document
from .redaction import Redactor
from .store import Hit, VectorStore

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    redactions: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        pii = ", ".join(f"{k}={v}" for k, v in sorted(self.redactions.items())) or "none"
        return (
            f"added={len(self.added)} updated={len(self.updated)} "
            f"unchanged={len(self.unchanged)} removed={len(self.removed)} | redacted: {pii}"
        )


class SecondBrain:
    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self.settings = settings
        self.embedder = embedder or build_embedder(settings.embedder, settings.embed_model)
        self.redactor = Redactor(settings.redact)
        self.store = VectorStore(settings.db_path, self.embedder.name, self.embedder.dim)

    @classmethod
    def from_env(cls) -> SecondBrain:
        return cls(Settings.from_env())

    # ---- ingest -------------------------------------------------------

    def ingest(self, docs_dir: Path | None = None) -> IngestReport:
        root = Path(docs_dir or self.settings.docs_dir)
        if not root.is_dir():
            raise FileNotFoundError(f"Docs folder not found: {root.resolve()}")

        report, seen = IngestReport(), set()
        for path in discover(root):
            doc = load_document(path, root)
            seen.add(doc.source)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            existing = self.store.document_hash(doc.source)
            if existing == digest:
                report.unchanged.append(doc.source)
                continue

            redacted = self.redactor.redact(doc.text)
            for category, n in redacted.counts.items():
                report.redactions[category] = report.redactions.get(category, 0) + n

            chunks = chunk_text(redacted.text, self.settings.chunk_size, self.settings.chunk_overlap)
            # Prefix the title so a chunk like "Deductible: $500" keeps its context.
            vectors = self.embedder.embed_documents([f"{doc.title}\n\n{c}" for c in chunks])
            self.store.upsert_document(doc.source, doc.title, digest, redacted.text, chunks, vectors)
            (report.updated if existing else report.added).append(doc.source)
            log.info("indexed %s (%d chunks)", doc.source, len(chunks))

        report.removed = self.store.prune(seen)
        return report

    # ---- query --------------------------------------------------------

    def search(self, query: str, top_k: int | None = None, min_score: float | None = None) -> list[Hit]:
        k = top_k or self.settings.top_k
        floor = self.settings.min_score if min_score is None else min_score
        hits = self.store.search(self.embedder.embed_query(query), k)
        return [h for h in hits if h.score >= floor]

    def list_documents(self) -> list[dict]:
        return self.store.list_documents()

    def get_document(self, source: str) -> dict | None:
        return self.store.get_document(source)

    def close(self) -> None:
        self.store.close()
