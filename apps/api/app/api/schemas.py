from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: str
    title: str
    author: Optional[str] = None
    filename: str
    page_count: int
    subject_area: Optional[str] = None
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
    parent_id: Optional[str] = None
    document_id: Optional[str] = None
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
    target_id: Optional[str] = None
    status: str
    progress: float
    detail: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CycleRequest(BaseModel):
    question_budget: int = 8


class AnalyzeRequest(BaseModel):
    document_id: str
    n_questions: Optional[int] = None
