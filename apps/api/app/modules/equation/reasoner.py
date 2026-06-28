"""Lightweight equation reasoner — parses formula chunks with sympy, exposes variables and a graphable form."""
from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

_EQ_SPLIT = re.compile(r"\s*=\s*")


@dataclass
class ParsedEquation:
    raw: str
    lhs: str
    rhs: str
    variables: list[str]
    sympy_form: str
    graphable: bool


def parse_equation(raw: str) -> ParsedEquation | None:
    if "=" not in raw:
        return None
    parts = _EQ_SPLIT.split(raw, maxsplit=1)
    if len(parts) != 2:
        return None
    lhs, rhs = parts[0].strip(), parts[1].strip()
    try:
        from sympy import symbols, sympify  # noqa: F401
        expr = sympify(rhs, evaluate=False)
        free = sorted({str(s) for s in expr.free_symbols})
        graphable = 1 <= len(free) <= 2
        return ParsedEquation(
            raw=raw, lhs=lhs, rhs=rhs,
            variables=free, sympy_form=str(expr),
            graphable=graphable,
        )
    except Exception as e:
        logger.debug("Equation parse failed for '{}': {}", raw, e)
        return None


def evaluate(expr: str, values: dict[str, float]) -> float | None:
    try:
        from sympy import sympify
        e = sympify(expr)
        return float(e.subs(values))
    except Exception as e:
        logger.debug("Eval failed: {}", e)
        return None
