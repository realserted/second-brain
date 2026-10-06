"""Turn files on disk into plain text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {".md", ".txt", ".pdf"}


@dataclass(frozen=True)
class LoadedDocument:
    source: str   # path relative to the docs root, forward slashes
    title: str
    text: str


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def _title(text: str, path: Path) -> str:
    match = re.search(r"^\s*#\s+(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first_line[:120] if first_line else path.stem.replace("-", " ").title()


def load_document(path: Path, root: Path) -> LoadedDocument:
    text = _read_pdf(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
    return LoadedDocument(
        source=path.relative_to(root).as_posix(),
        title=_title(text, path),
        text=text,
    )


def discover(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
