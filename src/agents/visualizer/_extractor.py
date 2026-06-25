"""Extractor agent — turns a visual template's data bindings into resolved values.

A binding is either:

  * a **static spec** in the ``_databind`` grammar (``file:path[?last=N]`` or
    ``file:[p1, p2, …]``) — resolved deterministically, no LLM; or
  * a **human intent** (free text, e.g. "last 3 months of daily close prices") — an LLM
    step converts the intent into a static spec *against the live JSON schema*, which is
    then resolved deterministically.

The LLM only ever *locates* data (proposes a path); it never authors a value. A proposed
spec that does not resolve fails loudly and is dropped — the contract everywhere in this
pipeline is degrade, never fabricate.

Called by the specialized renderers in the visualizer when a slot uses a template.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.visuals.registry import VisualTemplate
from ._databind import resolve_spec

# A static spec starts with a known input filename followed by ``:`` (path or [paths]).
_SPEC_RE = re.compile(r"^[\w./-]+\.(?:json|md|mdx|txt)\s*:", re.IGNORECASE)


def looks_like_spec(expr: str) -> bool:
    """True when ``expr`` is already a deterministic ``file:path`` spec (no LLM needed)."""
    return bool(_SPEC_RE.match(expr.strip()))


# ── intent resolution (LLM proposes a path; the value is still read deterministically) ──

_INTENT_SYSTEM = """\
You translate a data request into a single extraction spec. You do NOT output data values.

Output EXACTLY one line in this grammar and nothing else:
  <file>:<dotted.json.path>
  <file>:<dotted.json.path>?last=N        (keep only the last N items of an array)
  <file>:[<path_a>, <path_b>, ...]         (assemble one array from several paths, in order)

Rules:
- <file> must be one of the listed input files. <path> must be an exact path that exists
  in that file's schema below. Use array indices like items[0].field when needed.
- Choose the path whose value matches the requested type. Never invent a path.
- Output the spec line only — no prose, no backticks, no explanation.
"""

_INTENT_PROMPT = """\
INPUT FILES AND SCHEMA:
{schema}

SLOT: {slot}  (expected type: {slot_type})
REQUEST: {intent}

Output the single extraction spec line now.
"""


def _schema_digest(input_dir: str | Path | None) -> str:
    """Build a compact two-level schema summary of the input JSON files.

    Used as context for the intent-to-spec LLM call so the model can propose
    exact paths rather than guessing.

    Args:
        input_dir: Directory to search for ``*.json`` files. Defaults to
            ``"input"`` when ``None``.

    Returns:
        Multi-line string listing each JSON file with its top-level keys and
        each dict child's keys. Returns ``"(no JSON input files)"`` when the
        directory contains none.
    """
    root = Path(input_dir) if input_dir else Path("input")
    lines: list[str] = []
    for path in sorted(root.glob("*.json")):
        lines.append(f"- {path.name}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            lines.append(f"    keys: {', '.join(data.keys())}")
            for k, v in data.items():
                if isinstance(v, dict) and v:
                    lines.append(f"    {k} -> {', '.join(v.keys())}")
    return "\n".join(lines) if lines else "(no JSON input files)"


def _intent_to_spec(slot: str, slot_type: str, intent: str, input_dir, llm) -> str:
    """Convert a human-readable data intent into a deterministic ``file:path`` spec.

    The LLM receives the JSON schema digest and the intent, and returns a single
    spec line. The spec is then resolved deterministically by ``resolve_spec`` —
    the LLM only *locates* data, never authors a value.

    Args:
        slot: The template slot name (for logging and prompt context).
        slot_type: Expected value type hint from the template (e.g. ``"number"``).
        intent: Free-text description of the desired data
            (e.g. ``"last 63 daily close prices"``).
        input_dir: Input directory passed to ``_schema_digest``.
        llm: Base model instance; copied with ``temperature=0.0``.

    Returns:
        A single ``file:path`` spec line, or ``""`` if the model returns nothing.
    """
    cold = llm.model_copy(update={"temperature": 0.0, "validate_model_on_init": False})
    from src.llm import invoke_with_retry  # local import keeps test patching simple

    raw = invoke_with_retry(cold, [
        SystemMessage(content=_INTENT_SYSTEM),
        HumanMessage(content=_INTENT_PROMPT.format(
            schema=_schema_digest(input_dir), slot=slot,
            slot_type=slot_type or "any", intent=intent,
        )),
    ])
    return raw.strip().splitlines()[0].strip() if raw.strip() else ""


# ── public entry point ──────────────────────────────────────────────────────

def _apply_transform(value: Any, spec: dict) -> Any:
    """Scale and/or round a numeric value (or list of numbers) deterministically.

    ``{scale: 1e-9, round: 1}`` turns 31_352_000_000 into 31.4. Non-numeric values pass
    through untouched, so a transform on a string slot is a harmless no-op.
    """
    scale = spec.get("scale")
    digits = spec.get("round")

    def _one(x: Any) -> Any:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return x
        if scale is not None:
            x = x * scale
        if digits is not None:
            x = round(x, digits)
        return x

    return [_one(x) for x in value] if isinstance(value, list) else _one(value)


def resolve(
    template: VisualTemplate,
    bind: dict[str, str],
    input_dir: str | Path | None,
    llm: Any = None,
    transforms: dict[str, dict] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve every ``extract`` slot of ``template`` from ``bind`` into ``{slot: value}``.

    Returns ``(data, errors)``. A slot whose binding is missing, mis-typed, or fails to
    resolve is dropped and recorded in ``errors``; resolution continues for the rest.

    ``transforms`` maps a slot to ``{scale, round}`` applied after resolution; a slot's
    template-declared ``extract.<slot>.transform`` is the default, overridden per use.
    """
    errors: list[str] = []
    specs: dict[str, str] = {}

    for slot in template.extract:
        expr = (bind.get(slot) or "").strip()
        if not expr:
            errors.append(f"{template.id}: slot {slot!r} has no binding")
            continue
        if looks_like_spec(expr):
            specs[slot] = expr
            continue
        # Human intent — needs the LLM to locate it deterministically.
        if llm is None:
            errors.append(
                f"{template.id}: slot {slot!r} binding is an intent but no model is "
                f"available to resolve it: {expr!r}"
            )
            continue
        slot_type = (template.extract.get(slot) or {}).get("type", "")
        try:
            spec = _intent_to_spec(slot, slot_type, expr, input_dir, llm)
        except Exception as exc:  # noqa: BLE001 — degrade on any LLM failure
            errors.append(f"{template.id}: slot {slot!r} intent resolution failed — {exc}")
            continue
        if not looks_like_spec(spec):
            errors.append(
                f"{template.id}: slot {slot!r} intent did not yield a valid spec "
                f"(got {spec!r})"
            )
            continue
        specs[slot] = spec

    if not specs:
        return {}, errors

    combined = "; ".join(f"{slot}={spec}" for slot, spec in specs.items())
    resolved, bind_errors = resolve_spec(combined, input_dir)
    errors.extend(f"{template.id}: {e}" for e in bind_errors)

    # Drop synthetic *_labels entries — render computes its own labels from the template.
    data = {k: v for k, v in resolved.items() if not k.endswith("_labels")}

    # Apply transforms: template-declared default, overridden per-use by `transforms`.
    transforms = transforms or {}
    for slot in template.extract:
        if slot not in data:
            continue
        spec = dict((template.extract.get(slot) or {}).get("transform") or {})
        spec.update(transforms.get(slot) or {})
        if spec:
            data[slot] = _apply_transform(data[slot], spec)

    return data, errors


__all__ = ["resolve", "looks_like_spec"]
