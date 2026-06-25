"""Publisher node — renders and saves the final .mdx file.

Reads the final body (from the humanizer) plus the frontmatter designed by the metadata
node, assembles them into a string, injects visual artifacts, and writes the file. This
node performs no content derivation — title/description/tags are the metadata node's job;
the publisher only renders, slugs the filename, and writes to disk.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import List

from rich.console import Console

from src.config import Config
from src.mdx_document import (
    ARTIFACT_SLOT_ID_RE,
    ARTIFACT_TOKEN_RE,
    MDXDocument,
    MDXMetadata,
    render_mdx,
)
from src.state import Artifact, PublicationState

_console = Console()

# Tolerant id-only pattern (shared in mdx_document) — captures the id from any
# artifact-slot fence regardless of how the LLM formatted the content line. Used both
# to inject artifacts by id and to find leftover placeholders after injection.
_PLACEHOLDER_RE = ARTIFACT_SLOT_ID_RE

# Minimal frontmatter used only when the metadata node produced nothing (it normally
# always returns metadata, including its own deterministic fallback).
_FALLBACK_METADATA: MDXMetadata = {
    "title": "Publication",
    "author": "Alberto Duran",
    "draft": True,
}


def _merge_artifact_imports(doc: MDXDocument, artifacts: List[Artifact]) -> MDXDocument:
    """Collect import lines from all artifacts and add any that are not already present.

    Uses a running `seen` set so that identical imports shared across multiple
    artifacts are only added once, not once per artifact.
    """
    if not artifacts:
        return doc
    seen = set(doc["imports"])
    extra: List[str] = []
    for a in artifacts:
        for line in a.get("import_lines", []):
            if line and line not in seen:
                extra.append(line)
                seen.add(line)
    if not extra:
        return doc
    return MDXDocument(
        metadata=doc["metadata"],
        imports=doc["imports"] + extra,
        body=doc["body"],
    )


def _inject_artifacts(content: str, artifacts: List[Artifact]) -> str:
    """Replace artifact tokens and fence placeholders with rendered artifact content.

    Tries the short ``@@artifact:id@@`` token form first, then the tolerant
    fence form as a backstop for when the writer copied the outline fence
    instead of emitting a token.

    Args:
        content: The assembled MDX string before injection.
        artifacts: List of rendered artifacts from the visualizer.

    Returns:
        The content string with every matched placeholder replaced by the
        corresponding artifact's rendered body.
    """
    if not artifacts:
        return content
    lookup = {a["id"]: a["content"] for a in artifacts}
    replace = lambda m: lookup.get(m.group("id"), m.group(0))  # noqa: E731
    # Primary form is the `@@artifact:id@@` token; the fence form is the tolerant backstop
    # for when the writer copied the outline fence instead of emitting a token.
    content = ARTIFACT_TOKEN_RE.sub(replace, content)
    content = _PLACEHOLDER_RE.sub(replace, content)
    return content


def _strip_remaining_placeholders(content: str) -> tuple[str, list[str]]:
    """Remove any ARTIFACT_PLACEHOLDER that survived injection (no artifact or regex failure).

    Returns (cleaned_content, list_of_stripped_ids).
    """
    stripped: list[str] = []

    def _remove(m: re.Match) -> str:
        stripped.append(m.group("id"))
        return ""

    cleaned = ARTIFACT_TOKEN_RE.sub(_remove, content)
    cleaned = _PLACEHOLDER_RE.sub(_remove, cleaned)
    return cleaned, stripped


def _slug_from_metadata(metadata: MDXMetadata) -> str:
    """Derive a URL-safe filename slug from the publication title.

    Lowercases, strips non-alphanumeric characters, collapses whitespace and
    underscores to hyphens, and trims to 50 characters.

    Returns:
        A slug string suitable for use as a filename stem.
    """
    title = str(metadata.get("title", "publication")).strip().strip('"').strip("'")
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50]


def _save(content: str, metadata: MDXMetadata, output_dir: Path, run_id: str = "") -> str:
    """Write the final MDX string to disk and return the absolute path.

    Filename format: ``<run_id>-<date>-<slug>.mdx`` when ``run_id`` is set,
    or ``<date>-<slug>.mdx`` otherwise. The output directory is created if it
    does not exist.

    Returns:
        Absolute path of the written file as a string.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug_from_metadata(metadata)
    prefix = f"{run_id}-" if run_id else ""
    filename = f"{prefix}{date.today().isoformat()}-{slug}.mdx"
    path = output_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def run(state: PublicationState) -> dict:
    """Render and save the final ``.mdx`` file from the humanized document.

    Merges artifact imports, injects rendered artifact content, strips any
    unresolved placeholders, and writes the file to the configured output
    directory.

    Reads: humanized, metadata, artifacts, run_id
    Writes: final_publication, output_path
    """
    _console.print("  [cyan]Publisher:[/cyan] rendering and saving final file…")
    cfg = Config()

    source_doc: MDXDocument | None = state.get("humanized")
    if not source_doc or not source_doc.get("body"):
        return {"errors": ["Publisher: no humanized document available — pipeline produced no output"]}

    metadata = state.get("metadata")
    if not metadata:
        _console.print("  [yellow]Publisher:[/yellow] no metadata from metadata node — using minimal fallback")
        metadata = dict(_FALLBACK_METADATA)

    artifacts = state.get("artifacts") or []
    doc = MDXDocument(metadata=metadata, imports=source_doc["imports"], body=source_doc["body"])
    merged_doc = _merge_artifact_imports(doc, artifacts)
    final_str = render_mdx(merged_doc)
    final_str = _inject_artifacts(final_str, artifacts)

    # Remove any placeholder that survived injection — never write them to disk.
    final_str, leftover = _strip_remaining_placeholders(final_str)
    if leftover:
        _console.print(
            f"  [yellow]Publisher:[/yellow] stripped {len(leftover)} unresolved "
            f"placeholder(s) from final output: {', '.join(leftover)}"
        )

    output_path = _save(final_str, merged_doc["metadata"], cfg.output_dir, state.get("run_id", ""))

    return {
        "final_publication": final_str,
        "output_path": output_path,
    }
