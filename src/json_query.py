"""Deterministic JSON value lookup, rooted at the input directory.

A single reusable helper that returns the exact value or array at a JSON path inside an
input file. It reads the raw file from disk — bypassing the loader's array trimming — so
high-cardinality data (e.g. a 1,255-point price history) survives intact. No LLM is
involved, so nothing in the data path can be hallucinated.

    query("valuation_data.json", "historical_data.price_history", last=63)
    query("valuation_data.json", "valuations.DCF.scenarios.Base.intrinsic_value_per_share")
    query("news_data.json", "yahoo_finance[0].title")

The file is resolved against the input directory and must stay inside it (no traversal).
Failures raise ``JsonQueryError`` with the file, path, and reason so callers can degrade
gracefully rather than fabricate data.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from src.config import Config

# path segment → key name plus zero or more [index] accessors.
_SEGMENT_RE = re.compile(r"^([^\[\]]*)((?:\[\d+\])*)$")
_INDEX_RE = re.compile(r"\[(\d+)\]")

# Parsed-file cache keyed by (resolved path, mtime). Files do not change mid-run, and the
# same file is queried by several bindings, so this parses each input once.
_cache: dict[tuple[str, float], Any] = {}


class JsonQueryError(Exception):
    """Raised when a query cannot be resolved (missing file/path, bad type, traversal)."""


def _resolve_root(input_dir: str | Path | None) -> Path:
    return Path(input_dir).resolve() if input_dir else Config().input_dir.resolve()


def _load(file_name: str, root: Path) -> Any:
    """Parse and cache a JSON input file, keyed by path and mtime.

    Args:
        file_name: Filename relative to ``root`` (e.g. ``"valuation_data.json"``).
        root: Resolved input directory; used to guard against path traversal.

    Returns:
        The parsed JSON value (dict, list, or scalar).

    Raises:
        JsonQueryError: If the file resolves outside ``root``, does not exist,
            or is not valid JSON.
    """
    target = (root / file_name).resolve()
    if target != root and root not in target.parents:
        raise JsonQueryError(f"{file_name!r} resolves outside the input directory {root}")
    if not target.is_file():
        raise JsonQueryError(f"input file not found: {target}")

    key = (str(target), target.stat().st_mtime)
    if key not in _cache:
        try:
            _cache[key] = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise JsonQueryError(f"{file_name!r} is not valid JSON — {exc}") from exc
    return _cache[key]


def _tokens(path: str) -> list[str | int]:
    """Tokenize a dotted JSON path into a sequence of string keys and int indices.

    Args:
        path: Dotted path with optional bracket indices, e.g.
            ``"historical_data.price_history"`` or ``"items[0].field"``.

    Returns:
        List of alternating string keys and integer array indices in traversal
        order, e.g. ``["historical_data", "price_history"]`` or
        ``["items", 0, "field"]``.

    Raises:
        JsonQueryError: If any path segment is malformed.
    """
    """Tokenize a dotted path with optional [index] accessors into keys and ints."""
    out: list[str | int] = []
    for part in path.split("."):
        m = _SEGMENT_RE.match(part)
        if not m:
            raise JsonQueryError(f"malformed path segment: {part!r}")
        key, indices = m.group(1), m.group(2)
        if key:
            out.append(key)
        for idx in _INDEX_RE.findall(indices):
            out.append(int(idx))
    return out


def _navigate(data: Any, path: str, file_name: str) -> Any:
    current = data
    for token in _tokens(path):
        try:
            current = current[token]
        except (KeyError, IndexError, TypeError) as exc:
            raise JsonQueryError(
                f"path {path!r} not found in {file_name!r} (failed at {token!r})"
            ) from exc
    return current


def query(
    file_name: str,
    path: str,
    *,
    last: int | None = None,
    input_dir: str | Path | None = None,
) -> Any:
    """Return the value at ``path`` inside ``<input_dir>/<file_name>``.

    Args:
        file_name: JSON filename relative to ``input_dir``
            (e.g. ``"valuation_data.json"``).
        path: Dotted path with optional bracket indices
            (e.g. ``"historical_data.price_history"`` or ``"items[0].field"``).
        last: If set, return only the last ``N`` items of the resolved list.
            A count larger than the list length returns the whole list.
            Raises ``JsonQueryError`` if the resolved value is not a list or
            ``last`` is not a positive integer.
        input_dir: Directory to resolve ``file_name`` against. Defaults to
            ``Config().input_dir``. Always pass ``state["input_dir"]`` so the
            ``--input`` CLI override and test fixtures are respected.

    Returns:
        The value at the path — dict, list, str, int, float, bool, or ``None``.

    Raises:
        JsonQueryError: If the file cannot be loaded, the path does not exist,
            or the ``last`` constraint is violated.
    """
    root = _resolve_root(input_dir)
    data = _load(file_name, root)
    value = _navigate(data, path, file_name)

    if last is not None:
        if not isinstance(value, list):
            raise JsonQueryError(
                f"last={last!r} requires a list at {path!r} in {file_name!r}, "
                f"got {type(value).__name__}"
            )
        if isinstance(last, bool) or not isinstance(last, int) or last <= 0:
            raise JsonQueryError(f"last must be a positive integer, got {last!r}")
        value = value[-last:]
    return value


def clear_cache() -> None:
    """Drop the in-process parsed-file cache.

    Call in tests to reset between runs, or when input files are replaced
    mid-process. Normal pipeline runs never need this.
    """
    _cache.clear()
