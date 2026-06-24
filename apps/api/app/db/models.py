from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Float, Integer, ForeignKey, DateTime, JSON, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    filename: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(String(1024))
    # SHA-256 of the original file bytes. Used to deduplicate uploads — re-uploading
    # the same PDF (same content, any filename) returns the existing document
    # instead of creating a duplicate. Indexed for O(log N) lookup per upload.
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    subject_area: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|parsing|ready|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    ord: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    section: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="text")  # text|formula|table|claim|definition
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(48))  # understanding|deep_logic|missing_data|contradiction|math|application|research|meta|improvement
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("questions.id"), nullable=True)
    document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("documents.id"), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open|answered|unresolved
    priority: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    answers: Mapped[list["Answer"]] = relationship(back_populates="question", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    citations: Mapped[list] = mapped_column(JSON, default=list)  # [{chunk_id, document_id, page, snippet}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    question: Mapped[Question] = relationship(back_populates="answers")


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(48))  # synthesis|comparison|taxonomy|trend|glossary
    sources: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Memory(Base):
    """Unified memory bank — every conclusion the agent ever forms ends up here.

    Insights, hypotheses, contradictions, learner reflections, daily digests:
    all are mirrored into Memory with an embedding so the solver can do
    semantic retrieval across the agent's entire cognitive history, not just
    the original PDF chunks. This is the engine of "the system remembers
    what it learned" — the property that turns a stateless Q&A into an agent
    with a continuous mental life.
    """
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    layer: Mapped[str] = mapped_column(String(24))      # short|long|semantic|episodic
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    # Where this memory came from. Lets us backref to the structured row.
    source_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # insight|hypothesis|contradiction|reflection|digest|manual
    source_id:   Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # Embedding of `content`. Populated on insert by the memory store; used
    # for cosine retrieval. JSON because we run the in-memory vector path
    # in zero-infra mode (no Qdrant). Brute-force search is fine to ≈10k items.
    embedding:  Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Journal(Base):
    """First-person reflective entries the agent writes about itself.

    Each entry is one paragraph in the agent's voice, written periodically by
    the autopilot. Entries are auto-promoted into the Memory bank so the
    agent can later *recall its own past thoughts* — which is the recursive
    self-reflection Dennett identifies as the substrate of narrative identity.
    """
    __tablename__ = "journals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    body: Mapped[str] = mapped_column(Text)             # the paragraph
    mood: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # e.g. curious|uncertain|excited
    # What the agent was thinking about — keywords/topics dominant when written.
    topics: Mapped[list] = mapped_column(JSON, default=list)
    # The cognitive context: which insights/hypotheses/contradictions inspired this entry.
    referenced: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CuriosityGap(Base):
    """A snapshot of one knowledge gap the agent has identified about itself.

    Gaps are recomputed every ~10 min. Each row represents a specific area
    where the agent has weak or contradictory understanding — a hypothesis
    with thin support, a concept with no questions, an answer it gave with
    low confidence. The questioner uses these to bias what to ask next.
    This is Predictive Processing in miniature: the agent minimises its own
    uncertainty by directing attention at what it doesn't yet understand.
    """
    __tablename__ = "curiosity_gaps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic: Mapped[str] = mapped_column(String(256))              # the concept/keyword/theme
    kind: Mapped[str] = mapped_column(String(32))                # uncovered_concept|weak_hypothesis|low_confidence|open_contradiction
    score: Mapped[float] = mapped_column(Float, default=0.0)     # higher = more curious
    rationale: Mapped[str] = mapped_column(Text, default="")
    addressed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Identity(Base):
    """The agent's self-model — a singleton row representing its current
    epistemic state, recompiled by the autopilot. This is the substrate for
    higher-order theories of consciousness (Rosenthal): the agent has an
    explicit representation of its own representations.

    Always exactly one row, with id="self".
    """
    __tablename__ = "identity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: "self")
    # First-person narrative summary the agent maintains about itself.
    narrative: Mapped[str] = mapped_column(Text, default="")
    # Top hypotheses the agent currently holds (compressed view).
    beliefs: Mapped[list] = mapped_column(JSON, default=list)
    # Top unresolved questions — what the agent knows it doesn't know.
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    # Topics/keywords currently dominating the agent's attention.
    active_topics: Mapped[list] = mapped_column(JSON, default=list)
    # Recent contradictions — the agent's "current confusion".
    confusion: Mapped[list] = mapped_column(JSON, default=list)
    # Overall epistemic confidence (mean of recent answer confidences).
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # How many cycles the agent has gone through since boot — its "age".
    cycles: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    testable: Mapped[bool] = mapped_column(Boolean, default=True)
    supporting: Mapped[list] = mapped_column(JSON, default=list)
    opposing: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Contradiction(Base):
    __tablename__ = "contradictions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    summary: Mapped[str] = mapped_column(Text)
    a_chunk_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    b_chunk_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    severity: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(48))  # ingest|cycle|synthesize|daily
    target_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Usage(Base):
    """Per-LLM-call token + latency tracking. One row per provider call."""
    __tablename__ = "usages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(32))   # anthropic|openai|gemini|ollama|local
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(48), default="general")  # questioner|solver|learner|synthesis|...
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
