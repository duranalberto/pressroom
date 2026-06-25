"""Tests for src/visuals/registry.py — loading, indexing, validation, the outline menu."""

from __future__ import annotations

import textwrap

import pytest

from src.visuals import registry


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.clear_cache()
    yield
    registry.clear_cache()


def _write(dir_, name, body):
    (dir_ / name).write_text(textwrap.dedent(body), encoding="utf-8")


# ── shipped templates ───────────────────────────────────────────────────────

def test_loads_the_four_shipped_templates():
    templates = registry.load_visuals()  # default dir: templates/visuals
    for tid in ("price-line", "category-bar", "grouped-bar", "verdict-callout"):
        assert tid in templates, f"{tid} should be a shipped visual template"


def test_kinds_route_correctly():
    assert registry.get("price-line").kind == "echart"
    assert registry.get("grouped-bar").kind == "echart"
    assert registry.get("verdict-callout").kind == "ui"


def test_menu_excludes_internals():
    menu = registry.menu()
    entry = next(e for e in menu if e["id"] == "price-line")
    assert entry["type"] == "lineChartOption"
    assert "title" in entry["params"]
    assert "title" in entry["required_params"]
    # The menu must NOT leak how a visual is built.
    assert "render" not in entry
    assert "imports" not in entry


# ── tolerant loading ────────────────────────────────────────────────────────

def test_skips_template_missing_required_keys(tmp_path):
    _write(tmp_path, "good.yaml", """\
        id: good
        kind: echart
        type: lineChartOption
        render: "<EChart />"
    """)
    _write(tmp_path, "bad.yaml", """\
        id: bad
        kind: echart
        # no type, no render
    """)
    templates = registry.load_visuals(tmp_path)
    assert "good" in templates
    assert "bad" not in templates


def test_skips_unknown_kind(tmp_path):
    _write(tmp_path, "weird.yaml", """\
        id: weird
        kind: hologram
        type: foo
        render: "x"
    """)
    assert registry.load_visuals(tmp_path) == {}


def test_invalid_yaml_is_skipped_not_raised(tmp_path):
    _write(tmp_path, "broken.yaml", "id: [unclosed\n")
    _write(tmp_path, "ok.yaml", """\
        id: ok
        kind: ui
        type: Callout
        render: "<Callout/>"
    """)
    templates = registry.load_visuals(tmp_path)
    assert set(templates) == {"ok"}


def test_duplicate_id_keeps_first(tmp_path):
    _write(tmp_path, "a.yaml", """\
        id: dup
        kind: echart
        type: barChartOption
        type_marker: first
        render: "A"
    """)
    _write(tmp_path, "b.yaml", """\
        id: dup
        kind: echart
        type: lineChartOption
        render: "B"
    """)
    templates = registry.load_visuals(tmp_path)
    assert templates["dup"].render == "A"


def test_get_unknown_returns_none(tmp_path):
    assert registry.get("does-not-exist", tmp_path) is None


def test_missing_dir_returns_empty(tmp_path):
    assert registry.load_visuals(tmp_path / "nope") == {}
