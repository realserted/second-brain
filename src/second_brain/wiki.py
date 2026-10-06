"""Checks for the LLM wiki. Claude Code writes the wiki (see docs/wiki-schema.md);
this module only validates it. No LLM calls, no network.

    python -m second_brain.wiki check  [--wiki PATH] [--docs PATH]
    python -m second_brain.wiki status [--wiki PATH]
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

import yaml

from .config import Settings
from .loaders import discover, load_document
from .redaction import Redactor

PAGE_TYPES = ("answer", "entity", "source", "topic")
SPECIAL_PAGES = ("index.md", "log.md")   # catalogue and history: no frontmatter needed
# Repo checkout (editable install) first, then the current folder.
GOLDEN_CANDIDATES = (Path(__file__).resolve().parents[2] / "evals" / "golden.yaml", Path("evals/golden.yaml"))

_FRONTMATTER = re.compile(r"\A---\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_CODE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.DOTALL)   # links in code aren't links
_LINK = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
_DIGIT_RUN = re.compile(r"\d(?:[ .-]?\d)*")   # "0001 2345 6789" and "000123456789" alike
_CITATION = re.compile(r"(?<!\])\(([\w./-]+\.(?:md|txt|pdf))\)")
_LOG_HEADING = re.compile(r"## \[\d{4}-\d{2}-\d{2}\] (?:ingest|file|lint) \| \S.*")


@dataclass(frozen=True)
class Page:
    rel: str                       # path relative to the wiki root, forward slashes
    name: str                      # link name: file name without .md, lowercased
    text: str                      # whole file, frontmatter included
    frontmatter: dict | None
    frontmatter_error: str | None
    links: tuple[str, ...]         # link names, normalised with link_name()
    citations: tuple[str, ...]     # docs-relative paths cited inline

    @property
    def special(self) -> bool:
        return self.rel in SPECIAL_PAGES


@dataclass(frozen=True)
class Issue:
    severity: str                  # "error" fails the check; "warning" doesn't
    page: str
    message: str


def link_name(target: str) -> str:
    """Normalise a link target the way Obsidian resolves it: last path segment,
    no .md suffix, case-insensitive."""
    name = target.strip().rstrip("\\").replace("\\", "/").split("/")[-1]   # [[x\|y]] in tables
    return (name[:-3] if name.lower().endswith(".md") else name).lower()


def parse_page(rel: str, text: str) -> Page:
    frontmatter, error, body = None, None, text
    match = _FRONTMATTER.match(text)
    if match:
        body = text[match.end():]
        try:
            loaded = yaml.safe_load(match.group(1) or "")
        except yaml.YAMLError:
            error = "frontmatter is not valid YAML"
        else:
            if isinstance(loaded, dict):
                frontmatter = loaded
            else:
                error = "frontmatter must be a YAML mapping"
    else:
        error = "missing frontmatter (a --- block at the top of the page)"
    body = _CODE.sub("", body)
    return Page(
        rel=rel,
        name=link_name(rel),
        text=text,
        frontmatter=frontmatter,
        frontmatter_error=error,
        links=tuple(link_name(t) for t in _LINK.findall(body)),
        citations=tuple(_CITATION.findall(body)),
    )


def load_pages(wiki: Path) -> tuple[list[Page], list[Issue]]:
    """Every .md file under the wiki (any case, so Linux and Windows agree),
    skipping hidden folders like .obsidian/."""
    pages: list[Page] = []
    issues: list[Issue] = []
    if not wiki.is_dir():
        return pages, issues
    for path in sorted(wiki.rglob("*")):
        rel = path.relative_to(wiki).as_posix()
        if path.suffix.lower() != ".md" or not path.is_file():
            continue
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")   # tolerate a BOM from Notepad
        except UnicodeDecodeError:
            issues.append(Issue("error", rel, "not valid UTF-8 text"))
            continue
        pages.append(parse_page(rel, text))
    return pages, issues


def known_documents(docs: Path) -> set[str]:
    if not docs.is_dir():
        return set()
    return {f.relative_to(docs).as_posix() for f in docs.rglob("*") if f.is_file()}


def timestamp(value: object) -> str | None:
    """indexed_at as a string, whether YAML parsed it as a datetime or left it quoted."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def check(wiki: Path, docs: Path, redactor: Redactor, canaries: Iterable[str] = ()) -> list[Issue]:
    pages, issues = load_pages(wiki)
    known = known_documents(docs)
    secrets = _Secrets([c for c in canaries if c], redacted_values(docs, redactor))

    by_name: dict[str, str] = {}
    for p in pages:
        if p.name in by_name:
            issues.append(Issue("error", p.rel, f"duplicate page name '{p.name}' (also {by_name[p.name]})"))
        else:
            by_name[p.name] = p.rel
    issues += _duplicate_source_issues(pages)
    attachments = _attachment_names(wiki)   # ![[scan.png]] embeds
    # index.md and log.md link to everything, so they don't count as inbound links
    linked = {n for p in pages if not p.special for n in p.links if n != p.name}

    for p in pages:
        issues += _pii_issues(p, redactor, secrets)
        issues += [Issue("error", p.rel, f"broken link [[{n}]]")
                   for n in dict.fromkeys(p.links) if n not in by_name and n not in attachments]
        issues += [Issue("error", p.rel, f"cites unknown document {c}")
                   for c in dict.fromkeys(p.citations) if c not in known]
        if p.rel == "log.md":
            issues += _log_issues(p)
        if p.special:
            continue
        issues += _frontmatter_issues(p, known)
        if p.name not in linked:
            issues.append(Issue("warning", p.rel, "orphan: no other page links here"))
        if not p.citations:
            issues.append(Issue("warning", p.rel, "no inline citations like (folder/document.md)"))

    present = {p.rel for p in pages}
    issues += [Issue("warning", name, "missing") for name in SPECIAL_PAGES if name not in present]
    issues += _other_file_issues(wiki, present, redactor, secrets)
    # Messages and paths quote page content; scrub them so a report never leaks a value.
    return [Issue(i.severity, secrets.scrub(i.page, redactor), secrets.scrub(i.message, redactor))
            for i in issues]


def redacted_values(docs: Path, redactor: Redactor) -> list[str]:
    """The values ingest removes from the documents, so the wiki can be searched for
    them in any format. Kept in memory only and never printed."""
    values: list[str] = []
    if not docs.is_dir():
        return values
    for path in discover(docs):
        try:
            text = load_document(path, docs).text
        except Exception:   # an unreadable document can't contribute values; ingest reports it
            continue
        for line in text.splitlines():
            redacted = redactor.redact(line).text
            if redacted == line:
                continue
            matcher = difflib.SequenceMatcher(None, line, redacted, autojunk=False)
            for op, i1, i2, j1, j2 in matcher.get_opcodes():
                if op == "replace" and "[REDACTED_" in redacted[j1:j2]:
                    values.append(line[i1:i2].strip())
    return [v for v in dict.fromkeys(values) if len(re.sub(r"\D", "", v)) >= 6]


@dataclass(frozen=True)
class DocStatus:
    source: str
    state: str                     # "new": no source page; "changed": re-indexed since the page was written


def status(pages: Sequence[Page], documents: Sequence[dict]) -> list[DocStatus]:
    """Indexed documents the wiki hasn't caught up with. A source page belongs to
    the first document in its `sources`; its indexed_at must equal that document's
    current ingested_at."""
    written: dict[str, str | None] = {}
    for p in pages:
        fm = p.frontmatter or {}
        sources = fm.get("sources")
        if fm.get("type") == "source" and isinstance(sources, list) and sources:
            written[str(sources[0])] = timestamp(fm.get("indexed_at"))
    pending = []
    for doc in sorted(documents, key=lambda d: d["source"]):
        if doc["source"] not in written:
            pending.append(DocStatus(doc["source"], "new"))
        elif written[doc["source"]] != doc["ingested_at"]:
            pending.append(DocStatus(doc["source"], "changed"))
    return pending


class _Secrets:
    """Known sensitive values: eval canaries plus values redacted from the docs.
    Values with 6+ digits match in any spacing or punctuation."""

    def __init__(self, canaries: list[str], doc_values: list[str]) -> None:
        self.canaries = canaries
        self.doc_values = doc_values

    def found(self, text: str) -> list[str]:
        problems = []
        if any(_contains(text, c) for c in self.canaries):
            problems.append("contains an eval canary value")
        if any(_contains(text, v) for v in self.doc_values):
            problems.append("contains a value that was redacted from your documents")
        return problems

    def scrub(self, text: str, redactor: Redactor) -> str:
        text = redactor.redact(text).text
        for value in self.canaries + self.doc_values:
            digits = re.sub(r"\D", "", value)
            if len(digits) >= 6:
                text = _DIGIT_RUN.sub(
                    lambda m, d=digits: "[CANARY]" if d in re.sub(r"\D", "", m.group()) else m.group(), text)
            text = re.sub(re.escape(value), "[CANARY]", text, flags=re.IGNORECASE)
        return text


def _contains(text: str, value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 6 and any(digits in re.sub(r"\D", "", run) for run in _DIGIT_RUN.findall(text)):
        return True
    return value.lower() in text.lower()


def _duplicate_source_issues(pages: list[Page]) -> list[Issue]:
    first: dict[str, str] = {}
    issues = []
    for p in pages:
        fm = p.frontmatter or {}
        sources = fm.get("sources")
        if fm.get("type") != "source" or not isinstance(sources, list) or not sources:
            continue
        doc = str(sources[0])
        if doc in first:
            issues.append(Issue("error", p.rel, f"source page for {doc} is also covered by {first[doc]}"))
        else:
            first[doc] = p.rel
    return issues


def _attachment_names(wiki: Path) -> set[str]:
    return {link_name(p.name) for p in wiki.rglob("*")
            if p.is_file() and p.suffix.lower() != ".md"
            and not any(part.startswith(".") for part in p.relative_to(wiki).parts)}


def _pii_issues(page: Page, redactor: Redactor, secrets: _Secrets) -> list[Issue]:
    return _text_pii_issues(page.rel, page.text, redactor, secrets)


def _text_pii_issues(rel: str, text: str, redactor: Redactor, secrets: _Secrets) -> list[Issue]:
    # Name the category only; echoing the value would leak it into logs.
    scanned = f"{rel}\n{text}"     # file names can leak too
    found = sorted(redactor.redact(scanned).counts)
    issues = [Issue("error", rel, f"contains {', '.join(found)} that ingest would redact")] if found else []
    issues += [Issue("error", rel, problem) for problem in secrets.found(scanned)]
    return issues


def _other_file_issues(wiki: Path, pages: set[str], redactor: Redactor,
                       secrets: _Secrets) -> list[Issue]:
    """PII-scan every other file (.trash/, .txt, .canvas...). Only Obsidian's own
    settings folder and images are skipped; anything else that can't be read as
    text is an error, so the scan fails closed."""
    issues: list[Issue] = []
    for path in sorted(wiki.rglob("*")):
        rel = path.relative_to(wiki).as_posix()
        if not path.is_file() or rel in pages or rel.split("/")[0] == ".obsidian":
            continue
        if path.suffix.lower() in _IMAGE_SUFFIXES:
            continue
        text = _read_text(path)
        if text is None:
            issues.append(Issue("error", rel, "can't be read as text, so it can't be checked for PII; "
                                              "keep only markdown, text and images in the wiki"))
            continue
        issues += _text_pii_issues(rel, text, redactor, secrets)
    return issues


_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"})


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"  # Notepad "Unicode"
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return None


def _log_issues(page: Page) -> list[Issue]:
    return [
        Issue("error", page.rel, f"line {n}: log headings look like '## [2026-10-06] ingest | Title'")
        for n, line in enumerate(page.text.splitlines(), 1)
        if line.startswith("## ") and not _LOG_HEADING.fullmatch(line.rstrip())
    ]


def _frontmatter_issues(page: Page, known: set[str]) -> list[Issue]:
    if page.frontmatter is None:
        return [Issue("error", page.rel, page.frontmatter_error or "missing frontmatter")]
    fm, problems = page.frontmatter, []
    kind = fm.get("type")
    if kind not in PAGE_TYPES:
        problems.append(f"type must be one of {', '.join(PAGE_TYPES)}")   # don't echo page content
    sources = fm.get("sources")
    if not isinstance(sources, list) or not sources or not all(isinstance(s, str) for s in sources):
        problems.append("sources must be a non-empty list of document paths")
    else:
        problems += [f"sources lists unknown document {s}" for s in sources if s not in known]
    if not _is_date(fm.get("updated")):
        problems.append("updated must be a date like 2026-10-06")
    if kind == "source" and timestamp(fm.get("indexed_at")) is None:
        problems.append("source pages need indexed_at (the document's ingested_at)")
    return [Issue("error", page.rel, m) for m in problems]


def _is_date(value: object) -> bool:
    if isinstance(value, date):
        return True
    if isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


# ---- CLI ---------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m second_brain.wiki",
        description="Validate the LLM wiki and list documents it hasn't caught up with.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check_cmd = sub.add_parser("check", help="Validate PII, links, frontmatter and citations (read-only)")
    check_cmd.add_argument("--wiki", type=Path, help="Wiki folder (default: SECOND_BRAIN_WIKI)")
    check_cmd.add_argument("--docs", type=Path, help="Docs folder (default: SECOND_BRAIN_DOCS)")
    check_cmd.add_argument("--golden", type=Path, help="File with pii_canaries (default: evals/golden.yaml)")
    status_cmd = sub.add_parser("status", help="List indexed documents the wiki is missing or behind on")
    status_cmd.add_argument("--wiki", type=Path, help="Wiki folder (default: SECOND_BRAIN_WIKI)")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    wiki = args.wiki or settings.wiki_dir
    if args.command == "check":
        return _run_check(wiki, args.docs or settings.docs_dir, settings, args.golden)
    return _run_status(wiki, settings)


def _run_check(wiki: Path, docs: Path, settings: Settings, golden: Path | None = None) -> int:
    for label, folder in (("Wiki", wiki), ("Docs", docs)):
        if not folder.is_dir():
            print(f"{label} folder not found: {folder.resolve()}", file=sys.stderr)
            return 2
    issues = check(wiki, docs, Redactor(settings.redact), _canaries(golden))
    for issue in issues:
        print(f"{issue.severity.upper():7} {issue.page}: {issue.message}")
    errors = sum(i.severity == "error" for i in issues)
    pages, _ = load_pages(wiki)
    print(f"wiki check: {len(pages)} pages, {errors} errors, {len(issues) - errors} warnings")
    return 1 if errors else 0


def _canaries(golden: Path | None) -> list[str]:
    path = golden or next((c for c in GOLDEN_CANDIDATES if c.is_file()), None)
    if path is None:
        return []   # values redacted from --docs still protect the wiki
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(c) for c in data.get("pii_canaries", [])]


def _run_status(wiki: Path, settings: Settings) -> int:
    if not settings.db_path.is_file():
        print(f"Index not found: {settings.db_path.resolve()}. Run: python -m second_brain.ingest",
              file=sys.stderr)
        return 2
    from .brain import SecondBrain   # loads the embedding model; only status needs it

    brain = SecondBrain(settings)
    try:
        documents = brain.list_documents()
    finally:
        brain.close()
    pages, _ = load_pages(wiki)
    pending = status(pages, documents)
    for doc in pending:
        print(f"{doc.state:8} {doc.source}")
    print(f"wiki status: {len(documents)} indexed, {len(pending)} need ingest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
