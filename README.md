# Second Brain
![CI](https://github.com/realserted/second-brain/actions/workflows/ci.yml/badge.svg)

Local RAG over your personal paperwork (leases, insurance, contracts, warranties, notes), exposed to Claude as an **MCP server**. Sensitive numbers are redacted before anything is indexed, and retrieval quality is guarded by an **eval suite that runs in CI**.

```
data/docs/ ──► load (md, txt, pdf) ──► redact PII ──► chunk ──► embed locally ──► SQLite + sqlite-vec
                                                                                       │
Claude Desktop / Claude Code ◄──── MCP (stdio) ◄──── search_documents / list / get ◄───┘
```

## Design decisions

| Decision | Why |
|---|---|
| **Local embeddings** (`bge-small-en-v1.5` via fastembed, ONNX) | Document text never leaves the machine to build the index. Only the passages Claude retrieves for a specific question are sent to the model. |
| **Redact at ingest, not at query time** | A value that never enters the index can't leak through any path: search results, `get_document`, logs, or a future tool. SSNs, Luhn-valid card numbers, and labelled bank/routing numbers are on by default. |
| **Similarity floor (abstention)** | Below `SECOND_BRAIN_MIN_SCORE` the server returns `found: false`, so Claude says "not in your documents" instead of answering from general knowledge. |
| **SQLite + sqlite-vec** | One file, no server, easy to inspect. Re-ingest is incremental (SHA-256 per file) and prunes deleted files. The index refuses to mix vectors from different embedding models. |
| **Read-only MCP tools** | Every tool is annotated `read_only_hint=True`. The agent can't modify anything. |
| **Two eval layers** | Deterministic retrieval evals gate every PR for free. LLM-as-judge evals catch what retrieval metrics can't (a plausible chunk that doesn't actually answer the question) and run on demand. |

## Quick start

Requires Python 3.11+.

```bash
git clone <your-repo> second-brain && cd second-brain
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

python -m second_brain.ingest          # first run downloads the ~70 MB embedding model
pytest -q                              # 33 tests
python evals/run_evals.py --calibrate  # see the score distribution
python evals/run_evals.py              # gated retrieval evals
```

To index your own documents, point `SECOND_BRAIN_DOCS` at a folder **outside the repo** (or use `data/private/`, which is git-ignored). Only the synthetic documents in `data/docs/` belong in version control.

## Connect it to Claude

Claude launches the server as a subprocess, so its working directory isn't this repo. **Use absolute paths** for the Python executable, the database, and the docs folder.

### Claude Code

The quickest route is a project-scoped config: copy [`.mcp.example.json`](.mcp.example.json) to `.mcp.json` and replace the `/ABSOLUTE/PATH/TO/second-brain` placeholders (on Windows, `.venv\Scripts\python.exe`). `.mcp.json` is git-ignored because it holds machine-specific paths. Or register it with the CLI:

`add-json` avoids an argument-parsing quirk with `--env` on `claude mcp add`:

```bash
claude mcp add-json second-brain '{
  "type": "stdio",
  "command": "/abs/path/second-brain/.venv/bin/python",
  "args": ["-m", "second_brain.server"],
  "env": {
    "SECOND_BRAIN_DB": "/abs/path/second-brain/data/second_brain.db",
    "SECOND_BRAIN_DOCS": "/abs/path/second-brain/data/docs"
  }
}'
claude mcp list
```

On Windows the command is `C:\\path\\to\\second-brain\\.venv\\Scripts\\python.exe` (double backslashes inside JSON).

### Claude Desktop

Add to `claude_desktop_config.json` (on Windows: `%APPDATA%\Claude\claude_desktop_config.json`), then restart the app:

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "C:\\path\\to\\second-brain\\.venv\\Scripts\\python.exe",
      "args": ["-m", "second_brain.server"],
      "env": {
        "SECOND_BRAIN_DB": "C:\\path\\to\\second-brain\\data\\second_brain.db",
        "SECOND_BRAIN_DOCS": "C:\\path\\to\\second-brain\\data\\docs"
      }
    }
  }
}
```

Run `python -m second_brain.ingest` with the same `SECOND_BRAIN_DB` before connecting, then ask things like *"When does my lease end?"* or *"What's my collision deductible?"*.

### Tools

| Tool | Purpose |
|---|---|
| `search_documents(query, top_k=5)` | Semantic search. Returns passages with `source`, `title`, `score`, `text`, and `found: false` when nothing clears the floor. |
| `list_documents()` | Every indexed file with title and chunk count. |
| `get_document(source)` | Full redacted text of one file. |

## LLM wiki

Inspired by [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): Claude Code turns your documents into linked markdown notes (sources, people and companies, topics, filed answers) that get better as you use them. Open the folder as a vault in [Obsidian](https://obsidian.md) to see the graph.

- **Update the wiki:** ask Claude Code "update the wiki". It runs `python -m second_brain.wiki status`, reads the redacted text over MCP, and writes the pages.
- **Ask questions:** Claude checks the wiki first, confirms against the index, and offers to file new answers (it asks before writing).
- **Lint:** "lint the wiki" finds contradictions, expired dates, orphans and missing pages.

`python -m second_brain.wiki check` validates any wiki with no LLM involved: no PII, no broken links, valid frontmatter, real citations. CI runs it on `wiki/`, the example built from `data/docs`. For your own documents set `SECOND_BRAIN_WIKI` to a folder outside the repo. Rules: [docs/wiki-schema.md](docs/wiki-schema.md).

## Evals

### Retrieval evals (`evals/run_evals.py`, every PR)

Driven by `evals/golden.yaml`. Each run indexes `data/docs` into a throwaway database and checks:

| Metric | Meaning | Threshold |
|---|---|---|
| `hit_rate` | Expected document is in the top-k | 90% |
| `fact_recall` | A returned chunk from that document contains the expected fact | 85% |
| `abstention` | Off-topic questions (dentist appointment, World Cup) return nothing | 75% |
| `pii_leaks` | Planted canary values found in the index or any result | must be 0 |

Results are written to the GitHub Actions job summary. A prompt, chunking, model, or threshold change that drops any metric below its threshold fails the build.

### Judge evals (`evals/judge.py`, on demand)

For each case in `judge_cases`: retrieve → answer with Claude → grade with a second, cheaper model for **groundedness** (every claim is supported by the retrieved context) and **correctness** (answers when it should, declines when it should). The key case is *"What is my health insurance deductible?"*: retrieval returns the auto policy's deductible, and the answer must still say it isn't in the documents.

Run locally with `pip install -e ".[judge]"` and `ANTHROPIC_API_KEY` set, or in CI via **Actions → CI → Run workflow → judge**. Add `ANTHROPIC_API_KEY` as a repository secret first.

### Calibrating the similarity floor

`SECOND_BRAIN_MIN_SCORE` depends on the embedding model. The `--calibrate` flag prints the top similarity for every golden case and suggests the midpoint between the weakest answerable case and the strongest off-topic one. The default of `0.56` is calibrated for `bge-small-en-v1.5` on the synthetic set. The scores aren't perfectly separable: `pii-ssn` scores below two off-topic questions because the SSN is redacted at ingest, so the floor favours abstention and that case is a known miss (the judge eval's `j-ssn` case covers it). **Re-run `--calibrate` when you change the model or documents, and update `ci.yml` and your MCP config to match.**

## Configuration

All optional, read from environment variables.

| Variable | Default | |
|---|---|---|
| `SECOND_BRAIN_DB` | `data/second_brain.db` | Index file |
| `SECOND_BRAIN_DOCS` | `data/docs` | Folder to index |
| `SECOND_BRAIN_WIKI` | `wiki` | LLM wiki folder |
| `SECOND_BRAIN_EMBEDDER` | `fastembed` | `hash` is an offline lexical fallback used by tests |
| `SECOND_BRAIN_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Any fastembed text model |
| `SECOND_BRAIN_CHUNK_SIZE` / `_OVERLAP` | `900` / `150` | Characters |
| `SECOND_BRAIN_TOP_K` | `5` | Default results per search |
| `SECOND_BRAIN_MIN_SCORE` | `0.56` | Abstention floor (cosine similarity) |
| `SECOND_BRAIN_REDACT` | `ssn,credit_card,bank_account,routing_number` | Also available: `email`, `phone` |

Changing the embedding model or the redaction rules requires `python -m second_brain.ingest --rebuild`.

## Project layout

```
src/second_brain/
  config.py       settings from environment
  loaders.py      md / txt / pdf → text
  redaction.py    PII rules (regex + Luhn), applied at ingest
  chunking.py     paragraph-aware chunks with overlap
  embeddings.py   Embedder protocol: fastembed (real) and hash (tests)
  store.py        SQLite + sqlite-vec; embedder pinning; incremental upsert/prune
  brain.py        SecondBrain facade used by CLI, server, and evals
  ingest.py       CLI
  server.py       MCP server (mcp SDK 2.x MCPServer, stdio)
  wiki.py         wiki checker and status (no LLM)
evals/
  golden.yaml     cases, PII canaries, thresholds
  run_evals.py    deterministic retrieval evals (CI gate)
  judge.py        end-to-end LLM-as-judge evals
tests/            pytest suite, runs offline with the hash embedder
data/docs/        synthetic documents only
wiki/             example LLM wiki built from data/docs
```

## Known limitations

- Scanned PDFs have no text layer; they need OCR before ingest.
- Redaction is pattern-based. It catches structured identifiers, not free-text sensitive content like a medical history paragraph.
- Re-ingest is keyed on the raw file hash, so changing redaction settings needs `--rebuild`.
- The MCP SDK 2.x renamed `FastMCP` to `MCPServer`. Tutorials written for 1.x won't run as-is against this project.
