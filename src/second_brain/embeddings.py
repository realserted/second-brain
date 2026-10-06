"""Embedding backends.

FastEmbedEmbedder runs a small ONNX model locally, so document text never
leaves the machine. HashEmbedder is a dependency-free lexical fallback used
by unit tests and offline CI; it is not meant for real retrieval quality.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

Vector = list[float]


def normalize(vec: Sequence[float]) -> Vector:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[Vector]: ...
    def embed_query(self, text: str) -> Vector: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding  # lazy: heavy import, model download

        self.name = model_name
        self._model = TextEmbedding(model_name=model_name)
        self.dim = len(self.embed_query("dimension probe"))

    def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [normalize(v.tolist()) for v in self._model.passage_embed(list(texts))]

    def embed_query(self, text: str) -> Vector:
        return normalize(next(iter(self._model.query_embed(text))).tolist())


_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i in is it my of "
    "on or our the this to was what when where which who why will with you your".split()
)
_TOKEN = re.compile(r"[a-z0-9$]+")


class HashEmbedder:
    """Bag-of-words feature hashing. Deterministic, offline, lexical only."""

    def __init__(self, dim: int = 2048) -> None:
        self.name = f"hash-{dim}"
        self.dim = dim

    def _embed(self, text: str) -> Vector:
        vec = [0.0] * self.dim
        for token in _TOKEN.findall(text.lower()):
            if token in _STOPWORDS:
                continue
            token = token[:-1] if len(token) > 3 and token.endswith("s") else token
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            vec[int.from_bytes(digest, "little") % self.dim] += 1.0
        return normalize(vec)

    def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> Vector:
        return self._embed(text)


def build_embedder(kind: str, model_name: str) -> Embedder:
    if kind == "fastembed":
        return FastEmbedEmbedder(model_name)
    if kind == "hash":
        return HashEmbedder()
    raise ValueError(f"Unknown embedder '{kind}'. Use 'fastembed' or 'hash'.")
