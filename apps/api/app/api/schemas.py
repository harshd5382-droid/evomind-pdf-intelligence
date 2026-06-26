from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    title: str
    author: str | None = None
    filename: str
    page_count: int
    subject_area: str | None = None
    importance: float
    keywords: list[str] = []
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class QuestionOut(BaseModel):
    id: str
    text: str
    category: str
    parent_id: str | None = None
    document_id: str | None = None
    depth: int
    status: str
    priority: float
    created_at: datetime

    class Config:
        from_attributes = True


class AnswerOut(BaseModel):
    id: str
    question_id: str
    text: str
    reasoning: str
    confidence: float
    citations: list[Any] = []
    created_at: datetime

    class Config:
        from_attributes = True


class InsightOut(BaseModel):
    id: str
    title: str
    body: str
    kind: str
    sources: list[Any] = []
    created_at: datetime

    class Config:
        from_attributes = True


class MemoryOut(BaseModel):
    id: str
    layer: str
    content: str
    tags: list[str] = []
    importance: float
    created_at: datetime

    class Config:
        from_attributes = True


class HypothesisOut(BaseModel):
    id: str
    statement: str
    rationale: str
    testable: bool
    supporting: list[Any] = []
    opposing: list[Any] = []
    created_at: datetime

    class Config:
        from_attributes = True


class JobOut(BaseModel):
    id: str
    kind: str
    target_id: str | None = None
    status: str
    progress: float
    detail: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class ChatReply(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    confidence: float
    citations: list[Any] = []


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list[Any] = []
    confidence: float
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FeedbackRequest(BaseModel):
    target_kind: str = Field(pattern="^(answer|chat_message)$")
    target_id: str = Field(min_length=1)
    rating: int = Field(ge=-1, le=1)  # +1 up, -1 down (0 = clear)
    note: str = Field(default="", max_length=2000)


class EvalRequest(BaseModel):
    sample_size: int = Field(default=20, ge=1, le=100)


class ConfigUpdate(BaseModel):
    """Runtime-overridable tuning knobs. All optional; only provided fields
    change. Excludes provider/embedding settings (changing those at runtime
    would corrupt the vector index)."""
    questions_per_doc: int | None = Field(default=None, ge=1, le=50)
    recursion_depth: int | None = Field(default=None, ge=0, le=6)
    autonomy_level: str | None = Field(default=None, pattern="^(cautious|balanced|aggressive)$")
    creativity: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class CycleRequest(BaseModel):
    question_budget: int = Field(default=8, ge=1, le=100)


class AnalyzeRequest(BaseModel):
    document_id: str
    n_questions: int | None = Field(default=None, ge=1, le=50)
