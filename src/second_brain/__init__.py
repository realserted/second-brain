"""Second Brain: local RAG over personal documents, exposed as an MCP server."""
from .brain import IngestReport, SecondBrain
from .config import Settings

__all__ = ["IngestReport", "SecondBrain", "Settings"]
