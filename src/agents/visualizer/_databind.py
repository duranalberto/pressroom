"""Deterministic data binding for artifact-slots.

The outline may attach a ``data="..."`` directive to an artifact-slot fence, declaring
where a chart's values come from. This module parses those directives, resolves them
against the input files via :func:`src.json_query.query`, and substitutes the resolved
values into the rendered snippet by token — so the chart LLM never transcribes source
numbers.

Directive grammar (``;``-separated bindings):

    name=file:path                         single value or array at one path
    name=file:path?last=N                  tail-slice an array (e.g. last=63 points)
    name=file:[path_a, path_b, ...]        array assembled from several paths in order

Each binding ``name`` is referenced in the snippet as the token ``@@data:name@@``. For any
binding whose value is a list, a companion ``name_labels`` token is synthesized
(``["D-(N-1)", ..., "D-0"]``) so a chart's x-axis always matches its series length.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.json_query import JsonQueryError, query
from src.visuals.render import synth_labels

# A fenced artifact-slot block and its attributes (any order, all optional except id).
_SLOT_BLOCK_RE = re.compile(r"```artifact-slot[ \t]*\n(.*?)\n```", re.DOTALL)
_ID_RE = re.compile(r'id="([^"]*)"')
_CONTEXT_RE = re.compile(r'context="([^"]*)"', re.DOTALL)
_DATA_RE = re.compile(r'data="([^"]*)"', re.DOTALL)
_TEMPLATE_RE = re.compile(r'template="([^"]*)"')
_PARAMS_RE = re.compile(r'params="([^"]*)"', re.DOTALL)

# Token the chart snippet uses to reference a resolved binding.
_DATA_TOKEN_RE = re.compile(r"@@data:([\w-]+)@@")

# `?last=N` suffix on a single-path binding — keep the last N items of the array.
_LAST_RE = re.compile(r"\?last=(\d+)\s*$")

# Projection: `list.path[key=value].field` — select `field` from each object in the list
# at `list.path` whose `key` equals `value`, in list order. Lets a chart adapt to a
# variable-length set of rows (e.g. only the valuation models that actually ran).
_PROJECT_RE = re.compile(r"^(?P<list>[\w.]+)\[(?P<key>\w+)=(?P<val>[^\]]+)\]\.(?P<sel>[\w.]+)$")


@dataclass
class Slot:
    id: str
    context: str = ""
    data: str = ""  # raw data directive, "" when absent
    template: str = ""  # visual-template id, "" for a freeform slot
    params: str = ""  # inline "k=v; k2=v2" param overrides, "" when absent


@dataclass
class Binding:
    name: str
    file: str
    paths: list[str]
    is_list: bool = False  # True when declared with [..] multi-path form
    last: int | None = None  # keep the last N items of the resolved array
    error: str = ""  # set when the directive text could not be parsed

    extras: dict = field(default_factory=dict)


def parse_slots(outline: str) -> list[Slot]:
    """Extract every fenced artifact-slot block from an outline string.

    Args:
        outline: Raw outline text produced by the outline designer.

    Returns:
        List of ``Slot`` objects in document order. Blocks missing an ``id``
        attribute are silently skipped.
    """
    slots: list[Slot] = []
    for block in _SLOT_BLOCK_RE.finditer(outline):
        inner = block.group(1)
        id_m = _ID_RE.search(inner)
        if not id_m:
            continue
        ctx_m = _CONTEXT_RE.search(inner)
        data_m = _DATA_RE.search(inner)
        tmpl_m = _TEMPLATE_RE.search(inner)
        params_m = _PARAMS_RE.search(inner)
        slots.append(Slot(
            id=id_m.group(1),
            context=ctx_m.group(1) if ctx_m else "",
            data=data_m.group(1) if data_m else "",
            template=tmpl_m.group(1) if tmpl_m else "",
            params=params_m.group(1) if params_m else "",
        ))
    return slots


def parse_inline_params(spec: str) -> dict[str, str]:
    """Parse a ``params="k=v; k2=v2"`` fence attribute into a string dict.

    Used for ad-hoc fence overrides. Configured visuals carry typed params in
    the publication template's ``visuals:`` block and are handled separately.

    Args:
        spec: Raw params string from the fence attribute value (without the
            enclosing quotes), e.g. ``"color=blue; size=large"``.

    Returns:
        Dict of ``{key: value}`` pairs, all values as strings. Empty string or
        whitespace-only inputs return an empty dict.
    """
    out: dict[str, str] = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if sep and key.strip():
            out[key.strip()] = value.strip()
    return out


def parse_data_spec(spec: str) -> list[Binding]:
    """Parse a ``data="..."`` directive into bindings. Malformed bindings are returned
    with ``error`` set rather than raising, so one bad binding does not lose the rest."""
    bindings: list[Binding] = []
    for raw in spec.split(";"):
        chunk = raw.strip()
        if not chunk:
            continue
        name, sep, rest = chunk.partition("=")
        name, rest = name.strip(), rest.strip()
        if not sep or not name or not rest:
            bindings.append(Binding(name=name or "?", file="", paths=[],
                                    error=f"malformed binding: {chunk!r}"))
            continue
        file, sep2, pathpart = rest.partition(":")
        file, pathpart = file.strip(), pathpart.strip()
        if not sep2 or not file or not pathpart:
            bindings.append(Binding(name=name, file="", paths=[],
                                    error=f"binding {name!r} missing file:path: {rest!r}"))
            continue

        if pathpart.startswith("[") and pathpart.endswith("]"):
            paths = [p.strip() for p in pathpart[1:-1].split(",") if p.strip()]
            bindings.append(Binding(name=name, file=file, paths=paths, is_list=True))
            continue

        proj = _PROJECT_RE.match(pathpart)
        if proj:
            bindings.append(Binding(
                name=name, file=file, paths=[proj.group("list")],
                extras={"project": (proj.group("key"), proj.group("val"), proj.group("sel"))},
            ))
            continue

        last: int | None = None
        last_m = _LAST_RE.search(pathpart)
        if last_m:
            last = int(last_m.group(1))
            pathpart = pathpart[: last_m.start()].strip()
        bindings.append(Binding(name=name, file=file, paths=[pathpart], last=last))
    return bindings


def _select(row: Any, sel: str) -> Any:
    """Read a (possibly dotted) field out of one projected row object."""
    cur = row
    for part in sel.split("."):
        cur = cur[part]
    return cur


def _resolve_projection(b: Binding, input_dir: str | Path | None) -> list[Any]:
    """Resolve a `list[key=value].field` projection into an ordered list of values.

    Reads the list at ``b.paths[0]``, keeps rows whose ``key`` equals ``value`` (string
    compare), and projects ``field`` from each — preserving list order so parallel
    projections (e.g. Bear/Base/Bull scenarios) stay aligned. Degrades loudly: a missing
    list, a non-list value, an unselectable field, or zero matches raises ``JsonQueryError``
    so the artifact is skipped rather than shipped empty.
    """
    key, val, sel = b.extras["project"]
    rows = query(b.file, b.paths[0], input_dir=input_dir)
    if not isinstance(rows, list):
        raise JsonQueryError(
            f"projection source {b.paths[0]!r} in {b.file!r} is not a list"
        )
    matched = [r for r in rows if isinstance(r, dict) and str(r.get(key)) == val]
    if not matched:
        raise JsonQueryError(
            f"projection {b.paths[0]}[{key}={val}] in {b.file!r} matched no rows"
        )
    try:
        return [_select(r, sel) for r in matched]
    except (KeyError, IndexError, TypeError) as exc:
        raise JsonQueryError(
            f"projection field {sel!r} missing in a row of {b.paths[0]!r} ({b.file!r})"
        ) from exc


def resolve_spec(
    spec: str,
    input_dir: str | Path | None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve a full ``data="..."`` directive string into concrete values.

    Parses the directive into individual bindings, resolves each against the
    input JSON files, and synthesizes ``<name>_labels`` companion entries for
    every list-valued binding so chart x-axes can match series lengths.

    A binding that fails (parse error, missing file, bad path, type mismatch)
    is dropped and recorded in the errors list; the rest continue to resolve.

    Args:
        spec: The raw ``data`` attribute value, e.g.
            ``"y=valuation.json:metrics.revenue; x=valuation.json:metrics.years"``.
        input_dir: Directory to resolve filenames against.

    Returns:
        Tuple of ``(resolved_dict, error_list)``. ``resolved_dict`` maps each
        binding name to its resolved Python value plus any synthesized
        ``<name>_labels`` entries.
    """
    resolved: dict[str, Any] = {}
    errors: list[str] = []

    for b in parse_data_spec(spec):
        if b.error:
            errors.append(b.error)
            continue
        try:
            if b.extras.get("project"):
                value: Any = _resolve_projection(b, input_dir)
            elif b.is_list:
                value = [query(b.file, p, input_dir=input_dir) for p in b.paths]
            else:
                value = query(b.file, b.paths[0], last=b.last, input_dir=input_dir)
        except JsonQueryError as exc:
            errors.append(f"binding {b.name!r} failed — {exc}")
            continue

        resolved[b.name] = value
        if isinstance(value, list):
            resolved.setdefault(f"{b.name}_labels", synth_labels(len(value)))

    return resolved, errors


def substitute_data_tokens(
    body: str,
    resolved: dict[str, Any],
) -> tuple[str, list[str]]:
    """Replace ``@@data:name@@`` tokens with JSON-encoded resolved values.

    Tokens whose name is absent from ``resolved`` are stripped (never left in
    the output) and included in the unresolved list, mirroring how the
    publisher handles unresolved artifact placeholders.

    Args:
        body: Rendered snippet text containing ``@@data:name@@`` tokens.
        resolved: Mapping of binding name to its resolved Python value.

    Returns:
        Tuple of ``(substituted_body, unresolved_names)``.
    """
    unresolved: list[str] = []

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name in resolved:
            return json.dumps(resolved[name])
        unresolved.append(name)
        return ""

    return _DATA_TOKEN_RE.sub(_replace, body), unresolved
