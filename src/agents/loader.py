"""Loader node — the first node in the workflow.

Loads every petition file from the input directory and the configured template into
state, so downstream nodes read structured data rather than re-reading disk. Owns:

  - Input discovery (.md / .mdx / .txt / .json), with structure-aware JSON trimming.
  - A reference to each source file (path, name, char count) in `input_files`.
  - The full template, exposed as `template_data` for the outline and metadata nodes.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from src.docs_loader import load_template
from src.state import InputFile, PublicationState

_console = Console()

# ── JSON trimming ─────────────────────────────────────────────────────────────

_JSON_CHAR_LIMIT = 8_000   # trigger: JSON files larger than this are structure-trimmed
_JSON_MAX_CHARS = 40_000   # post-trim ceiling: array-trimmed JSON ships whole up to here
_JSON_ARRAY_THRESHOLD = 8  # arrays longer than this get summarized, not listed in full
_JSON_ARRAY_HEAD = 3       # leading elements kept from a summarized array
_JSON_ARRAY_TAIL = 2       # trailing elements kept from a summarized array

_INPUT_PATTERNS = ["*.md", "*.mdx", "*.txt", "*.json"]


def _summarize_json(obj):
    """Recursively trim long arrays so the citable scalar/object data survives.

    Large JSON inputs are dominated by noisy time-series arrays (e.g. a 1,255-point
    price history) that the outline rules forbid citing point-by-point. Listing them
    in full pushes the real data points (metrics, valuations, summaries) out of the
    LLM's context window. This keeps every scalar and object intact and replaces the
    middle of any long array with an elision marker, so no individual metric is lost.
    """
    if isinstance(obj, dict):
        return {k: _summarize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > _JSON_ARRAY_THRESHOLD:
            head = [_summarize_json(x) for x in obj[:_JSON_ARRAY_HEAD]]
            tail = [_summarize_json(x) for x in obj[-_JSON_ARRAY_TAIL:]]
            elided = len(obj) - _JSON_ARRAY_HEAD - _JSON_ARRAY_TAIL
            return head + [f"... {elided} more items elided ..."] + tail
        return [_summarize_json(x) for x in obj]
    return obj


def _byte_truncate(text: str, limit: int) -> str:
    """Last-resort truncation at a newline boundary, with a visible marker."""
    truncated = text[:limit]
    last_newline = truncated.rfind("\n")
    if last_newline > 0:
        truncated = truncated[:last_newline]
    total_kb = len(text) // 1024
    return f"{truncated}\n\n[... truncated — original file is {total_kb}KB; key data above ...]"


def _read_file(f: Path) -> str:
    """Read a petition file, applying structure-aware JSON trimming when needed.

    For non-JSON files, or JSON files under ``_JSON_CHAR_LIMIT``, returns the
    raw text. For larger JSON files, trims long arrays while preserving every
    scalar and object value, then falls back to byte truncation only if the
    trimmed result still exceeds ``_JSON_MAX_CHARS``.

    Args:
        f: Path to the input file.

    Returns:
        UTF-8 text content, possibly summarized or truncated with an
        elision marker.
    """
    text = f.read_text(encoding="utf-8")
    if f.suffix != ".json" or len(text) <= _JSON_CHAR_LIMIT:
        return text

    # Structure-aware first: trim long arrays but keep every scalar/object data point.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _byte_truncate(text, _JSON_CHAR_LIMIT)

    compact = json.dumps(_summarize_json(data), indent=2, ensure_ascii=False, default=str)
    # Array-trimming removes the noisy time-series; what remains is citable data, so it
    # ships whole up to the ceiling. Byte truncation is only a guardrail for outliers.
    return compact if len(compact) <= _JSON_MAX_CHARS else _byte_truncate(compact, _JSON_MAX_CHARS)


# ── Input discovery ───────────────────────────────────────────────────────────

def _discover_files(input_dir: Path) -> list[Path]:
    """Return all petition files under ``input_dir``, sorted and deduplicated.

    Scans recursively for ``*.md``, ``*.mdx``, ``*.txt``, and ``*.json``
    files. Files are deduplicated by path so a file matched by multiple glob
    patterns is only included once.

    Args:
        input_dir: Root directory to search.

    Returns:
        Sorted list of absolute ``Path`` objects.
    """
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in _INPUT_PATTERNS:
        for f in sorted(input_dir.rglob(pattern)):
            if f not in seen:
                seen.add(f)
                files.append(f)
    return files


def _load_input(input_dir: Path) -> tuple[str, list[InputFile]]:
    """Read every petition file and return combined content plus structured references."""
    files = _discover_files(input_dir)
    parts: list[str] = []
    refs: list[InputFile] = []
    for f in files:
        rel = f.relative_to(input_dir)
        content = _read_file(f)
        parts.append(f"## FILE: {rel}\n\n{content}")
        refs.append(InputFile(path=str(f), name=str(rel), chars=len(content)))
    return "\n\n---\n\n".join(parts), refs


# ── LangGraph node entry point ────────────────────────────────────────────────

def run(state: PublicationState) -> dict:
    """Load petition files and the publication template into pipeline state.

    Reads: input_dir, template_name
    Writes: petition_content, input_file_paths, input_files, template_data
    """
    input_dir = Path(state.get("input_dir") or "input")
    _console.print(f"  [bright_black]Loader:[/bright_black] reading input from {input_dir}…")

    petition_content, input_files = _load_input(input_dir)
    if not input_files:
        return {"errors": [f"Loader: no .md / .mdx / .txt / .json files found in {input_dir}"]}
    _console.print(
        f"  Loaded [cyan]{len(input_files)}[/cyan] file(s): "
        f"{', '.join(f['name'] for f in input_files)}"
    )

    template_name = state.get("template_name", "default") or "default"
    try:
        template_data = load_template(template_name)
    except FileNotFoundError:
        template_data = {"name": template_name}

    return {
        "petition_content": petition_content,
        "input_file_paths": [f["path"] for f in input_files],
        "input_files": input_files,
        "template_data": template_data,
    }
