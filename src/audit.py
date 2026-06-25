"""Audit trail helpers — run identifiers and per-step body snapshots.

The orchestrator (`main.py`) owns audit file I/O, mirroring the existing rule that
agents never touch disk. Each pipeline run is allocated a monotonically incrementing
numeric id, tracked in a git-ignored counter file. The id prefixes the final `.mdx`
filename and names a per-run audit directory under `output/audit/<id>/`, where the body
delivered by each intermediary step (outline, writer, reviewer, humanizer) is saved
without frontmatter so a published file can be traced back to what each agent produced.

All writers here swallow their own errors: auditing must never crash a publication run.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Zero-padding width for the numeric run id (keeps filenames and listings aligned).
_ID_WIDTH = 4

# Name of the audit subdirectory inside the output directory.
AUDIT_DIRNAME = "audit"

# Maps a graph node name to the audit step file it produces (without extension).
# Nodes not present here have no body to snapshot.
NODE_TO_STEP: dict[str, str] = {
    "outline_designer": "outline",
    "writer": "writer",
    "reviewer": "reviewer",
    "humanizer": "humanizer",
}


def allocate_run_id(counter_path: Path) -> int:
    """Read, increment, persist, and return the next monotonic run id.

    A missing, empty, or unparseable counter file is treated as 0, so the
    first run on a fresh checkout is always id 1. The operation is
    read-modify-write; concurrent runs are out of scope for a single-user
    local CLI.

    Args:
        counter_path: Path to the plain-text counter file. Parent directories
            are created automatically if absent.

    Returns:
        The new run id (previous value + 1).
    """
    current = 0
    try:
        raw = counter_path.read_text(encoding="utf-8").strip()
        current = int(raw)
    except (FileNotFoundError, ValueError):
        current = 0
    except OSError as exc:
        logger.warning("Could not read run-id counter %s — starting at 0. %s", counter_path, exc)
        current = 0

    new_id = current + 1
    try:
        counter_path.parent.mkdir(parents=True, exist_ok=True)
        counter_path.write_text(str(new_id), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not persist run-id counter %s — %s", counter_path, exc)
    return new_id


def format_run_id(run_id: int) -> str:
    """Zero-pad the numeric run id for use in filenames and directory names."""
    return f"{run_id:0{_ID_WIDTH}d}"


def run_dir(output_dir: Path, run_id: str) -> Path:
    """Return the per-run audit directory: ``<output_dir>/audit/<run_id>/``."""
    return Path(output_dir) / AUDIT_DIRNAME / run_id


def write_step_body(audit_run_dir: Path, step: str, body: str) -> None:
    """Write ``<step>.md`` into the run's audit directory.

    All ``OSError`` failures are logged and swallowed — a disk problem in the
    audit trail must never abort a publication run.

    Args:
        audit_run_dir: Per-run directory (created if absent).
        step: Step name, used as the filename stem (e.g. ``"writer"``).
        body: Raw agent output with no frontmatter. An empty string writes an
            empty file rather than skipping the write.
    """
    try:
        audit_run_dir.mkdir(parents=True, exist_ok=True)
        (audit_run_dir / f"{step}.md").write_text(body or "", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write audit step %s in %s — %s", step, audit_run_dir, exc)
