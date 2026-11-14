"""Deterministic checks on a Finalyst brief: every figure in it must come from the gathered data.

The Reviewer model judges suitability and tone; this code checks the numbers, which models are bad at
checking and code is good at. A figure is supported when it matches (within rounding) a number anywhere in
the facts, analytics or research the Finalyst was given.
"""

from __future__ import annotations

import re
from typing import Any

# Dates and years are context, not figures: removed before numbers are read.
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b")
# $1,234.56 / 12.5% / 1.85M / -3.2
_FIGURE = re.compile(r"(?<![\w.])-?\$?(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB](?![a-zA-Z]))?")
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}


def figures_in(text: str) -> list[float]:
    """Numbers a reader would take as figures (years, dates and small counts like '3 accounts' are skipped)."""
    out = []
    for m in _FIGURE.finditer(_DATE.sub(" ", text)):
        value = float(m.group(1).replace(",", ""))
        if m.group(2):
            value *= _SCALE[m.group(2).lower()]
        if m.group(0).lstrip().startswith("-"):
            value = -value
        if value.is_integer() and abs(value) <= 12 and not m.group(2):
            continue  # small counts (3 suggestions, 5 years, 1Y) aren't checked
        out.append(value)
    return out


def known_numbers(*sources: Any) -> list[float]:
    """Every number in the given data: numeric values, and figures inside its text (e.g. news snippets)."""
    found: list[float] = []

    def walk(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            found.append(float(v))
        elif isinstance(v, str):
            found.extend(figures_in(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    for s in sources:
        walk(s)
    return found


def supported(value: float, known: list[float]) -> bool:
    for k in known:
        tolerance = max(
            0.051, abs(k) * 0.01
        )  # rounding to 0.1, or 1% of large amounts ($1.85M for 1,854,511)
        if abs(abs(value) - abs(k)) <= tolerance:
            return True
    return False


def brief_text(brief: dict) -> list[tuple[str, str]]:
    """(where, text) for every piece of prose in a brief."""
    parts = [("summary", brief.get("summary", "")), ("client snapshot", brief.get("client_snapshot", ""))]
    for i, s in enumerate(brief.get("suggestions", []), start=1):
        parts += [(f"suggestion {i}", s.get("title", "")), (f"suggestion {i}", s.get("rationale", ""))]
        parts += [(f"suggestion {i}", s.get("risks", ""))]
        parts += [(f"suggestion {i} evidence", e.get("detail", "")) for e in s.get("evidence", [])]
    parts += [("questions", q) for q in brief.get("questions_for_meeting", [])]
    return parts


def unsupported_figures(brief: dict, known: list[float]) -> list[str]:
    problems = []
    for where, text in brief_text(brief):
        for value in figures_in(text):
            if not supported(value, known):
                problems.append(f"{where}: the figure {value:g} is not in the data")
    return problems
