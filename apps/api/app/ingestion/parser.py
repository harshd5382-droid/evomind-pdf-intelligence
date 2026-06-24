"""PDF parsing with priority fallback: LlamaParse → PyMuPDF → pdfplumber.

Each parser returns a list of page dicts:
    {"page": int (1-based), "text": str}
plus a top-level metadata dict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from app.core.config import get_settings


@dataclass
class ParsedDocument:
    title: str = ""
    author: str = ""
    page_count: int = 0
    pages: list[dict] = field(default_factory=list)  # [{page:int, text:str}]
    used_parser: str = ""


def _try_llamaparse(path: Path) -> ParsedDocument | None:
    s = get_settings()
    if not s.llamaparse_api_key:
        return None
    try:
        from llama_parse import LlamaParse  # type: ignore
        parser = LlamaParse(api_key=s.llamaparse_api_key, result_type="text")
        docs = parser.load_data(str(path))
        pages: list[dict] = []
        for i, d in enumerate(docs, start=1):
            pages.append({"page": i, "text": d.text or ""})
        return ParsedDocument(
            title=path.stem,
            page_count=len(pages),
            pages=pages,
            used_parser="llamaparse",
        )
    except Exception as e:
        logger.warning("LlamaParse failed: {}", e)
        return None


def _try_pymupdf(path: Path) -> ParsedDocument | None:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        meta = doc.metadata or {}
        pages: list[dict] = []
        for i, page in enumerate(doc, start=1):
            txt = page.get_text("text") or ""
            pages.append({"page": i, "text": txt})
        return ParsedDocument(
            title=meta.get("title") or path.stem,
            author=meta.get("author") or "",
            page_count=len(pages),
            pages=pages,
            used_parser="pymupdf",
        )
    except Exception as e:
        logger.warning("PyMuPDF failed: {}", e)
        return None


def _try_pdfplumber(path: Path) -> ParsedDocument | None:
    try:
        import pdfplumber
        pages: list[dict] = []
        title = path.stem
        author = ""
        with pdfplumber.open(str(path)) as pdf:
            md = pdf.metadata or {}
            title = md.get("Title") or title
            author = md.get("Author") or ""
            for i, page in enumerate(pdf.pages, start=1):
                pages.append({"page": i, "text": page.extract_text() or ""})
        return ParsedDocument(
            title=title,
            author=author,
            page_count=len(pages),
            pages=pages,
            used_parser="pdfplumber",
        )
    except Exception as e:
        logger.warning("pdfplumber failed: {}", e)
        return None


_PARSERS = {
    "llamaparse": _try_llamaparse,
    "pymupdf": _try_pymupdf,
    "pdfplumber": _try_pdfplumber,
}


def parse_pdf(path: str | Path) -> ParsedDocument:
    p = Path(path)
    s = get_settings()
    order = [name.strip() for name in s.parser_priority.split(",") if name.strip()]
    for name in order:
        fn = _PARSERS.get(name)
        if fn is None:
            continue
        result = fn(p)
        if result is not None and result.pages:
            logger.info("Parsed {} with {} ({} pages)", p.name, name, result.page_count)
            return result
    raise RuntimeError(f"No parser was able to read {p}")
