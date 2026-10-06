# CLAUDE.md

Second Brain: local RAG over personal documents, served to Claude over MCP (stdio). PII is redacted at ingest; retrieval quality is gated by evals in CI.

## Commands
- Install: `pip install -e ".[dev]"` (add `[judge]` for LLM-as-judge evals)
- Tests: `pytest -q` (offline, uses the hash embedder)
- Index: `python -m second_brain.ingest` (`--rebuild` after changing the embedding model or redaction rules)
- Retrieval evals: `python evals/run_evals.py` (`--calibrate` prints score distribution)
- Judge evals: `python evals/judge.py` (needs ANTHROPIC_API_KEY, costs money, never run automatically)
- Server: `python -m second_brain.server`
- Wiki: `python -m second_brain.wiki check` (no LLM, gated in CI) and `python -m second_brain.wiki status`

## Architecture
- `brain.py`: `SecondBrain` facade. The CLI, MCP server and evals all go through it. Don't bypass it.
- `store.py`: SQLite + sqlite-vec. Pins the embedder name and dimension in a `meta` table and refuses to mix models.
- `redaction.py`: regex rules plus a Luhn check. Rule order matters: labelled numbers run before the generic card scan.
- `embeddings.py`: `Embedder` protocol. `FastEmbedEmbedder` is the real model; `HashEmbedder` is a lexical stand-in for tests only.
- `server.py`: MCP tools, all annotated read-only.

## Invariants (don't break these)
- Redaction happens at ingest, before chunking and embedding. Never move it to query time.
- All MCP tools stay read-only. Adding a write tool needs explicit approval.
- Never print to stdout in `server.py`; stdout is the MCP protocol channel. Log to stderr.
- The MCP SDK runs sync tools on worker threads. Every `VectorStore` method that touches the connection must keep the `@_locked` decorator.
- This uses `mcp` 2.x: `from mcp.server.mcpserver import MCPServer`. `FastMCP` from 1.x tutorials does not exist here.
- `SECOND_BRAIN_MIN_SCORE` is calibrated for bge-small-en-v1.5 at 0.56. Changing the model means recalibrating.

## Evals
- Never lower a threshold or edit an expected answer in `evals/golden.yaml` to make CI pass. Fix the cause, or ask.
- Adding cases is encouraged, especially out-of-scope questions and PII probes.
- `pii_leaks` must always be 0.

## Testing conventions
- Tests use `HashEmbedder` with chunk_size=300, overlap=50, min_score=0.12. Those values are tuned for lexical matching, not the real model.
- Server tests must go through `server.server.call_tool(...)` as well as direct calls, so threading bugs surface.

## Data
- `data/docs/` holds synthetic documents only, with planted fake PII used as eval canaries. Never add real personal documents to the repo; point `SECOND_BRAIN_DOCS` at a folder outside it.

## Wiki
- The LLM wiki is maintained by Claude Code following `docs/wiki-schema.md`. Read it before touching any wiki.
- Build wiki pages only from redacted text (MCP tools or `SecondBrain.get_document`), never from files under the docs folder.
- Ask before filing an answer into the wiki.
- `wiki/` is the committed example built from `data/docs`. Personal wikis live outside the repo via `SECOND_BRAIN_WIKI`.

## Style
- Python 3.11+, type hints, frozen dataclasses for config, small modules, no new dependencies without a reason.
