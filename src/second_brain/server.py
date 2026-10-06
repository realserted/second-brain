"""MCP server exposing the Second Brain to Claude (Desktop, Code, or any MCP client).

Runs over stdio. Never print to stdout here: stdout is the protocol channel,
so all diagnostics go to stderr via logging.
"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .brain import SecondBrain

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

server = MCPServer(
    name="second-brain",
    instructions=(
        "Search the user's personal documents (leases, insurance, contracts, "
        "memberships, notes). Always call search_documents before answering questions "
        "about the user's own paperwork, cite the `source` of every fact you use, and "
        "say plainly when the documents don't contain the answer. Values shown as "
        "[REDACTED_*] were removed at ingest and must not be guessed."
    ),
)


@lru_cache(maxsize=1)
def brain() -> SecondBrain:
    return SecondBrain.from_env()


@server.tool(annotations=READ_ONLY)
def search_documents(query: str, top_k: int = 5) -> dict:
    """Semantic search over the user's documents.

    Returns the most relevant passages with their source file and a similarity
    score. An empty result means nothing relevant was found; do not answer
    from general knowledge in that case.
    """
    hits = brain().search(query, top_k=max(1, min(top_k, 20)))
    return {
        "query": query,
        "found": bool(hits),
        "results": [
            {"source": h.source, "title": h.title, "score": h.score, "text": h.text} for h in hits
        ],
    }


@server.tool(annotations=READ_ONLY)
def list_documents() -> dict:
    """List every indexed document with its title and chunk count."""
    return {"documents": brain().list_documents()}


@server.tool(annotations=READ_ONLY)
def get_document(source: str) -> dict:
    """Return the full (redacted) text of one document by its `source` path."""
    doc = brain().get_document(source)
    return doc or {"error": f"No document with source '{source}'. Call list_documents first."}


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
