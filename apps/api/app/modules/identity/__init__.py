"""Identity subsystem — the agent's representation of itself.

Higher-Order theories of consciousness (Rosenthal, Lau) hold that a system
becomes conscious of a state when it forms a representation of that state.
The Identity module is exactly that: an explicit, queryable, periodically-
recompiled snapshot of what the agent currently believes, doubts, and
attends to. It is *not* a marketing widget — the solver reads from it,
the questioner consults it, the journal narrates it.
"""
from app.modules.identity.engine import (
    current_identity,
    narrative_summary,
    update_identity,
)

__all__ = ["update_identity", "current_identity", "narrative_summary"]
