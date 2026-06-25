"""MDX document structure — three-part split of a .mdx publication.

Every agent hands off an MDXDocument rather than a raw string so each
stage can edit only what it owns (body, imports, or metadata) without
touching the others.  The final render step merges all three back into a
valid .mdx file.
"""

from __future__ import annotations

import re as _re
from datetime import date as _date, datetime as _datetime
from typing import List

import yaml
from typing_extensions import TypedDict


_DATE_LIKE = _re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Artifact-slot placeholder fences, shared so the writer, visualizer, and publisher
# never drift apart on the format. Two shapes:
#   ID-only      — writer/publisher only need the id to strip or inject by key.
#   ID + context — the visualizer also needs the creation prompt to render the artifact.
#
# The id-only matcher is fence-tolerant: small writer models sometimes drop the ``` fence
# when copying a placeholder, leaving a bare `artifact-slot\nid="..."` block. The optional
# `fence` group with a conditional tail injects/strips by id whether or not the fence
# survived — and the bare branch consumes only its own line, so it never swallows a later
# unrelated code fence. Capture the id by name (`id`) so callers stay group-order agnostic.
ARTIFACT_SLOT_ID_RE = _re.compile(
    r'(?P<fence>```[ \t]*)?artifact-slot[ \t]*\n'
    r'id="(?P<id>[^"]+)"'
    r'(?(fence).*?\n```|[^\n]*)',
    _re.DOTALL,
)
ARTIFACT_SLOT_ID_CONTEXT_RE = _re.compile(
    r'```artifact-slot[ \t]*\nid="([^"]+)"\s+context="([^"]*)".*?\n```',
    _re.DOTALL,
)

# Short placement token the writer drops into the body in place of an artifact-slot fence.
# A single-line `@@artifact:<id>@@` is trivial for a small model to reproduce verbatim —
# unlike a multi-line fence carrying a long context string — and keeps the verbose creation
# prompt out of the draft the reviewer reads. The publisher swaps it for the rendered
# artifact by id; the fence form (ARTIFACT_SLOT_ID_RE) stays as a tolerant backstop.
ARTIFACT_TOKEN_RE = _re.compile(r"@@artifact:(?P<id>[\w-]+)@@")


def _fm_value(value: object) -> str:
    """Serialize a single frontmatter value to Astro-compatible YAML syntax.

    Astro expects specific representations for certain types — booleans as
    bare ``true``/``false``, dates as unquoted ``YYYY-MM-DD``, tag arrays as
    inline ``["a", "b"]``, and strings double-quoted (except date-like strings).

    Args:
        value: The Python value to serialize.

    Returns:
        YAML-compatible string representation with no trailing newline.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (_date, _datetime)):
        return value.isoformat()[:10]          # YYYY-MM-DD, unquoted
    if isinstance(value, list):
        items = ", ".join(
            f'"{v}"' if isinstance(v, str) else str(v)
            for v in value
        )
        return f"[{items}]"
    if isinstance(value, str):
        if _DATE_LIKE.match(value):
            return value                        # date strings stay unquoted
        return f'"{value}"'
    return str(value)


class MDXMetadata(TypedDict, total=False):
    """Typed representation of the YAML frontmatter block."""
    title: str
    description: str
    image: str
    tags: List[str]
    pubDate: str
    author: str
    draft: bool


class MDXDocument(TypedDict):
    """A publication split into its three structural sections."""
    metadata: MDXMetadata   # parsed YAML frontmatter
    imports: List[str]      # import statements, one per item
    body: str               # prose + components + diagrams


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_mdx(content: str) -> MDXDocument:
    """Split a full MDX string into metadata, imports, and body.

    Scanning rules:
    - Frontmatter: everything between the first two bare ``---`` lines.
    - Imports: contiguous ``import ...`` lines (with blank lines between
      them allowed) immediately after the frontmatter.
    - Body: everything after the first non-blank, non-import line.

    Returns a safe fallback (empty metadata, no imports, full content as
    body) when the frontmatter fences are missing.
    """
    lines = content.split("\n")

    fm_start = fm_end = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if fm_start is None:
                fm_start = i
            elif fm_end is None:
                fm_end = i
                break

    if fm_start is None or fm_end is None:
        return MDXDocument(metadata={}, imports=[], body=content.strip())

    fm_text = "\n".join(lines[fm_start + 1 : fm_end])
    try:
        parsed = yaml.safe_load(fm_text) or {}
        metadata: MDXMetadata = parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError:
        metadata = {}

    post_fm = lines[fm_end + 1 :]
    import_lines: List[str] = []
    body_start_idx = len(post_fm)

    for i, line in enumerate(post_fm):
        stripped = line.strip()
        if stripped.startswith("import "):
            import_lines.append(line.rstrip())
        elif stripped == "":
            continue  # blank lines between imports — keep scanning
        else:
            body_start_idx = i
            break

    body = "\n".join(post_fm[body_start_idx:]).strip()

    # Deduplicate while preserving insertion order — LLMs sometimes repeat the same
    # import when the document has multiple artifact placeholders.
    import_lines = list(dict.fromkeys(import_lines))

    return MDXDocument(metadata=metadata, imports=import_lines, body=body)



_EM_DASH_RE = _re.compile(r"[ \t]*—[ \t]*")
_FENCE_SPLIT_RE = _re.compile(r"(```[^\n]*\n.*?\n```)", _re.DOTALL)


def strip_em_dashes(body: str) -> str:
    """Replace em dashes with a comma in prose, leaving fenced code blocks untouched.

    "No em dashes" is an absolute house rule enforced by the writer, reviewer, and
    humanizer prompts. The humanizer is the final prose pass and runs *after* the
    reviewer has approved, so it can reintroduce an em dash that nothing downstream
    checks. This deterministic normalization guarantees the published body honors
    the rule. Code fences are preserved verbatim so code/comments are never altered.

    Idempotent — running twice produces the same output as running once.
    """
    parts = _FENCE_SPLIT_RE.split(body)
    # split() with a capturing group puts fenced blocks at odd indices; rewrite only
    # the prose segments at even indices.
    for i in range(0, len(parts), 2):
        parts[i] = _EM_DASH_RE.sub(", ", parts[i])
    return "".join(parts)


# ── Rendering ─────────────────────────────────────────────────────────────────

def render_mdx(doc: MDXDocument) -> str:
    """Assemble an ``MDXDocument`` into a complete, valid ``.mdx`` file string.

    Output order: frontmatter (``---`` / YAML / ``---``), then import
    statements (omitted when empty), then body. Each present section is
    separated by a single blank line. The result ends with a trailing newline.

    Args:
        doc: The structured document to render.

    Returns:
        A complete ``.mdx`` file string ready to write to disk.
    """
    fm_dict = dict(doc["metadata"])
    if fm_dict:
        fm_lines = ["---"]
        for key, value in fm_dict.items():
            fm_lines.append(f"{key}: {_fm_value(value)}")
        fm_lines.append("---")
        frontmatter = "\n".join(fm_lines)
    else:
        frontmatter = "---\n---"

    parts = [frontmatter]
    if doc["imports"]:
        parts.append("\n".join(doc["imports"]))
    if doc["body"].strip():
        parts.append(doc["body"].strip())

    return "\n\n".join(parts) + "\n"
