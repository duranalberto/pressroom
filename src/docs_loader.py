from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.config import Config

_cfg = Config()


@lru_cache(maxsize=None)
def load_doc(filename: str) -> str:
    """Load an agent-context file from the ``context/`` directory.

    Results are LRU-cached for the lifetime of the process. The same doc file
    is loaded for every artifact of a given type within a run, and files do not
    change mid-run, so caching is safe. Call ``load_doc.cache_clear()`` only in
    tests or if the context directory is updated between runs.

    Args:
        filename: Bare filename relative to ``Config().docs_dir``
            (e.g. ``"MERMAID_AUTHORING.md"``).

    Returns:
        The full UTF-8 text of the file.

    Raises:
        FileNotFoundError: If the file does not exist under ``Config().docs_dir``.
    """
    path = _cfg.docs_dir / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Documentation file not found: {path}\n"
            "Run the setup script or copy files from the albertoduran project."
        )
    return path.read_text(encoding="utf-8")


def load_template(name: str) -> dict[str, Any]:
    """Load a publication template from ``templates/<name>.yaml``.

    Normalizes legacy keys so callers always see a consistent schema regardless
    of which optional sections the template file includes.

    Args:
        name: Template stem without the ``.yaml`` extension (e.g. ``"default"``).

    Returns:
        Dict with at minimum: ``name``, ``description``, ``config`` (list of
        field dicts), ``goal``, ``outline_structure``, ``frontmatter``,
        ``agents``, and ``visuals``. Missing optional keys default to empty
        strings, dicts, or lists.

    Raises:
        FileNotFoundError: If no matching ``.yaml`` file exists, with a list
            of available template names included in the message.
    """
    path = _cfg.templates_dir / f"{name}.yaml"
    if not path.exists():
        available = [p.stem for p in _cfg.templates_dir.glob("*.yaml")]
        raise FileNotFoundError(
            f"Template '{name}' not found at {path}\n"
            f"Available templates: {', '.join(sorted(available)) or 'none'}"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Normalize: expose config fields under "config" regardless of which key was used.
    # "config" is the current schema; "questions" is the legacy key kept for compatibility.
    if "config" not in data:
        data["config"] = data.get("questions", [])
    # Optional extended schema keys — normalize so callers never need to guard.
    data.setdefault("goal", "")
    data.setdefault("outline_structure", [])  # legacy location; agents.outline.structure preferred
    data.setdefault("frontmatter", {})
    data.setdefault("agents", {})             # per-agent fine-tuning (template_config helpers)
    data.setdefault("visuals", [])            # preconfigured visual-template references
    return data


def list_templates() -> list[dict[str, str]]:
    """Return a summary of every ``.yaml`` template in the templates directory.

    Returns:
        List of dicts, each with keys ``file`` (stem), ``name``, and
        ``description`` (first line of the template's description field).
        Sorted by filename. Templates that fail to parse are silently skipped.
    """
    results = []
    for p in sorted(_cfg.templates_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            results.append({
                "file": p.stem,
                "name": data.get("name", p.stem),
                "description": (data.get("description") or "").strip().split("\n")[0],
            })
        except Exception:
            pass
    return results
