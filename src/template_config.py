"""Per-agent template configuration — optional fine-tuning passed to the agents.

Templates may carry an optional ``agents:`` block keyed by agent name. Each entry can
hold a free-form ``prompt`` (general fine-tuning appended to that agent's system prompt)
plus agent-specific config. The outline agent additionally reads ``structure`` (the
section plan, formerly the top-level ``outline_structure`` key).

Everything here is optional: when a key is absent or empty, nothing is added to the
agent's prompt and the fine-tuning is never mentioned to the model. Helpers are pure
functions over the loaded template dict, so they are trivially testable.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# A `### ` section heading in an outline (exactly three hashes — excludes `##` meta
# sections and `####` subsections).
_OUTLINE_SECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)

# The four agents that support template fine-tuning.
AGENT_KEYS = ("outline", "writer", "reviewer", "humanizer")

# Heading used to delimit injected fine-tuning so the model reads it as instructions.
_FINETUNE_HEADING = "## ADDITIONAL INSTRUCTIONS (from template)"


def _agents_block(template: dict) -> dict:
    block = template.get("agents")
    return block if isinstance(block, dict) else {}


def agent_prompt(template: dict, agent: str) -> str:
    """Return the fine-tuning prompt for ``agent``, or ``""`` when none is set.

    Args:
        template: Loaded template dict (from ``load_template``).
        agent: One of ``"outline"``, ``"writer"``, ``"reviewer"``, ``"humanizer"``.

    Returns:
        The stripped prompt string, or ``""`` if the key is absent or empty.
    """
    entry = _agents_block(template).get(agent)
    if not isinstance(entry, dict):
        return ""
    return (entry.get("prompt") or "").strip()


def outline_structure(template: dict) -> list:
    """Return the ordered section structure from a template.

    Prefers ``agents.outline.structure``; falls back to the legacy top-level
    ``outline_structure`` key so older templates remain compatible.

    Args:
        template: Loaded template dict (from ``load_template``).

    Returns:
        List of section dicts (each has at minimum ``id`` and ``title``), or
        an empty list when the template defines no structure.
    """
    entry = _agents_block(template).get("outline")
    if isinstance(entry, dict):
        structure = entry.get("structure")
        if isinstance(structure, list) and structure:
            return structure
    legacy = template.get("outline_structure")
    return legacy if isinstance(legacy, list) else []


def section_titles(template: dict, outline: str) -> list[str]:
    """Return the ordered, de-duplicated section titles for a publication.

    The template's recommended ``structure`` titles come first (they define the
    canonical order); any extra ``### `` section the outline added that is not
    already covered is appended in document order. Matching is case-insensitive,
    so a section the outline restated under a slightly different case is not
    duplicated.

    Args:
        template: Loaded template dict (from ``load_template``).
        outline: The outline designer's raw output text.

    Returns:
        List of section title strings (structure titles first, outline-only
        titles after), or an empty list when neither source provides any.
    """
    titles: list[str] = []
    seen: set[str] = set()

    def _add(title: str) -> None:
        clean = (title or "").strip()
        if clean and clean.lower() not in seen:
            titles.append(clean)
            seen.add(clean.lower())

    for section in outline_structure(template):
        if isinstance(section, dict):
            _add(section.get("title", ""))

    for match in _OUTLINE_SECTION_RE.finditer(outline or ""):
        _add(match.group(1))

    return titles


def apply_finetune(system: str, template: dict, agent: str) -> str:
    """Append a template's agent-specific fine-tuning to a system prompt.

    Uses string concatenation instead of ``str.format`` so that literal
    ``{{ }}`` braces in either the base prompt or the template text are never
    interpreted as format fields.

    Args:
        system: The agent's base system prompt.
        template: Loaded template dict (from ``load_template``).
        agent: The agent name whose ``agents.<agent>.prompt`` block to inject.

    Returns:
        ``system`` with the fine-tuning block appended under a section heading,
        or ``system`` unchanged if no prompt is configured for ``agent``.
    """
    prompt = agent_prompt(template, agent)
    if not prompt:
        return system
    return f"{system}\n\n{_FINETUNE_HEADING}\n\n{prompt}\n"


def warn_unknown_agents(template: dict) -> None:
    """Log a warning for any ``agents:`` key that is not a recognized agent."""
    for key in _agents_block(template):
        if key not in AGENT_KEYS:
            logger.warning(
                "Template 'agents' block has unknown agent '%s' — ignored. "
                "Known agents: %s",
                key,
                ", ".join(AGENT_KEYS),
            )
