"""Lightweight surface-level extractors used during ingestion.
Heavier semantic extraction (claims, definitions) happens at solve time via the LLM."""
from __future__ import annotations

import re
from collections import Counter

_KEYWORD_RE = re.compile(r"\b[A-Za-z][A-Za-z\-]{3,}\b")
_STOPWORDS = set(
    """the and that with this from have been their which were also they when into more such than then those these about
       upon would could should there here other where many must used most some any can may not but our its has had
       both will been who what does done due via per very within without across over under between among using based""".split()
)


def keywords_from_text(text: str, k: int = 12) -> list[str]:
    counts: Counter[str] = Counter()
    for m in _KEYWORD_RE.findall(text.lower()):
        if m in _STOPWORDS or len(m) < 4:
            continue
        counts[m] += 1
    return [w for w, _ in counts.most_common(k)]
