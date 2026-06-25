"""Deterministic render-fill for visual templates.

Substitutes the four token namespaces in a template's ``render`` string with concrete
literals. No LLM is involved — given the same template, params, and extracted data, the
output is byte-identical.

Token namespaces (all placed BARE in the template — the substitution emits the full
literal, so the template author never wraps a token in quotes or brackets):

    @@data:<slot>@@    an extracted value/array         -> JSON literal (e.g. [1, 2, 3])
    @@param:<name>@@   an author param (after defaults)  -> JSON literal (e.g. "Buy", true)
    @@label:<name>@@   a computed axis-label array       -> JSON literal
    @@text:<name>@@    a value used as JSX prose/children -> raw, escaped for MDX
    @@str:<name>@@     a value interpolated INSIDE a JSON -> JSON-string body, no quotes
                       string (e.g. a fence's "content")    (e.g. Buy -> Buy, a\"b -> a\\\"b)

A token whose value cannot be resolved is a template/config error: rendering raises so the
orchestrator skips the artifact rather than shipping one with a hole where a value belongs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .registry import VisualTemplate

_TOKEN_RE = re.compile(r"@@(data|param|label|text|str):([\w-]+)@@")

_MISSING = object()


class VisualRenderError(Exception):
    """Raised when a template cannot be rendered (missing param, data, or label)."""


def synth_labels(n: int) -> list[str]:
    """Generate sequential trading-day offset labels for an n-point series.

    Labels count backwards from the most recent point: a series of length 3
    yields ``["D-2", "D-1", "D-0"]``.

    Args:
        n: Number of data points in the series.

    Returns:
        List of ``n`` label strings in chronological order.
    """
    return [f"D-{n - 1 - i}" for i in range(n)]


def _window_labels(n: int, start: str, end: str) -> list[str]:
    """Label only the endpoints of a series; leave interior points blank.

    Avoids a row of meaningless per-point axis ticks when the data has no
    evenly-spaced dates (e.g. a filtered price history where gaps exist).

    Args:
        n: Total number of data points.
        start: Label for the first point (oldest).
        end: Label for the last point (most recent).

    Returns:
        List of ``n`` strings: ``[start, "", "", …, end]``. Returns ``[]``
        when ``n == 0``; returns ``[end or start]`` when ``n == 1``.
    """
    if n <= 0:
        return []
    if n == 1:
        return [end or start]
    return [start] + [""] * (n - 2) + [end]


def _escape_text(value: str) -> str:
    """Escape MDX/JSX-significant characters so a string is safe in component children.

    Replaces ``{``, ``}``, and ``<`` with HTML entities. Applied only to
    ``@@text:…@@`` tokens — ``@@data:…@@`` and ``@@param:…@@`` tokens are
    JSON-encoded and safe by construction.
    """
    return (
        value.replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace("<", "&lt;")
    )


def _merge_params(template: VisualTemplate, params: dict[str, Any]) -> dict[str, Any]:
    """Merge caller-supplied params over template defaults.

    Args:
        template: The visual template providing the param schema and defaults.
        params: Author-supplied overrides from the publication template or fence.

    Returns:
        Dict of resolved param values (defaults filled in, caller values on top).

    Raises:
        VisualRenderError: If any param marked ``required: true`` is still
            missing after merging.
    """
    merged: dict[str, Any] = {}
    for name, spec in template.params.items():
        if isinstance(spec, dict) and "default" in spec:
            merged[name] = spec["default"]
    merged.update({k: v for k, v in params.items() if v is not None})

    missing = [n for n in template.required_params() if n not in merged]
    if missing:
        raise VisualRenderError(
            f"{template.id}: missing required param(s): {', '.join(sorted(missing))}"
        )
    return merged


def _compute_derived(
    template: VisualTemplate, data: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Compute params whose value is derived from a data slot via a value map.

    Each entry in ``template.derive`` names a target param and a ``from`` source
    (a data slot, falling back to a param). The source value is looked up in the
    ``map`` (string-keyed); a ``default`` is used when the value is missing or
    unmapped. This lets a template pick, say, a Callout ``variant`` from a
    Buy/Hold/Sell ``recommendation`` deterministically.

    Args:
        template: Visual template with an optional ``derive`` schema.
        data: Resolved data slot values.
        params: Merged author params (defaults + caller).

    Returns:
        Dict mapping each derived param name to its computed value. Entries with
        no mapping match and no ``default`` are omitted.
    """
    derived: dict[str, Any] = {}
    for name, spec in (template.derive or {}).items():
        spec = spec or {}
        source = spec.get("from")
        if source in data:
            value = data[source]
        elif source in params:
            value = params[source]
        else:
            value = None
        mapping = spec.get("map") or {}
        if value is not None and str(value) in mapping:
            derived[name] = mapping[str(value)]
        elif "default" in spec:
            derived[name] = spec["default"]
    return derived


def _compute_labels(
    template: VisualTemplate, data: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Compute all declared axis labels for a template.

    Each label in ``template.labels`` specifies a ``from`` rule:
    ``sequential`` (offset labels matching a data series length),
    ``window`` (endpoint-only labels for a dense series),
    ``param`` (reads a named author param), or ``static`` (literal value).

    Args:
        template: Visual template with a ``labels`` schema.
        data: Resolved data slot values.
        params: Merged author params (from ``_merge_params``).

    Returns:
        Dict mapping each label name to its computed value (usually a list of strings).

    Raises:
        VisualRenderError: If a referenced data slot or param is missing, or
            a label specifies an unknown ``from`` source.
    """
    labels: dict[str, Any] = {}
    for name, spec in template.labels.items():
        spec = spec or {}
        source = spec.get("from")
        if source == "sequential":
            of = spec.get("of")
            series = data.get(of)
            if not isinstance(series, list):
                raise VisualRenderError(
                    f"{template.id}: label {name!r} needs a list at data slot {of!r}"
                )
            labels[name] = synth_labels(len(series))
        elif source == "window":
            # Label only the endpoints of a long ordered series; blank the middle. Avoids a
            # row of meaningless per-point ticks when the data has no real axis (e.g. dates).
            of = spec.get("of")
            series = data.get(of)
            if not isinstance(series, list):
                raise VisualRenderError(
                    f"{template.id}: label {name!r} needs a list at data slot {of!r}"
                )
            labels[name] = _window_labels(
                len(series), str(spec.get("start", "")), str(spec.get("end", ""))
            )
        elif source == "data":
            # Labels come straight from a resolved data slot (e.g. category names that were
            # extracted from the input rather than supplied as a static param).
            of = spec.get("of")
            series = data.get(of)
            if not isinstance(series, list):
                raise VisualRenderError(
                    f"{template.id}: label {name!r} needs a list at data slot {of!r}"
                )
            labels[name] = series
        elif source == "param":
            value = params.get(spec.get("name"))
            if value is None:
                raise VisualRenderError(
                    f"{template.id}: label {name!r} reads missing param {spec.get('name')!r}"
                )
            labels[name] = value
        elif source == "static":
            labels[name] = spec.get("value")
        else:
            raise VisualRenderError(
                f"{template.id}: label {name!r} has unknown source {source!r}"
            )
    return labels


def render_visual(
    template: VisualTemplate,
    *,
    data: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """Render a visual template to ``(import_lines, body)``.

    ``data`` holds the extracted values keyed by the template's ``extract`` slot names.
    ``params`` holds author-supplied values; template defaults fill the rest.
    """
    params = params or {}
    merged_params = _merge_params(template, params)
    # Derived params fill in values computed from the data (e.g. a Callout variant from the
    # recommendation), but an explicit caller-supplied value always wins over a derived one.
    for name, value in _compute_derived(template, data, merged_params).items():
        if name not in params:
            merged_params[name] = value
    labels = _compute_labels(template, data, merged_params)

    unresolved: list[str] = []

    def _lookup(namespace: str, name: str) -> Any:
        if namespace == "data":
            return data.get(name, _MISSING)
        if namespace == "param":
            return merged_params.get(name, _MISSING)
        if namespace == "label":
            return labels.get(name, _MISSING)
        # text: a value used as prose — try data first, then params
        if name in data:
            return data[name]
        return merged_params.get(name, _MISSING)

    def _replace(m: re.Match) -> str:
        namespace, name = m.group(1), m.group(2)
        value = _lookup(namespace, name)
        if value is _MISSING:
            unresolved.append(f"{namespace}:{name}")
            return m.group(0)
        if namespace == "text":
            return _escape_text(str(value))
        if namespace == "str":
            # Interpolated inside an existing JSON string (e.g. a fence's "content"):
            # emit the JSON-escaped body without the surrounding quotes so it drops
            # cleanly into "...@@str:x@@...".
            return json.dumps(str(value), ensure_ascii=False)[1:-1]
        return json.dumps(value, ensure_ascii=False)

    body = _TOKEN_RE.sub(_replace, template.render).strip()

    if unresolved:
        raise VisualRenderError(
            f"{template.id}: unresolved token(s): {', '.join(sorted(set(unresolved)))}"
        )
    return list(template.imports), body
