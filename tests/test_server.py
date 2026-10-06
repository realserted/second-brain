"""Exercise the MCP tool functions against a real (hash-embedded) index."""
import shutil

import pytest

from conftest import DOCS


@pytest.fixture
def server(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    shutil.copytree(DOCS, docs)
    monkeypatch.setenv("SECOND_BRAIN_DB", str(tmp_path / "server.db"))
    monkeypatch.setenv("SECOND_BRAIN_DOCS", str(docs))
    monkeypatch.setenv("SECOND_BRAIN_EMBEDDER", "hash")
    monkeypatch.setenv("SECOND_BRAIN_MIN_SCORE", "0.12")
    monkeypatch.setenv("SECOND_BRAIN_CHUNK_SIZE", "300")
    monkeypatch.setenv("SECOND_BRAIN_CHUNK_OVERLAP", "50")

    from second_brain import server as srv

    srv.brain.cache_clear()
    srv.brain().ingest()
    yield srv
    srv.brain().close()
    srv.brain.cache_clear()


def test_search_tool_returns_cited_results(server):
    out = server.search_documents("monthly rent")
    assert out["found"]
    assert out["results"][0]["source"] == "leases/apartment-lease.md"
    assert {"source", "title", "score", "text"} <= out["results"][0].keys()


def test_search_tool_signals_nothing_found(server):
    out = server.search_documents("who won the world cup")
    assert out == {"query": "who won the world cup", "found": False, "results": []}


def test_top_k_is_clamped(server):
    assert len(server.search_documents("fee", top_k=999)["results"]) <= 20


def test_list_and_get_document(server):
    sources = [d["source"] for d in server.list_documents()["documents"]]
    assert "contracts/freelance-msa.md" in sources
    doc = server.get_document("contracts/freelance-msa.md")
    assert "Net 30" in doc["content"]


def test_get_unknown_document(server):
    assert "error" in server.get_document("nope.md")


def test_tools_are_registered_read_only(server):
    import asyncio

    tools = asyncio.run(server.server.list_tools())
    names = {t.name for t in tools}
    assert names == {"search_documents", "list_documents", "get_document"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_tools_work_through_the_mcp_dispatcher(server):
    """The SDK runs sync tools on worker threads; calling the functions directly
    would miss threading bugs, so go through call_tool like a real client."""
    import asyncio

    async def calls():
        for query in ["monthly rent", "collision deductible", "gym annual fee"]:
            await server.server.call_tool("search_documents", {"query": query})
        await server.server.call_tool("list_documents", {})

    asyncio.run(calls())
