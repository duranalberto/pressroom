"""Metadata node — designs the publication frontmatter (title, description, tags).

Runs after the humanizer, on the final body. An LLM proposes the title, description, and
tags, guided by theJournal frontmatter rules and the template's optional `frontmatter`
guidance section. If the LLM call or parse fails, a deterministic derivation from the
body takes over, so the pipeline always produces usable frontmatter.

This replaces the deterministic-only logic that used to live in the publisher; the
publisher now consumes the `metadata` this node writes to state.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator
from rich.console import Console

from src.llm import build_model, strip_json_fences
from src.mdx_document import MDXMetadata
from src.state import PublicationState

logger = logging.getLogger(__name__)
_console = Console()

_DEFAULT_IMAGE = "../assets/thejournal/stock/01.avif"
_AUTHOR = "Alberto Duran"

_STOPWORDS = {
    "about", "actually", "after", "again", "against", "also", "and", "because", "before",
    "between", "could", "does", "doing", "done", "ever", "every", "for", "from", "have",
    "here", "into", "just", "like", "make", "makes", "many", "more", "most", "much",
    "only", "other", "over", "really", "should", "some", "such", "than", "that", "the",
    "their", "then", "these", "this", "those", "through", "under", "very", "what", "when",
    "where", "which", "while", "will", "with", "without", "would", "your",
}

_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_FENCED_BLOCK_RE = re.compile(r"```[^\n]*\n.*?\n```", re.DOTALL)


# ── Pydantic schema ───────────────────────────────────────────────────────────

class _MetadataResult(BaseModel):
    title: str = Field(description="A real article title, not a section heading")
    description: str = Field(description="One-sentence summary, <= 160 characters")
    tags: list[str] = Field(default_factory=list, description="2-5 lowercase kebab-case tags")

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [t.strip() for t in re.split(r"[,\s]+", v) if t.strip()]
        if isinstance(v, list):
            return [str(t).strip() for t in v if str(t).strip()]
        return []


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You design the YAML frontmatter for a publication on theJournal at albertoduran.com.

From the final article body, produce three fields:
- title: a real, specific article title (NOT a section heading, NOT a question copied
  from a section). It should read as the name of the whole piece.
- description: one plain sentence summarizing the article, at most 160 characters, no
  trailing ellipsis, no colons.
- tags: 2 to 5 lowercase kebab-case topic tags. No filler words, no generic stopwords.

{frontmatter_guidance}
Return ONLY a valid JSON object — no markdown fences, no extra text — matching:
{{
  "title": "...",
  "description": "...",
  "tags": ["...", "..."]
}}
"""

_PROMPT = """\
Design the frontmatter for this publication.

TEMPLATE: {template_name}
TONE: {tone}
AUDIENCE: {audience}

--- BEGIN BODY ---
{body}
--- END BODY ---

Return ONLY the JSON object described in your instructions.
"""


def _format_frontmatter_guidance(template_data: dict) -> str:
    """Render a template's optional ``frontmatter`` block into a prompt guidance string.

    Args:
        template_data: Loaded template dict. The ``frontmatter`` key is a dict
            with optional ``title``, ``description``, and ``tags`` string hints.

    Returns:
        A multi-line guidance block ready to interpolate into the system prompt,
        or ``""`` when the template has no frontmatter guidance.
    """
    fm = (template_data or {}).get("frontmatter") or {}
    if not isinstance(fm, dict) or not fm:
        return ""
    lines = ["TEMPLATE FRONTMATTER GUIDANCE (follow precisely):"]
    for key in ("title", "description", "tags"):
        guidance = (fm.get(key) or "").strip() if isinstance(fm.get(key), str) else ""
        if guidance:
            lines.append(f"- {key}: {guidance}")
    return "\n".join(lines) + "\n\n" if len(lines) > 1 else ""


# ── Deterministic fallback (relocated from the publisher) ─────────────────────

def _clean_text(text: str) -> str:
    """Strip Markdown formatting, inline HTML, and excess whitespace from text.

    Used to normalize heading text and prose snippets before using them as
    frontmatter values where raw Markdown syntax would be inappropriate.
    """
    text = _INLINE_LINK_RE.sub(r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`*_~>#\[\]]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -.,;:!?")


def _title_from_body(body: str) -> str:
    """Derive a fallback title from the first ``##`` heading in the body.

    Returns:
        The cleaned heading text, or ``"Publication"`` if no ``##`` heading
        is found.
    """
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            raw = match.group(1).rstrip()
            title = _clean_text(raw)
            if title:
                if raw.endswith("?") and not title.endswith("?"):
                    title += "?"
                elif raw.endswith("!") and not title.endswith("!"):
                    title += "!"
                return title
    return "Publication"


def _first_prose_paragraph(body: str) -> str:
    """Extract the first non-empty prose paragraph from the body.

    Skips fenced code blocks, ``---`` separators, headings, import lines, and
    JSX/HTML tags. Used as the basis for the fallback description.

    Returns:
        The cleaned paragraph text, or ``""`` if no prose paragraph is found.
    """
    body = _FENCED_BLOCK_RE.sub("\n\n", body)
    for paragraph in re.split(r"\n\s*\n", body):
        lines = []
        for line in paragraph.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped == "---"
                or stripped.startswith(("#", "import ", "<", "</", "{"))
            ):
                continue
            lines.append(stripped)
        text = _clean_text(" ".join(lines))
        if text:
            return text
    return ""


def _truncate_description(text: str, limit: int = 160) -> str:
    """Truncate ``text`` to at most ``limit`` characters at a clean sentence boundary.

    Args:
        text: Raw description candidate (may be longer than the limit).
        limit: Maximum character count. Defaults to 160 (Astro's description cap).

    Returns:
        The cleaned, truncated string. Prefers a sentence-ending boundary;
        falls back to the last word boundary; hard-truncates only as a last resort.
    """
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence_end = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
    if sentence_end >= limit // 2:
        return window[: sentence_end + 1].rstrip()
    truncated = window.rsplit(" ", 1)[0].strip()
    return truncated.rstrip(" -.,;:!?") or window.rstrip(" -.,;:!?")


def _tagify(text: str) -> list[str]:
    """Convert a text string into a list of lowercase kebab-case tag tokens.

    Splits on whitespace, commas, slashes, and pipes; strips non-alphanumeric
    characters; drops tokens shorter than 3 characters and any in ``_STOPWORDS``.

    Returns:
        Ordered list of tag strings in the order they appear in ``text``.
    """
    tags: list[str] = []
    for raw in re.split(r"[\s,/|]+", text.lower()):
        token = re.sub(r"[^a-z0-9-]", "", raw.strip())
        token = re.sub(r"-+", "-", token).strip("-")
        if len(token) < 3 or token in _STOPWORDS or token in tags:
            continue
        tags.append(token)
    return tags


def _derive_tags(template_name: str, title: str) -> list[str]:
    """Derive up to 5 fallback tags from the template name and article title.

    Adds the template name as the first tag (unless it is ``"default"``), then
    fills from the title tokens, then pads with ``"thejournal"`` / ``"publication"``
    if fewer than 2 tags were found.

    Returns:
        List of 2–5 unique kebab-case tag strings.
    """
    tags: list[str] = []
    template_tag = re.sub(r"[^a-z0-9-]", "", template_name.lower().replace("_", "-")).strip("-")
    if template_tag and template_tag != "default":
        tags.append(template_tag)
    for tag in _tagify(title):
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= 5:
            break
    if not tags:
        return ["thejournal", "publication"]
    for fallback in ("thejournal", "publication"):
        if len(tags) >= 2:
            break
        if fallback not in tags:
            tags.append(fallback)
    return tags[:5]


def _fallback_fields(body: str, template_name: str) -> _MetadataResult:
    title = _title_from_body(body)
    description = _truncate_description(_first_prose_paragraph(body) or title)
    return _MetadataResult(title=title, description=description, tags=_derive_tags(template_name, title))


# ── Assembly ──────────────────────────────────────────────────────────────────

def _has_metadata_value(value: object) -> bool:
    return value is not None and value != "" and value != []


def _assemble(fields: _MetadataResult, template_name: str, existing: MDXMetadata | None) -> MDXMetadata:
    """Assemble the final ``MDXMetadata`` dict from LLM fields and existing values.

    Values already present in ``existing`` (non-empty, non-None) take precedence
    over derived defaults — this preserves any frontmatter the document already
    carried (e.g. a manually set ``image``).

    Args:
        fields: Title, description, and tags from the LLM or fallback.
        template_name: Used to derive fallback tags when ``fields.tags`` is empty.
        existing: Pre-existing frontmatter from the document, or ``None``.

    Returns:
        Complete ``MDXMetadata`` dict ready to pass to ``render_mdx``.
    """
    tags = fields.tags or _derive_tags(template_name, fields.title)
    metadata: MDXMetadata = {
        "title": fields.title.strip() or "Publication",
        "description": _truncate_description(fields.description) or fields.title,
        "image": _DEFAULT_IMAGE,
        "tags": tags[:5],
        "pubDate": date.today().isoformat(),
        "author": _AUTHOR,
        "draft": True,
    }
    for key, value in (existing or {}).items():
        if _has_metadata_value(value):
            metadata[key] = value  # type: ignore[literal-required]
    return metadata


# ── LangGraph node entry point ────────────────────────────────────────────────

def run(state: PublicationState) -> dict:
    """Design the publication frontmatter from the final humanized body.

    Tries an LLM pass first; falls back to deterministic derivation if the
    model call or JSON parse fails, so the pipeline always produces usable
    frontmatter.

    Reads: humanized, draft, tone, audience, template_name, template_data
    Writes: metadata
    """
    _console.print("  [bright_magenta]Metadata:[/bright_magenta] designing title, description, and tags…")
    source_doc = state.get("humanized") or state.get("draft")
    if not source_doc or not source_doc.get("body"):
        return {"errors": ["Metadata: no document body available to design frontmatter"]}

    body = source_doc["body"]
    template_name = state.get("template_name", "default") or "default"
    template_data = state.get("template_data") or {}
    existing = source_doc.get("metadata") or {}

    errors: list[str] = []
    fields: _MetadataResult | None = None
    try:
        llm = build_model(temperature=0.3)
        json_llm = llm.model_copy(update={"format": "json", "validate_model_on_init": False})
        response = json_llm.invoke([
            SystemMessage(content=_SYSTEM.format(
                frontmatter_guidance=_format_frontmatter_guidance(template_data),
            )),
            HumanMessage(content=_PROMPT.format(
                template_name=template_name,
                tone=state.get("tone", "conversational"),
                audience=state.get("audience", "developers"),
                body=body,
            )),
        ])
        raw = (response.content or "").strip()
        raw = strip_json_fences(raw)
        fields = _MetadataResult(**json.loads(raw))
    except Exception as exc:  # noqa: BLE001 — any failure falls back deterministically
        logger.warning("Metadata: LLM design failed, using deterministic fallback — %s", exc)
        errors.append(f"Metadata: LLM design failed — {exc}")
        fields = _fallback_fields(body, template_name)

    metadata = _assemble(fields, template_name, existing)
    result: dict = {"metadata": metadata}
    if errors:
        result["errors"] = errors
    return result
