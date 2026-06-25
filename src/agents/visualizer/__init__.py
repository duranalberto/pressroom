"""Visualizer — orchestrator node.

Extracts ARTIFACT_PLACEHOLDER markers from the outline, classifies each by artifact
type (mermaid / echart / ui), delegates rendering to the matching sub-agent, then
assembles and returns Artifact objects for the rest of the pipeline.

Sub-agents (each returns a raw MDX string):
  _mermaid  — fenced ```mermaid diagram source     (temperature 0.3)
  _echart   — fenced ```echart JSON, template-filled (deterministic)
  _ui       — fenced ```daisyui JSON (freeform or template-filled) (temperature 0.5)

The orchestrator owns:
  - Placeholder extraction and routing
  - Import / body splitting (_split_imports) — fences carry no imports, so this is a no-op
    for compliant output and a guard against a stray legacy import
  - Fence JSON validation (_validate_artifact)
  - One correction retry when validation finds issues
  - Artifact assembly and state return
"""

from __future__ import annotations

import json
import re
from typing import List, Literal

from rich.console import Console

from src.llm import build_model
from src.state import Artifact, PublicationState
from src.visuals import registry
from . import _echart, _extractor, _mermaid, _ui
from ._databind import Slot, parse_inline_params, parse_slots, substitute_data_tokens

_console = Console()

# ---------------------------------------------------------------------------
# Classification (freeform fallback routing)
# ---------------------------------------------------------------------------

_MERMAID_KEYWORDS = frozenset({
    "mermaid",
    "flowchart",
    "sequencediagram",
    "statediagram",
    "erdiagram",
    "classdiagram",
    "gantt",
    "mindmap",
    "graph td",
    "graph tb",
    "graph lr",
})

_ECHART_KEYWORDS = frozenset({
    "echart",
    "echarts",
    "linechartoption",
    "barchartoption",
    "piechartoption",
    "scatterchartoption",
    "histogramchartoption",
    "heatmapchartoption",
    "treemapchartoption",
    "sankeychartoption",
    "boxplotchartoption",
    "candlestickwithvolumeoption",
    "depthchartoption",
    "orderbookchartoption",
    "correlationheatmapchartoption",
    "macdchartoption",
    "rsichartoption",
    "bollingerbandschartoption",
    "ohlcchartoption",
})

ArtifactType = Literal["mermaid", "echart", "ui"]

_TYPE_LABEL: dict[ArtifactType, str] = {
    "mermaid": "mermaid",
    "echart": "echart",
    "ui": "ui-component",
}

# Freeform (LLM-authored) renderers. EChart is intentionally absent: charts are
# template-only now, so an echart slot without a template degrades rather than being
# hand-authored by the model.
_RENDERERS: dict[str, object] = {
    "mermaid": _mermaid.render,
    "ui": _ui.render,
}

# Templated (deterministic) renderers, keyed by a visual template's `kind`.
_TEMPLATED_RENDERERS: dict[str, object] = {
    "echart": _echart.render_template,
    "ui": _ui.render_template,
}


def _classify_artifact(context: str) -> ArtifactType:
    """Classify an artifact by scanning the context string for domain keywords.

    Returns 'mermaid' or 'echart' when a recognised keyword is found; falls back
    to 'ui' (the safest default — the UI sub-agent handles all component types).
    """
    lower = context.lower()
    if any(k in lower for k in _MERMAID_KEYWORDS):
        return "mermaid"
    if any(k in lower for k in _ECHART_KEYWORDS):
        return "echart"
    return "ui"


# ---------------------------------------------------------------------------
# Shared post-processing helpers (also exported for tests)
# ---------------------------------------------------------------------------

def _split_imports(raw: str) -> tuple[list[str], str]:
    """Separate leading import lines from the component body.

    Returns (import_lines, body) where body is everything after the last
    contiguous import block at the top of the output.
    """
    lines = raw.strip().split("\n")
    import_lines: list[str] = []
    body_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import "):
            import_lines.append(line.rstrip())
        elif stripped == "":
            continue  # blank lines between imports — keep scanning
        else:
            body_start = i
            break

    body = "\n".join(lines[body_start:]).strip()
    return import_lines, body


# Matches the component name from any opening JSX tag, e.g. <Callout or <List.
# Excludes closing tags (</…>) and HTML lowercase tags. A capital-letter tag in a compliant
# artifact means the author emitted a JSX component instead of a fence — a hard error now.
_JSX_OPEN_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9]*)")

# A rendered visual fence carrying JSON (echart or daisyui). Mermaid fences hold Mermaid
# source, not JSON, and are validated at render time — not here.
_JSON_FENCE_RE = re.compile(r"```(echart|daisyui)[ \t]*\n(.*?)\n```", re.DOTALL)

# Any fenced block, used to blank out fence bodies before scanning the surrounding prose for
# stray JSX or imports (so a `<` or `import` inside a fence's JSON never false-positives).
_ANY_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _validate_echart_fence(obj: dict) -> list[str]:
    """Structural checks for one parsed ``echart`` fence object."""
    issues: list[str] = []
    if not obj.get("type"):
        issues.append('echart fence: missing "type"')
    figure = obj.get("figure")
    if not (isinstance(figure, dict) and str(figure.get("description", "")).strip()):
        issues.append(
            "echart fence: figure.description is required and must be non-empty "
            "(it is the accessible chart summary and the no-JS fallback)"
        )
    data = obj.get("data")
    if isinstance(data, dict):
        x, y = data.get("x"), data.get("y")
        if isinstance(x, list) and isinstance(y, list) and len(x) != len(y):
            issues.append(
                f"echart fence: data.x has {len(x)} label(s) but data.y has {len(y)} "
                f"value(s) — x and y must be the same length"
            )
    return issues


def _validate_daisyui_fence(obj: dict) -> list[str]:
    """Structural checks for one parsed ``daisyui`` fence object."""
    if not obj.get("component"):
        return ['daisyui fence: missing "component"']
    return []


def _validate_artifact(artifact_id: str, content: str, import_lines: list[str]) -> list[str]:
    """Return structural issues found in a generated visual artifact.

    Compliant artifacts are fenced blocks — ``echart``/``daisyui`` carry a JSON object and
    ``mermaid`` carries diagram source, none of them import anything. Checks:
    - Every echart/daisyui fence body parses as a JSON object with its required fields.
    - echart ``data.x`` and ``data.y`` (when both present) have matching lengths.
    - No leftover JSX component tag or import line (the fence contract needs neither).
    - No HTML comment, which is invalid in MDX.
    Mermaid syntax errors surface at render time and are not caught here.
    """
    issues: list[str] = []

    for m in _JSON_FENCE_RE.finditer(content):
        lang, body = m.group(1), m.group(2)
        try:
            obj = json.loads(body)
        except json.JSONDecodeError as exc:
            issues.append(f"```{lang} fence is not valid JSON — {exc.msg} (line {exc.lineno})")
            continue
        if not isinstance(obj, dict):
            issues.append(f"```{lang} fence must contain a JSON object")
            continue
        issues.extend(
            _validate_echart_fence(obj) if lang == "echart" else _validate_daisyui_fence(obj)
        )

    outside_fences = _ANY_FENCE_RE.sub("", content)
    for comp in sorted({m.group(1) for m in _JSX_OPEN_TAG_RE.finditer(outside_fences)}):
        issues.append(
            f"{comp} appears as a JSX component — emit a fenced ```daisyui or ```echart "
            f"block containing a JSON object instead (no components, no imports)"
        )

    if import_lines or re.search(r"(?m)^\s*import\s", outside_fences):
        issues.append(
            "contains an import statement — fenced visuals need no imports; remove it"
        )

    if "<!--" in content:
        issues.append(
            "contains an HTML comment <!-- --> which is invalid in MDX — remove it"
        )

    return issues


# ---------------------------------------------------------------------------
# Per-artifact generation (orchestrator logic)
# ---------------------------------------------------------------------------

def _prepare(artifact_id: str, raw: str, resolved: dict) -> tuple[list[str], str]:
    """Split imports and substitute resolved data tokens into one render."""
    import_lines, body = _split_imports(raw)
    if resolved:
        body, unresolved = substitute_data_tokens(body, resolved)
        for name in unresolved:
            _console.print(
                f"    [yellow]⚠ {artifact_id}: unresolved data token @@data:{name}@@ "
                f"— stripped[/yellow]"
            )
    return import_lines, body


def _generate_artifact(
    artifact_id: str,
    context: str,
    artifact_type: ArtifactType,
    llm,
) -> Artifact:
    """Freeform (LLM-authored) generation for mermaid and UI slots without a template."""
    render = _RENDERERS[artifact_type]

    raw = render(artifact_id, context, llm)
    import_lines, body = _prepare(artifact_id, raw, {})
    issues = _validate_artifact(artifact_id, body, import_lines)

    if issues:
        for issue in issues:
            _console.print(f"    [yellow]⚠ {artifact_id}: {issue}[/yellow]")

        fix_context = (
            context.strip()
            + "\n\nFIX REQUIRED before outputting:\n"
            + "\n".join(f"- {i}" for i in issues)
        )
        corrected = render(artifact_id, fix_context, llm)
        import_lines, body = _prepare(artifact_id, corrected, {})

        remaining = _validate_artifact(artifact_id, body, import_lines)
        for issue in remaining:
            _console.print(f"    [red]✗ {artifact_id}: {issue} (persists after correction)[/red]")
        if remaining:
            raise ValueError(
                f"{artifact_id}: validation failed after correction — "
                + "; ".join(remaining)
            )

    return Artifact(id=artifact_id, content=body, import_lines=import_lines)


# ---------------------------------------------------------------------------
# Templated generation (deterministic — code fills the option object / JSX)
# ---------------------------------------------------------------------------

def _visuals_config(state: PublicationState) -> dict[str, dict]:
    """Build a lookup of preconfigured visual entries keyed by their id.

    Returns:
        Dict mapping each visual's ``id`` string to its full config dict from
        the template's ``visuals`` list. Returns ``{}`` when none are configured.
    """
    visuals = (state.get("template_data") or {}).get("visuals") or []
    out: dict[str, dict] = {}
    for entry in visuals:
        if isinstance(entry, dict) and entry.get("id"):
            out[str(entry["id"])] = entry
    return out


def _generate_templated(
    slot: Slot,
    cfg: dict,
    template_id: str,
    input_dir: str,
    llm,
) -> tuple[Artifact | None, list[str]]:
    """Resolve data and deterministically render one templated slot.

    Returns ``(artifact_or_None, errors)``. Any failure degrades to ``None`` plus an error
    string so the orchestrator can skip the artifact (the publisher strips the placeholder)
    rather than ship a broken or invented visual.
    """
    vt = registry.get(template_id)
    if vt is None:
        return None, [f"{slot.id}: unknown visual template {template_id!r}"]

    params = dict(cfg.get("params") or {})
    params.update(parse_inline_params(slot.params))  # inline fence overrides win
    bind = dict(cfg.get("bind") or {})
    transforms = cfg.get("transform") or {}

    data, errors = _extractor.resolve(vt, bind, input_dir, llm, transforms=transforms)
    missing = [s for s in vt.extract if s not in data]
    if missing:
        errors.append(f"{slot.id}: unresolved data slot(s): {', '.join(missing)}")
        return None, errors

    renderer = _TEMPLATED_RENDERERS.get(vt.kind)
    if renderer is None:
        return None, errors + [f"{slot.id}: no templated renderer for kind {vt.kind!r}"]

    try:
        import_lines, body = renderer(vt, data, params)
    except Exception as exc:  # noqa: BLE001 — degrade on any render error
        return None, errors + [f"{slot.id}: render failed — {exc}"]

    issues = _validate_artifact(slot.id, body, import_lines)
    if issues:
        return None, errors + [f"{slot.id}: {i}" for i in issues]

    return Artifact(id=slot.id, content=body, import_lines=import_lines), errors


# ---------------------------------------------------------------------------
# Outline reconciliation — guarantee every configured visual reaches the writer
# ---------------------------------------------------------------------------

def _visual_fence(visual_id: str, cfg: dict) -> str:
    """Build the artifact-slot fence string for a preconfigured visual.

    Returns:
        A ` ```artifact-slot … ``` ` block carrying ``id`` and ``template``
        attributes, ready to inject into the outline.
    """
    template = cfg.get("template", "")
    return f'```artifact-slot\nid="{visual_id}" template="{template}"\n```'


def _section_title(template_data: dict, section_id: str) -> str:
    """Resolve a template section id to its heading title for fence insertion.

    Args:
        template_data: Loaded template dict.
        section_id: The ``id`` value from a visual config's ``section`` key.

    Returns:
        The section's ``title`` string, or ``""`` if the id is not found.
    """
    from src.template_config import outline_structure
    for section in outline_structure(template_data):
        if isinstance(section, dict) and section.get("id") == section_id:
            return (section.get("title") or "").strip()
    return ""


def _insert_fence(outline: str, fence: str, title: str) -> str:
    """Insert ``fence`` immediately after the first heading matching ``title``.

    Falls back to appending the fence at the end of the outline when ``title``
    is empty or no matching heading is found.

    Args:
        outline: Current outline text.
        fence: The artifact-slot fence block to insert.
        title: Heading text to search for (case-insensitive substring match).

    Returns:
        Updated outline string with the fence inserted.
    """
    if title:
        lines = outline.split("\n")
        for i, line in enumerate(lines):
            if line.lstrip().startswith("#") and title.lower() in line.lower():
                lines.insert(i + 1, f"\n{fence}\n")
                return "\n".join(lines)
    return outline.rstrip() + f"\n\n{fence}\n"


def _reconcile_visuals(
    outline: str,
    slots: list[Slot],
    visuals_cfg: dict[str, dict],
    template_data: dict,
) -> tuple[str, list[Slot], bool]:
    """Ensure every configured visual is present as a slot; inject any the outline missed.

    The visualizer runs before the writer, so an updated outline (with injected fences) is
    what the writer copies into the body — the visual is never silently lost to an outline
    that forgot to place it.
    """
    present = {s.id for s in slots}
    new_slots = list(slots)
    injected = False
    for vid, cfg in visuals_cfg.items():
        if vid in present:
            continue
        outline = _insert_fence(
            outline, _visual_fence(vid, cfg), _section_title(template_data, cfg.get("section", ""))
        )
        new_slots.append(Slot(id=vid, template=cfg.get("template", "")))
        injected = True
        _console.print(f"    [dim]+ injected configured visual '{vid}' into the outline[/dim]")
    return outline, new_slots, injected


# ---------------------------------------------------------------------------
# LangGraph node entry point
# ---------------------------------------------------------------------------

def run(state: PublicationState) -> dict:
    """Generate all visual artifacts declared in the outline.

    Reconciles preconfigured visuals from the template with slots found in the
    outline, then renders each slot via the templated or freeform path. Failed
    slots are recorded in ``errors`` and their placeholders are later stripped
    by the publisher rather than shipping broken output.

    Reads: outline, template_data, input_dir
    Writes: artifacts, outline (only when fences were injected), errors
    """
    outline = state.get("outline", "")
    template_data = state.get("template_data") or {}
    slots = parse_slots(outline)

    # Make sure every visual the publication template preconfigured is placed, even if the
    # outline forgot it. This may rewrite the outline the writer later copies from.
    visuals_cfg = _visuals_config(state)
    outline, slots, outline_injected = _reconcile_visuals(
        outline, slots, visuals_cfg, template_data
    )

    if not slots:
        _console.print("  [blue]Visualizer:[/blue] no artifact placeholders in outline — skipping.")
        return {"outline": outline} if outline_injected else {}

    _console.print(f"  [blue]Visualizer:[/blue] generating {len(slots)} visual artifact(s)…")

    input_dir = state.get("input_dir") or "input"
    llm = build_model()
    artifacts: List[Artifact] = []

    failed: list[str] = []
    errors: list[str] = []

    for slot in slots:
        cfg = visuals_cfg.get(slot.id, {})
        template_id = slot.template or cfg.get("template", "")

        if template_id:
            # Templated path — deterministic, no LLM authoring.
            _console.print(f"    [dim]→ {slot.id}  [template: {template_id}][/dim]")
            artifact, slot_errors = _generate_templated(slot, cfg, template_id, input_dir, llm)
            for err in slot_errors:
                _console.print(f"    [yellow]⚠ {err}[/yellow]")
                errors.append(f"Visualizer: {err}")
            if artifact is None:
                _console.print(f"    [red]✗ {slot.id}: skipped[/red]")
                failed.append(slot.id)
                continue
            artifacts.append(artifact)
            _console.print(
                f"    [dim]  {len(artifact['import_lines'])} import(s), "
                f"{len(artifact['content'])} chars[/dim]"
            )
            continue

        # Freeform path — mermaid/UI only. EChart requires a template.
        artifact_type = _classify_artifact(slot.context)
        if artifact_type == "echart":
            msg = (f"{slot.id}: an echart chart needs a visual template "
                   f"(reference one with template=\"...\") — skipped")
            _console.print(f"    [red]✗ {msg}[/red]")
            errors.append(f"Visualizer: {msg}")
            failed.append(slot.id)
            continue

        _console.print(f"    [dim]→ {slot.id}  [{_TYPE_LABEL[artifact_type]}][/dim]")
        try:
            artifact = _generate_artifact(slot.id, slot.context, artifact_type, llm)
        except Exception as exc:
            _console.print(f"    [red]✗ {slot.id}: generation failed — {exc}[/red]")
            failed.append(slot.id)
            continue

        artifacts.append(artifact)
        _console.print(
            f"    [dim]  {len(artifact['import_lines'])} import(s), "
            f"{len(artifact['content'])} chars[/dim]"
        )

    if failed:
        _console.print(
            f"  [yellow]Visualizer:[/yellow] {len(failed)} artifact(s) failed — "
            f"placeholders will be stripped by publisher: {', '.join(failed)}"
        )
        errors.extend(f"Visualizer: artifact '{f}' failed to generate" for f in failed)

    result: dict = {"artifacts": artifacts}
    if outline_injected:
        result["outline"] = outline
    if errors:
        result["errors"] = errors
    return result
