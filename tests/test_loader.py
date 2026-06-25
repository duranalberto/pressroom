"""Tests for src/agents/loader.py — input discovery, JSON trimming, and the node."""

from __future__ import annotations

import json

import pytest

from src.agents import loader
from src.agents.loader import (
    _JSON_ARRAY_HEAD,
    _JSON_ARRAY_TAIL,
    _JSON_CHAR_LIMIT,
    _JSON_MAX_CHARS,
    _discover_files,
    _read_file,
    _summarize_json,
    run,
)


# ── _summarize_json ───────────────────────────────────────────────────────────

def test_summarize_keeps_short_arrays_intact():
    obj = {"items": [1, 2, 3]}
    assert _summarize_json(obj) == {"items": [1, 2, 3]}


def test_summarize_trims_long_array_with_elision_marker():
    obj = {"series": list(range(100))}
    out = _summarize_json(obj)["series"]
    assert out[:_JSON_ARRAY_HEAD] == list(range(_JSON_ARRAY_HEAD))
    assert out[-_JSON_ARRAY_TAIL:] == [98, 99]
    assert "elided" in out[_JSON_ARRAY_HEAD]
    assert "95 more items" in out[_JSON_ARRAY_HEAD]


def test_summarize_keeps_every_scalar_in_nested_objects():
    obj = {"metrics": {"a": 1, "b": 2.5, "c": "x"}, "noise": list(range(50))}
    out = _summarize_json(obj)
    assert out["metrics"] == {"a": 1, "b": 2.5, "c": "x"}
    assert len(out["noise"]) == _JSON_ARRAY_HEAD + 1 + _JSON_ARRAY_TAIL


def test_summarize_recurses_into_arrays_of_objects():
    obj = {"rows": [{"id": i, "v": i * 10} for i in range(20)]}
    out = _summarize_json(obj)["rows"]
    assert out[0] == {"id": 0, "v": 0}
    assert out[-1] == {"id": 19, "v": 190}


# ── _read_file ────────────────────────────────────────────────────────────────

def test_read_file_non_json_returned_verbatim(tmp_path):
    f = tmp_path / "report.md"
    big = "x" * (_JSON_CHAR_LIMIT + 5000)
    f.write_text(big, encoding="utf-8")
    assert _read_file(f) == big


def test_read_file_small_json_untouched(tmp_path):
    f = tmp_path / "small.json"
    payload = {"a": 1, "b": [1, 2, 3]}
    f.write_text(json.dumps(payload), encoding="utf-8")
    assert _read_file(f) == json.dumps(payload)


def test_read_file_large_json_preserves_scalars_trims_arrays(tmp_path):
    f = tmp_path / "big.json"
    payload = {"ticker": "CRM", "composite_intrinsic": 3465.5, "price_history": list(range(2000))}
    f.write_text(json.dumps(payload), encoding="utf-8")
    assert len(f.read_text()) > _JSON_CHAR_LIMIT
    out = _read_file(f)
    assert "CRM" in out
    assert "3465.5" in out
    assert "elided" in out
    assert "1995 more items" in out


def test_read_file_malformed_json_falls_back_to_byte_truncate(tmp_path):
    f = tmp_path / "broken.json"
    f.write_text("{not valid json " + "x" * _JSON_CHAR_LIMIT, encoding="utf-8")
    out = _read_file(f)
    assert "truncated" in out
    assert len(out) < _JSON_CHAR_LIMIT + 200


def test_read_file_huge_trimmed_json_capped_at_ceiling(tmp_path):
    f = tmp_path / "huge.json"
    payload = {f"metric_{i}": f"value-{i}-{'y' * 40}" for i in range(2000)}
    f.write_text(json.dumps(payload), encoding="utf-8")
    out = _read_file(f)
    assert "truncated" in out
    assert len(out) <= _JSON_MAX_CHARS + 200


# ── _discover_files ───────────────────────────────────────────────────────────

def test_discover_files_finds_supported_types_and_skips_others(tmp_path):
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c", encoding="utf-8")
    (tmp_path / "ignore.png").write_text("x", encoding="utf-8")
    names = {p.name for p in _discover_files(tmp_path)}
    assert names == {"a.md", "b.json", "c.txt"}


def test_discover_files_recurses_subdirectories(tmp_path):
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "deep.md").write_text("deep", encoding="utf-8")
    assert any(p.name == "deep.md" for p in _discover_files(tmp_path))


def test_discover_files_empty_dir_returns_empty(tmp_path):
    assert _discover_files(tmp_path) == []


# ── run (node) ────────────────────────────────────────────────────────────────

def test_run_loads_input_and_template_into_state(tmp_path, monkeypatch):
    (tmp_path / "brief.md").write_text("# Brief\n\nDo the thing.", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"ticker": "CRM"}', encoding="utf-8")

    monkeypatch.setattr(loader, "load_template", lambda name: {"name": name, "goal": "g"})

    result = run({"input_dir": str(tmp_path), "template_name": "finance-analysis"})

    assert "Do the thing." in result["petition_content"]
    assert '"ticker": "CRM"' in result["petition_content"]
    assert result["template_data"] == {"name": "finance-analysis", "goal": "g"}

    names = {f["name"] for f in result["input_files"]}
    assert names == {"brief.md", "data.json"}
    for ref in result["input_files"]:
        assert ref["path"].endswith(ref["name"])
        assert ref["chars"] > 0
    assert sorted(result["input_file_paths"]) == sorted(f["path"] for f in result["input_files"])


def test_run_reports_error_when_no_input_files(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "load_template", lambda name: {"name": name})
    result = run({"input_dir": str(tmp_path), "template_name": "default"})
    assert "errors" in result
    assert any("no" in e.lower() for e in result["errors"])


def test_run_tolerates_missing_template(tmp_path, monkeypatch):
    (tmp_path / "brief.md").write_text("hi", encoding="utf-8")

    def _raise(name):
        raise FileNotFoundError("nope")

    monkeypatch.setattr(loader, "load_template", _raise)
    result = run({"input_dir": str(tmp_path), "template_name": "ghost"})
    assert result["template_data"] == {"name": "ghost"}
