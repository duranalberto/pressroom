"""Load and index visual templates from ``templates/visuals/*.yaml``.

The registry is the *menu* the outline and orchestrator see: id, kind, type, summary,
and the params an author may set. Neither learns the render internals — those live in
the template file and are consumed only by the specialized renderer for that ``kind``.

Loading is tolerant: a malformed template is skipped with a warning rather than aborting
the whole pipeline, mirroring the "degrade, never fabricate" contract used elsewhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.config import Config

logger = logging.getLogger(__name__)

# Recognized renderer kinds. A template whose kind is not here is skipped on load.
KNOWN_KINDS = ("echart", "ui", "mermaid")

# Tokens the render string may contain — used for light validation, not parsing.
_TOKEN_NAMESPACES = ("data", "param", "label", "text", "str")


@dataclass(frozen=True)
class VisualTemplate:
    """A parsed visual template. ``raw`` keeps the untouched dict for forward-compat."""

    id: str
    kind: str
    type: str
    summary: str
    params: dict[str, Any]
    extract: dict[str, Any]
    labels: dict[str, Any]
    imports: list[str]
    render: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    # Optional: params computed from a resolved data slot via a value map (e.g. a Callout
    # variant chosen from a Buy/Hold/Sell recommendation). Filled by render, not the author.
    derive: dict[str, Any] = field(default_factory=dict)

    def param_default(self, name: str) -> Any:
        """Return the default value for ``name``, or ``None`` if absent or unset."""
        spec = self.params.get(name) or {}
        return spec.get("default") if isinstance(spec, dict) else None

    def required_params(self) -> list[str]:
        """Return the names of all params that carry ``required: true``."""
        return [
            n for n, spec in self.params.items()
            if isinstance(spec, dict) and spec.get("required")
        ]


def _visuals_dir() -> Path:
    return Config().templates_dir / "visuals"


def _coerce(data: dict, path: Path) -> VisualTemplate | None:
    """Validate and convert a raw template dict into a ``VisualTemplate``.

    Args:
        data: Parsed YAML dict from the template file.
        path: File path — used only for warning messages.

    Returns:
        A ``VisualTemplate`` instance, or ``None`` when required fields are
        missing or the ``kind`` is unrecognized (logged as a warning).
    """
    missing = [k for k in ("id", "kind", "type", "render") if not data.get(k)]
    if missing:
        logger.warning("Visual template %s missing required key(s): %s — skipped",
                       path.name, ", ".join(missing))
        return None
    if data["kind"] not in KNOWN_KINDS:
        logger.warning("Visual template %s has unknown kind %r (known: %s) — skipped",
                       path.name, data["kind"], ", ".join(KNOWN_KINDS))
        return None
    imports = data.get("imports") or []
    if not isinstance(imports, list):
        logger.warning("Visual template %s: 'imports' must be a list — skipped", path.name)
        return None
    return VisualTemplate(
        id=str(data["id"]),
        kind=str(data["kind"]),
        type=str(data["type"]),
        summary=(data.get("summary") or "").strip(),
        params=data.get("params") or {},
        extract=data.get("extract") or {},
        labels=data.get("labels") or {},
        imports=[str(line) for line in imports],
        render=str(data["render"]),
        raw=data,
        derive=data.get("derive") or {},
    )


# Cache keyed by the resolved visuals dir so tests can point at a tmp dir and reload.
_cache: dict[str, dict[str, VisualTemplate]] = {}


def load_visuals(visuals_dir: str | Path | None = None) -> dict[str, VisualTemplate]:
    """Return ``{id: VisualTemplate}`` for every valid template file in the directory."""
    root = Path(visuals_dir).resolve() if visuals_dir else _visuals_dir().resolve()
    key = str(root)
    if key in _cache:
        return _cache[key]

    templates: dict[str, VisualTemplate] = {}
    if root.is_dir():
        for path in sorted(root.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                logger.warning("Visual template %s is not valid YAML — %s — skipped",
                               path.name, exc)
                continue
            vt = _coerce(data, path)
            if vt is None:
                continue
            if vt.id in templates:
                logger.warning("Duplicate visual template id %r (%s) — keeping the first",
                               vt.id, path.name)
                continue
            templates[vt.id] = vt
    _cache[key] = templates
    return templates


def get(template_id: str, visuals_dir: str | Path | None = None) -> VisualTemplate | None:
    """Return the template with ``template_id``, or None if it does not exist."""
    return load_visuals(visuals_dir).get(template_id)


def menu(visuals_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """A compact catalogue for the outline: id, kind, type, summary, params.

    Deliberately excludes ``render`` and ``imports`` — the outline configures a visual
    by reference, it never sees how the visual is built.
    """
    out: list[dict[str, Any]] = []
    for vt in load_visuals(visuals_dir).values():
        out.append({
            "id": vt.id,
            "kind": vt.kind,
            "type": vt.type,
            "summary": vt.summary,
            "params": sorted(vt.params.keys()),
            "required_params": vt.required_params(),
        })
    return out


def clear_cache() -> None:
    """Drop the loaded-template cache (tests, or when template files change mid-process)."""
    _cache.clear()
