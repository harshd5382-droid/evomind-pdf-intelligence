"""Memory subsystem — the agent's continuous mental life.

Every conclusion the agent forms (insight, hypothesis, contradiction,
reflection, daily digest) is mirrored into the Memory table with an
embedding. Retrieval is semantic (cosine over embeddings), not just
recency-based, so the solver can pull what's actually relevant to a new
question — including conclusions formed days ago about other documents.

This is what turns a stateless Q&A system into an agent with persistent
identity over time.
"""
from app.modules.memory.store import (
    add_memory,
    search_memories,
    backfill_embeddings,
    memory_stats,
)

__all__ = ["add_memory", "search_memories", "backfill_embeddings", "memory_stats"]
