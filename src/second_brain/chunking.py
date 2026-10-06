"""Paragraph-aware chunking with character overlap between chunks."""
from __future__ import annotations

import re


def _split_long(paragraph: str, size: int) -> list[str]:
    """Break an oversized paragraph on sentence boundaries, then hard-wrap."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        if len(current) + len(sentence) + 1 <= size:
            current = f"{current} {sentence}".strip()
            continue
        if current:
            pieces.append(current)
        while len(sentence) > size:
            pieces.append(sentence[:size])
            sentence = sentence[size:]
        current = sentence
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, overlap: int) -> str:
    """Last `overlap` characters, starting on a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else tail


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    paragraphs: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if para:
            paragraphs.extend(_split_long(para, size) if len(para) > size else [para])

    chunks, current = [], ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= size:
            current = candidate
            continue
        chunks.append(current)
        carry = _tail(current, overlap)
        current = f"{carry}\n\n{para}" if carry and len(carry) + len(para) + 2 <= size else para
    if current:
        chunks.append(current)
    return chunks
