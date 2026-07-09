#!/usr/bin/env python3
"""Swap the README hero between the poster placeholder and the real GIF.

The hero lives between `<!-- DEMO:START -->` and `<!-- DEMO:END -->` markers so
this rewrite is deterministic and idempotent. make-gif.sh calls it after a
successful capture; pass `--reset` to put the poster back.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
START, END = "<!-- DEMO:START -->", "<!-- DEMO:END -->"

POSTER = (
    '<a href="docs/demo/README.md">\n'
    '  <img src="docs/demo/demo-poster.svg" alt="EvoMind demo — run make demo-gif to generate the live capture" width="820" />\n'
    "</a>"
)
GIF = (
    '<img src="docs/demo/demo.gif" alt="EvoMind: drop a PDF, watch it question, solve, and graph itself" width="820" />'
)


def main() -> int:
    inner = POSTER if "--reset" in sys.argv[1:] else GIF
    text = README.read_text(encoding="utf-8")
    block = f"{START}\n{inner}\n{END}"
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(text):
        print(f"markers {START} / {END} not found in README.md", file=sys.stderr)
        return 1
    new = pattern.sub(lambda _: block, text, count=1)
    if new == text:
        print("README hero already up to date")
        return 0
    README.write_text(new, encoding="utf-8")
    print(f"README hero -> {'poster' if inner is POSTER else 'demo.gif'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
