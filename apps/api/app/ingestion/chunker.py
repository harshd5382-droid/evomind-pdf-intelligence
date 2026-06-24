from __future__ import annotations

import re
from dataclasses import dataclass


_HEADING_RE = re.compile(r"^(?:[A-Z][A-Z0-9 \-]{3,}|\d+(?:\.\d+)*\s+[A-Z].{0,80})$")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


@dataclass
class ChunkSpec:
    ord: int
    page: int
    text: str
    section: str | None
    kind: str  # text|formula|table|definition|claim


def _detect_section(line: str, current: str | None) -> str | None:
    s = line.strip()
    if 4 <= len(s) <= 90 and _HEADING_RE.match(s):
        return s
    return current


def _is_formula_line(s: str) -> bool:
    if "=" in s and len(s) < 200 and re.search(r"[A-Za-z]", s) and not s.endswith("."):
        # Heuristic: has =, contains a letter, not too long, not a sentence
        non_alnum = sum(1 for c in s if not c.isalnum() and not c.isspace())
        return non_alnum >= 2
    return False


def chunk_pages(pages: list[dict], target_chars: int = 1100, overlap: int = 150) -> list[ChunkSpec]:
    """Sliding window chunking that preserves page numbers and detected section headings.

    Also flags isolated formula lines as their own chunks so they're queryable on their own.
    """
    chunks: list[ChunkSpec] = []
    ord_i = 0
    section: str | None = None

    for page_data in pages:
        page_no = page_data["page"]
        raw = (page_data.get("text") or "").strip()
        if not raw:
            continue

        # First pass: pull standalone formula lines as their own chunks
        lines = raw.split("\n")
        normal_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            section = _detect_section(stripped, section)
            if _is_formula_line(stripped):
                chunks.append(ChunkSpec(
                    ord=ord_i, page=page_no, text=stripped,
                    section=section, kind="formula",
                ))
                ord_i += 1
            else:
                normal_lines.append(line)

        body = "\n".join(normal_lines).strip()
        if not body:
            continue

        sentences = _SENT_SPLIT.split(body)
        buf = ""
        for sent in sentences:
            if not sent:
                continue
            if len(buf) + len(sent) + 1 <= target_chars:
                buf = (buf + " " + sent).strip()
            else:
                if buf:
                    chunks.append(ChunkSpec(
                        ord=ord_i, page=page_no, text=buf,
                        section=section, kind="text",
                    ))
                    ord_i += 1
                # apply overlap
                tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
                buf = (tail + " " + sent).strip()
        if buf:
            chunks.append(ChunkSpec(
                ord=ord_i, page=page_no, text=buf,
                section=section, kind="text",
            ))
            ord_i += 1

    return chunks
