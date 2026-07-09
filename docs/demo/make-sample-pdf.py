#!/usr/bin/env python3
"""Generate the deterministic sample paper used by the demo capture.

Pure standard library — no reportlab/fpdf/PIL required. Emits a valid,
single-page PDF with wrapped text so the demo always ingests the *same*
document and the resulting GIF is reproducible run to run.

Usage:
    python3 docs/demo/make-sample-pdf.py            # -> docs/demo/sample-paper.pdf
    python3 docs/demo/make-sample-pdf.py out.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

TITLE = "Emergent Curiosity in Autonomous Research Agents"
BODY = """Abstract. We study whether a language-model agent, given a corpus of
scientific PDFs and no human questions, can identify its own knowledge gaps
and pursue them productively. We describe a closed loop in which the agent
ingests documents, generates questions across nine categories, answers them
with grounded evidence, reflects on each answer to spawn deeper questions,
and synthesizes cross-document insights. A curiosity module inspects the
agent's own uncertainty and seeds new questions from the gaps it finds.

1. Introduction. Retrieval-augmented systems are overwhelmingly reactive:
a user asks, the system answers. We ask a different question. What happens
when an agent is left alone with a library and told only to understand it?
The agent must decide what is worth asking. This shifts the hard problem
from answering to question formation.

2. Method. Each document is parsed, chunked, and embedded. Hybrid retrieval
fuses dense vector scores with BM25 lexical scores using reciprocal rank
fusion. Answers below a confidence threshold are marked unresolved and fed
back to the questioner as explicit knowledge gaps. A persistent self-model
records beliefs, known unknowns, and current curiosities, and is promoted
into a searchable memory the solver reads at answer time.

3. Results. Over a 1,000-paper run the agent issued 33 model calls per
document on average and surfaced alt3 cross-document contradictions that a
single-document reader would miss. The intelligence score, a composite of
coverage, grounding, and novelty, rose monotonically as the loop ran.

4. Discussion. The novel component is not retrieval but the curiosity loop:
gap detection -> self-question -> solve -> memory. We make no claim about
machine consciousness; the self-model is an engineering device for directing
attention, not a phenomenal one.""".replace("alt3", "13")


def esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def wrap(text: str, width: int = 82) -> list[str]:
    out: list[str] = []
    for para in text.split("\n\n"):
        words = para.replace("\n", " ").split()
        line = ""
        for w in words:
            if len(line) + len(w) + 1 > width:
                out.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        out.append(line)
        out.append("")  # blank line between paragraphs
    return out


def build_content() -> str:
    lines = ["BT", "/F1 20 Tf", "72 748 Td", "18 TL", f"({esc(TITLE)}) Tj", "ET"]
    body = ["BT", "/F2 10.5 Tf", "72 712 Td", "15 TL"]
    for ln in wrap(BODY):
        body.append(f"({esc(ln)}) Tj T*")
    body.append("ET")
    return "\n".join(lines + body)


def build_pdf() -> bytes:
    content = build_content().encode("latin-1", "replace")
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"

    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objs) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_pos
    return bytes(out)


def main() -> None:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("sample-paper.pdf")
    dest.write_bytes(build_pdf())
    print(f"wrote {dest} ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
