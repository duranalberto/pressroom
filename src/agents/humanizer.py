"""Agent 4 — Humanizer.

Makes the approved draft feel authentically human-written by removing AI patterns,
varying rhythm, and applying theJournal body style rules.

Pattern guidance is built per-draft by humanizer_patterns.select_patterns, so only
the patterns that actually fire in the body are injected into the prompt.

Optionally uses the blader/humanizer CLI tool (https://github.com/blader/humanizer)
if it is installed; falls back to an LLM-based pass otherwise.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from src.llm import build_model, invoke_with_retry
from src.mdx_document import MDXDocument, strip_em_dashes
from src.state import PublicationState
from src.template_config import apply_finetune
from src.agents._style import style_rules_block
from src.agents.humanizer_patterns import (
    apply_mechanical_fixes,
    render_patterns,
    select_patterns,
)

logger = logging.getLogger(__name__)

_console = Console()

_HEADING_RE = re.compile(r"^#{2,4} .+", re.MULTILINE)
_FENCED_BLOCK_RE = re.compile(r"```[^\n]*\n.*?\n```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_MDX_COMPONENT_START_RE = re.compile(r"^[ \t]*<([A-Z][\w.:]*)\b")
_FENCE_LINE_RE = re.compile(r"^[ \t]*```")


def _extract_mdx_component_blocks(content: str) -> list[str]:
    """Extract top-level MDX component blocks from a body string.

    Handles both self-closing (``<Callout />``) and multi-line container
    components (``<Callout>…</Callout>``). Ignores component-like text inside
    fenced code blocks so examples embedded in the prose are not treated as
    live JSX.

    Args:
        content: The raw publication body string.

    Returns:
        List of component block strings in document order. Each item is the
        full raw text of one top-level component, from its opening tag to its
        closing tag or ``/>``.
    """
    """Return top-level MDX component blocks, ignoring examples inside code fences."""
    blocks: list[str] = []
    lines = content.splitlines(keepends=True)
    in_fence = False
    i = 0

    while i < len(lines):
        line = lines[i]
        if _FENCE_LINE_RE.match(line):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue

        start = _MDX_COMPONENT_START_RE.match(line)
        if not start:
            i += 1
            continue

        component_name = start.group(1)
        block = [line]
        if "/>" in line or f"</{component_name}>" in line:
            blocks.append("".join(block))
            i += 1
            continue
        opening_tag_closed = ">" in line

        i += 1
        while i < len(lines):
            current = lines[i]
            block.append(current)
            if f"</{component_name}>" in current:
                break
            if not opening_tag_closed:
                if "/>" in current:
                    break
                if ">" in current:
                    opening_tag_closed = True
            i += 1
        blocks.append("".join(block))
        i += 1

    return blocks

_SYSTEM = """\
You are a writing humanizer for theJournal at albertoduran.com.

Take the approved publication body and make the prose sound authentically human-written:
natural, varied in rhythm, free of AI patterns, and true to the author's style.

You receive only the **body** of a publication.
Rewrite prose only. Return only the body.

---

## AI WRITING PATTERNS TO REMOVE

Fix each of the AI-writing patterns below. Rewrite, don't delete — replace the pattern with a
natural alternative that covers the same ground. Leave prose that already reads naturally
alone; do not manufacture changes to look busy.

{patterns}

## THEJOURNAL BODY STYLE RULES

- Keep a direct, specific, technically literate voice.
- Prefer concrete claims over abstract significance language.
{style_rules}

---

## SCOPE AND CONSTRAINTS

APPLY:
- Every AI writing pattern listed above.
- All theJournal body style rules above.
- Author preferences passed in the user message (tone, audience, additional context).
- Do not synonym-swap technical terms or proper nouns the author uses deliberately.

PRESERVE EXACTLY:
- All `---` section separators before `##` headings.
- All `##`, `###`, and `####` headings (exact text and sentence case).
- All fenced code blocks (content, language tags, and indentation).
- All links and their anchor text.
- All MDX/JSX component blocks, including opening tags, closing tags, props, braces,
  indentation, and children.
- All technical facts, claims, and code examples.

DO NOT:
- Add or remove sections.
- Change the meaning of any claim.
- Invent new technical details.
- Add, remove, rename, wrap, unwrap, reorder, or edit MDX/JSX components.
- Add MDX component imports, document metadata blocks, or file-level wrappers.
- Wrap the output in code fences.
"""

_HUMANIZE_PROMPT = """\
Humanize this publication body.

AUTHOR PREFERENCES:
- Tone: {tone}
- Audience: {audience}
- Additional context: {context}

--- BEGIN BODY ---
{content}
--- END BODY ---

Apply the full humanizer pass to the body. Return only the body.
"""


def _try_cli_humanizer(content: str) -> str | None:
    """Attempt to run blader/humanizer CLI if available. Returns result or None."""
    if not shutil.which("humanizer"):
        return None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp = Path(f.name)
        result = subprocess.run(
            ["humanizer", str(tmp)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        tmp.unlink(missing_ok=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _preserves_structure(original: str, output: str) -> bool:
    """Return ``True`` when ``output`` preserves all critical MDX structure from ``original``.

    Checks headings, ``---`` separators, fenced code blocks, Markdown links, and
    MDX component blocks. Used to validate both the CLI humanizer output and the
    LLM humanizer output before accepting either.

    Args:
        original: The body before humanization (after mechanical fixes).
        output: The humanized body to validate.

    Returns:
        ``True`` if all structural elements are identical; ``False`` with a
        warning log entry if any check fails.
    """
    if _HEADING_RE.findall(original) != _HEADING_RE.findall(output):
        logger.warning("Humanizer changed H2/H3 headings — falling back.")
        return False

    if output.count("\n---\n") != original.count("\n---\n"):
        logger.warning("Humanizer changed --- separators — falling back.")
        return False

    if _FENCED_BLOCK_RE.findall(original) != _FENCED_BLOCK_RE.findall(output):
        logger.warning("Humanizer changed fenced code blocks — falling back.")
        return False

    if _MARKDOWN_LINK_RE.findall(original) != _MARKDOWN_LINK_RE.findall(output):
        logger.warning("Humanizer changed Markdown links — falling back.")
        return False

    if _extract_mdx_component_blocks(original) != _extract_mdx_component_blocks(output):
        logger.warning("Humanizer changed MDX components — falling back.")
        return False

    return True


def _build_system(state: PublicationState) -> str:
    """Compose the humanizer system prompt with only the patterns the body triggers.

    The pattern catalogue is triaged against the draft body (so the prompt carries relevant
    guidance, not all 33 patterns), the shared style canon is interpolated, then template
    fine-tuning is appended AFTER ``str.format`` so braces in the user-supplied prompt are
    never interpreted as format fields.
    """
    draft = state.get("draft") or {}
    body = draft.get("body", "") if isinstance(draft, dict) else ""
    system = _SYSTEM.format(
        patterns=render_patterns(select_patterns(body)),
        style_rules=style_rules_block(),
    )
    return apply_finetune(system, state.get("template_data") or {}, "humanizer")


def run(state: PublicationState) -> dict:
    """Apply a humanization pass to the approved draft body.

    Tries the blader/humanizer CLI first; falls back to an LLM pass. Either
    result is validated with ``_preserves_structure`` before being accepted;
    the original body is used as a last resort if both fail validation.

    Reads: draft, tone, audience, additional_context, template_data
    Writes: humanized
    """
    _console.print("  [magenta]Humanizer:[/magenta] removing AI patterns and varying rhythm…")
    source_doc = state.get("draft")
    if not source_doc:
        return {"errors": ["Humanizer: no draft document to humanize"]}

    # Mechanical patterns (curly quotes) are fixed deterministically up front, so the LLM
    # never spends attention on them and the fix is guaranteed regardless of model behaviour.
    original_body = apply_mechanical_fixes(source_doc["body"])

    # Try the blader/humanizer CLI first (body only); validate structure before accepting
    cli_result = _try_cli_humanizer(original_body)
    if cli_result and _preserves_structure(original_body, cli_result):
        return {"humanized": MDXDocument(
            metadata=source_doc["metadata"],
            imports=source_doc["imports"],
            body=strip_em_dashes(cli_result.strip()),
        )}

    # Fall back to LLM-based humanization of the body
    llm = build_model()
    system = _build_system(state)

    try:
        humanized_body = invoke_with_retry(llm, [
            SystemMessage(content=system),
            HumanMessage(content=_HUMANIZE_PROMPT.format(
                tone=state.get("tone", "conversational"),
                audience=state.get("audience", "developers"),
                context=state.get("additional_context") or "none provided",
                content=original_body,
            )),
        ])
    except Exception as exc:
        logger.error("Humanizer: LLM pass failed — %s", exc)
        return {"errors": [f"Humanizer: LLM pass failed — {exc}"]}

    humanized_body = humanized_body.strip()
    if not _preserves_structure(original_body, humanized_body):
        logger.warning(
            "Humanizer LLM changed structural elements (headings, separators, fences, "
            "links, or MDX components) — falling back to original body."
        )
        humanized_body = original_body

    return {"humanized": MDXDocument(
        metadata=source_doc["metadata"],
        imports=source_doc["imports"],
        body=strip_em_dashes(humanized_body),
    )}
