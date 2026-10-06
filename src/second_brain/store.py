"""SQLite storage: documents and chunks in normal tables, vectors in a
sqlite-vec virtual table keyed by chunk id."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from typing import Callable, Sequence, TypeVar

import sqlite_vec

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    source TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    content TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Hit:
    source: str
    title: str
    text: str
    score: float  # cosine similarity, 1.0 = identical


class IndexMismatchError(RuntimeError):
    pass


F = TypeVar("F", bound=Callable)


def _locked(method: F) -> F:
    """Serialize access: the MCP server runs sync tools on worker threads, and a
    sqlite3 connection must not be used by two threads at once."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class VectorStore:
    def __init__(self, path: Path | str, embedder_name: str, dim: int) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks "
            f"USING vec0(embedding float[{dim}] distance_metric=cosine)"
        )
        self._check_embedder(embedder_name, dim)

    def _check_embedder(self, name: str, dim: int) -> None:
        """Refuse to mix vectors from different models in one index."""
        stored = dict(self._db.execute("SELECT key, value FROM meta").fetchall())
        if not stored:
            with self._db:
                self._db.executemany(
                    "INSERT INTO meta VALUES (?, ?)", [("embedder", name), ("dim", str(dim))]
                )
        elif stored != {"embedder": name, "dim": str(dim)}:
            raise IndexMismatchError(
                f"Index was built with {stored['embedder']} ({stored['dim']}d), "
                f"current embedder is {name} ({dim}d). Re-run ingest with --rebuild."
            )

    # ---- writes -------------------------------------------------------

    @_locked
    def document_hash(self, source: str) -> str | None:
        row = self._db.execute("SELECT sha256 FROM documents WHERE source = ?", (source,)).fetchone()
        return row[0] if row else None

    @_locked
    def upsert_document(
        self,
        source: str,
        title: str,
        sha256: str,
        content: str,
        chunks: Sequence[str],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must be the same length")
        with self._db:
            self._delete(source)
            doc_id = self._db.execute(
                "INSERT INTO documents (source, title, sha256, content, ingested_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (source, title, sha256, content, datetime.now(timezone.utc).isoformat()),
            ).lastrowid
            for ordinal, (text, vec) in enumerate(zip(chunks, vectors)):
                chunk_id = self._db.execute(
                    "INSERT INTO chunks (document_id, ordinal, text) VALUES (?, ?, ?)",
                    (doc_id, ordinal, text),
                ).lastrowid
                self._db.execute(
                    "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                    (chunk_id, sqlite_vec.serialize_float32(list(vec))),
                )

    @_locked
    def prune(self, keep_sources: set[str]) -> list[str]:
        """Remove documents that no longer exist on disk."""
        stale = [s for (s,) in self._db.execute("SELECT source FROM documents") if s not in keep_sources]
        with self._db:
            for source in stale:
                self._delete(source)
        return stale

    def _delete(self, source: str) -> None:
        # vec0 tables don't cascade, so remove vectors before the chunk rows.
        self._db.execute(
            "DELETE FROM vec_chunks WHERE rowid IN ("
            "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id WHERE d.source = ?)",
            (source,),
        )
        self._db.execute("DELETE FROM documents WHERE source = ?", (source,))

    # ---- reads --------------------------------------------------------

    @_locked
    def search(self, vector: Sequence[float], k: int) -> list[Hit]:
        rows = self._db.execute(
            """
            SELECT d.source, d.title, c.text, v.distance
            FROM (SELECT rowid, distance FROM vec_chunks
                  WHERE embedding MATCH ? AND k = ? ORDER BY distance) v
            JOIN chunks c ON c.id = v.rowid
            JOIN documents d ON d.id = c.document_id
            ORDER BY v.distance
            """,
            (sqlite_vec.serialize_float32(list(vector)), k),
        ).fetchall()
        return [Hit(source, title, text, round(1.0 - dist, 4)) for source, title, text, dist in rows]

    @_locked
    def list_documents(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT d.source, d.title, d.ingested_at, COUNT(c.id) FROM documents d "
            "LEFT JOIN chunks c ON c.document_id = d.id GROUP BY d.id ORDER BY d.source"
        ).fetchall()
        return [
            {"source": s, "title": t, "ingested_at": at, "chunks": n} for s, t, at, n in rows
        ]

    @_locked
    def get_document(self, source: str) -> dict | None:
        row = self._db.execute(
            "SELECT source, title, content FROM documents WHERE source = ?", (source,)
        ).fetchone()
        return {"source": row[0], "title": row[1], "content": row[2]} if row else None

    @_locked
    def all_text(self) -> str:
        """Everything stored, for PII leak audits."""
        docs = " ".join(r[0] for r in self._db.execute("SELECT content FROM documents"))
        chunks = " ".join(r[0] for r in self._db.execute("SELECT text FROM chunks"))
        return f"{docs} {chunks}"

    @_locked
    def close(self) -> None:
        self._db.close()
