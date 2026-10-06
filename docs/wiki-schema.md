# Wiki schema

The rules Claude Code follows when it maintains a Second Brain wiki. The wiki is
a folder of linked markdown pages, viewable as a graph in Obsidian. It is built
from **redacted** text only and checked by `python -m second_brain.wiki check`.

Which wiki: `SECOND_BRAIN_WIKI` (default `wiki/`, the committed example built from
`data/docs`). A personal wiki lives outside the repo and never goes into git.

## Hard rules

- Read document content only through the MCP tools `get_document`,
  `search_documents` and `list_documents` (or `SecondBrain.get_document` in
  Python). Never open files under the docs folder directly: they hold unredacted PII.
- Never write a value that was redacted. Keep tags like `[REDACTED_SSN]` as they are.
- Every fact cites its document inline as a docs-relative path in parentheses:
  `Rent is $1,450/month (leases/apartment-lease.md)`.
- Don't invent facts. If documents disagree, say so on the page and cite both.
- Run `python -m second_brain.wiki check` after every change. Finish only when it
  reports 0 errors. Besides the redaction rules it searches every wiki file for the
  values ingest removed from your documents, in any spacing or punctuation; those
  values stay in memory and are never printed.
- Images can be embedded with `![[file.png]]`. Keep other binary files (PDFs, office
  documents) out of the wiki: `check` can't scan them for PII and reports them as errors.

## Layout

    index.md      every page, grouped by type, one line each: [[name]] - summary
    log.md        append-only history (format below)
    sources/      one page per document
    entities/     people, organisations, things appearing in 2+ documents (or on request)
    topics/       cross-cutting views, e.g. deadlines-and-renewals, monthly-costs
    answers/      filed answers, named YYYY-MM-DD-<slug>.md

File names are lowercase-hyphenated and unique across the wiki. Link with
`[[name]]`, `[[name|text]]` or `[[name#heading]]`.

## Page format

    ---
    type: source            # source | entity | topic | answer
    sources: [leases/apartment-lease.md]
    updated: 2026-10-06
    indexed_at: '2026-10-06T03:36:51.662657+00:00'   # source pages only
    ---
    # Residential Lease Agreement

    One-paragraph summary.

    ## Key facts
    - Lease ends December 31, 2026 (leases/apartment-lease.md)

    ## Related
    - [[jordan-reyes]], [[deadlines-and-renewals]]

- `sources`: every document the page draws on. For a source page, its own document first.
- `indexed_at`: copy the document's `ingested_at` from `list_documents` exactly.
- `index.md` and `log.md` need no frontmatter.

## log.md

    ## [2026-10-06] ingest | Residential Lease Agreement
    - created [[apartment-lease]], [[jordan-reyes]]
    - updated [[deadlines-and-renewals]]

Operations: `ingest`, `file`, `lint`. Append only, newest at the bottom.

## Workflows

### Ingest ("update the wiki")
1. Run `python -m second_brain.wiki status`. Work only on documents it lists.
2. For each: `get_document(source)` for the redacted text, and `list_documents`
   for its `ingested_at`.
3. Write or update `sources/<name>.md`. Create or extend entity pages for things
   that appear in 2+ documents, and update topic pages (deadlines, costs, people).
4. Update `index.md`, append to `log.md`, run `check`, fix every error.
5. Tell the user which pages were created and changed.

### Ask, then file (any question about the documents)
1. Read the wiki first (`index.md`, then linked pages). Confirm key facts with
   `search_documents`: the index is the source of truth.
2. Answer with citations.
3. If the answer is a new synthesis (combines documents, or computes something),
   ask: "Want me to file this in the wiki?" Write nothing without a yes.
4. On yes: write `answers/YYYY-MM-DD-<slug>.md` (type `answer`) linking the
   entities involved, link it from a relevant topic or entity page, update
   `index.md` and `log.md`, run `check`.

### Lint ("lint the wiki")
1. Run `check`.
2. Review for: contradictions between pages, stale facts (dates before today, such
   as expired policies), orphans, entities in 2+ documents without a page,
   uncited claims, pages whose documents changed (`status`).
3. Report findings. Apply only the fixes the user approves. Log the pass.
   Run `check` again.
