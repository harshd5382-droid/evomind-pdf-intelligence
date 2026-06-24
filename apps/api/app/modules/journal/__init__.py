"""Journal — the agent's first-person reflective writing.

A continuous stream of paragraphs in the agent's voice, written periodically.
Each entry is grounded in what changed since the last entry: new insights,
new contradictions, surprising answers. Entries auto-promote into Memory so
the agent can later recall *its own thoughts about its own learning*. This
recursion is what Dennett calls the narrative self.
"""
from app.modules.journal.engine import write_entry, recent_entries

__all__ = ["write_entry", "recent_entries"]
