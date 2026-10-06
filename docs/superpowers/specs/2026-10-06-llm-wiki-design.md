# LLM Wiki for Second Brain: design

Date: 2026-10-06
Status: approved in conversation, awaiting written-spec review

## Goal

Add a Karpathy-style "LLM Wiki" (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) on top of the Second Brain: a folder of linked markdown pages that an LLM writes and maintains, browsable as a graph in Obsidian, and that gets more useful over time as documents are ingested, good answers are filed, and periodic lint passes fix drift.

## Decisions

| Decision | Choice |
|---|---|
| Who writes the wiki | Claude Code, in an interactive session, following `docs/wiki-schema.md`. No Python LLM pipeline. |
| Filing answers | Ask first. Claude offers to file a synthesised answer; it writes only on a yes. |
| Where it lives | Two wikis, same format. `wiki/` in the repo is built from the synthetic `data/docs` and committed. The real wiki lives outside the repo at `SECOND_BRAIN_WIKI`. |
| Cost | No paid API calls anywhere in this feature. The Python code makes no LLM or network calls. LLM work happens only inside the user's own Claude Code session. |
| MCP server | Unchanged and still read-only. No wiki tools in v1. |

## Invariants this design keeps

- **Redacted text only.** Claude Code reads document content only through the MCP `get_document` / `search_documents` tools, which return redacted text. It never opens raw files under the docs folder to build the wiki.
- **The index stays the source of truth.** Wiki facts cite the document they came from, and answers are confirmed against `search_documents`.
- **MCP tools stay read-only**, `server.py` is untouched, and existing evals and thresholds are unchanged.
- **The real wiki never enters git.** It lives outside the repo by default.

## 1. Layout and page format

```
<wiki>/
  index.md      catalogue of every page, grouped by type
  log.md        append-only history
  sources/      one page per indexed document
  entities/     people, organisations, things appearing across documents
  topics/       cross-cutting views (deadlines-and-renewals, monthly-costs)
  answers/      filed Q&A pages
```

- File names are lowercase-hyphenated, and a page's link name is its file name without `.md` (`[[acme-analytics]]`). Link names are unique across the wiki.
- Every page except `index.md` and `log.md` starts with YAML frontmatter:
  ```yaml
  ---
  type: source | entity | topic | answer
  sources: [leases/apartment-lease.md]   # docs-relative paths; at least one
  updated: 2026-10-06                     # ISO date
  indexed_at: 2026-10-06T03:36:51.662657+00:00   # source pages only: the document's ingested_at when the page was written
  ---
  ```
- Facts cite their document inline as a docs-relative path in parentheses: `Rent is $1,450/month (leases/apartment-lease.md)`. The checker recognises a citation as `(<path>.md|.txt|.pdf)`.
- Redacted values stay as their tags (`[REDACTED_SSN]`), never reconstructed or guessed.
- Pages link to each other with `[[name]]`, `[[name|alias]]` or `[[name#heading]]`.
- An entity page is created when the entity appears in two or more documents, or when the user asks.
- `log.md` entries are headings of the form `## [YYYY-MM-DD] <op> | <subject>`, where `<op>` is `ingest`, `file` or `lint`, followed by a short bullet list of pages created or changed.

## 2. Workflows (written into `docs/wiki-schema.md`)

**Ingest** ("update the wiki"):
1. Run `python -m second_brain.wiki status` to list indexed documents with no source page, or re-indexed since the page was written.
2. For each, read the redacted text with MCP `get_document`.
3. Write or update the source page (copying the document's `ingested_at` into `indexed_at`); create or extend entity and topic pages; update `index.md`; append to `log.md`.
4. Run `python -m second_brain.wiki check` and fix any errors before finishing.
5. Report pages created and changed.

**Ask, then file** (any question about the documents):
1. Read the wiki first (`index.md`, then linked pages); confirm key facts with `search_documents`.
2. If the answer is a new synthesis, ask "Want me to file this in the wiki?".
3. On yes, write an `answers/YYYY-MM-DD-<slug>.md` page linked to the entities involved, update `index.md` and `log.md`, and run `check`.

**Lint** ("lint the wiki"):
1. Run `check`.
2. Review for contradictions, stale facts (deadlines that have passed), orphans, entities appearing in several documents without a page, and uncited claims.
3. Report findings, apply only the fixes the user approves, log the pass, and run `check` again.

## 3. Python checker: `src/second_brain/wiki.py`

No LLM calls, no network, no new dependencies (YAML uses the existing `pyyaml`).

**`python -m second_brain.wiki check [--wiki PATH] [--docs PATH]`**: read-only validation. Exit code 0 with no errors, 1 with errors, 2 if the wiki folder doesn't exist.

Errors:
- **PII:** a page's text changes when run through `Redactor(settings.redact)`, or contains a canary from `evals/golden.yaml` (when that file is present).
- **Broken link:** a `[[link]]` (after stripping `|alias` and `#heading`) has no matching page.
- **Frontmatter:** missing, unparseable YAML, `type` not in the allowed set, `sources` empty or not a list, `updated` not an ISO date, or a source page without `indexed_at`.
- **Unknown source:** a `sources` entry or inline citation path is not a file under the docs folder.
- **Log:** a `log.md` heading doesn't match `## [YYYY-MM-DD] <ingest|file|lint> | <subject>`.

Warnings (printed, don't fail): orphan pages (no inbound links from any page other than `index.md` and `log.md`, which list everything), and pages with no inline citations.

Malformed files are reported as issues; the checker never crashes on bad content.

**`python -m second_brain.wiki status [--wiki PATH]`**: goes through the `SecondBrain` facade (`list_documents()`), and prints documents with no source page (`new`) and documents whose current `ingested_at` differs from the source page's `indexed_at` (`changed`). A source page is matched to its document by the first entry of its `sources` frontmatter. After `ingest --rebuild` every document reports `changed`, which is correct: the index was rebuilt.

**Code shape:** pure functions over a parsed `Page` frozen dataclass (path, name, frontmatter, body, links, citations) returning a list of `Issue` frozen dataclasses (severity, page, message). The CLI is a thin layer on top. Output goes to stdout (this is a CLI, not the MCP server).

**Config:** `Settings` gains `wiki_dir: Path` from `SECOND_BRAIN_WIKI`, default `wiki`. Added to `.env.example` and the README configuration table.

## 4. CI, tests, docs

- **CI:** the `tests` job adds a step `python -m second_brain.wiki check --wiki wiki --docs data/docs`. No model download needed.
- **Tests (written first):** `tests/test_wiki.py` builds throwaway wikis in `tmp_path`, each with one problem, and asserts it is caught: SSN, Luhn-valid card, canary, broken link, alias and heading links resolving, bad YAML, bad `type`, made-up source, malformed log entry, orphan warning, and `status` reporting new and changed documents (using `HashEmbedder` settings like the other tests). Plus a clean wiki that passes.
- **The committed example:** after the code lands, Claude Code runs the ingest workflow over the 7 synthetic documents, `check` passes, and the result is committed as `wiki/`.
- **Git:** add `.obsidian/` to `.gitignore`.
- **Docs:** `docs/wiki-schema.md` (rules and workflows), a pointer section in `CLAUDE.md`, and a README section on opening a wiki in Obsidian and the three workflows.

## Out of scope for v1

- MCP tools for reading the wiki (a read-only `search_wiki` could follow).
- Any scheduled or automatic run.
- A Python pipeline that calls the Anthropic API.
- Embedding wiki pages into the vector index.

## Success criteria

- `pytest -q` passes, including the new wiki tests.
- `python -m second_brain.wiki check` passes on the committed `wiki/`, and CI runs it.
- The committed wiki has a source page for each of the 7 documents, plus entity and topic pages, with no broken links and no PII.
- Opening `wiki/` in Obsidian shows a connected graph.
- Existing retrieval evals still print `RESULT: PASS` at 0.56.
