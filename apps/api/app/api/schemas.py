from datetime import datetime
from typing import Any

from pydantic import BaseModel


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
    message: str
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


class CycleRequest(BaseModel):
    question_budget: int = 8


class AnalyzeRequest(BaseModel):
    document_id: str
    n_questions: int | None = None
