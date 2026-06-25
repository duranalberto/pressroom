"""Tests for main.py — _save_state_snapshot helper.

Input reading (`_read_file`, `_summarize_json`) moved to the loader node; those tests
now live in tests/test_loader.py.
"""

from __future__ import annotations

import datetime
import json

from main import _save_audit_step, _save_state_snapshot


def test_creates_file(tmp_path):
    _save_state_snapshot("writer", {"review_iteration": 0, "errors": []}, tmp_path)
    assert (tmp_path / "pipeline_state.json").exists()


def test_valid_json(tmp_path):
    _save_state_snapshot("reviewer", {"petition_content": "brief"}, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert isinstance(data, dict)


def test_last_node_field(tmp_path):
    _save_state_snapshot("humanizer", {}, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert data["_last_node"] == "humanizer"


def test_saved_at_is_iso_timestamp(tmp_path):
    _save_state_snapshot("publisher", {}, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    # Should not raise — confirms the string is a valid ISO datetime
    datetime.datetime.fromisoformat(data["_saved_at"])


def test_state_values_included(tmp_path):
    state = {"petition_content": "my brief", "review_iteration": 2, "errors": ["oops"]}
    _save_state_snapshot("writer", state, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert data["petition_content"] == "my brief"
    assert data["review_iteration"] == 2
    assert data["errors"] == ["oops"]


def test_overwrites_on_subsequent_calls(tmp_path):
    _save_state_snapshot("writer", {"review_iteration": 1}, tmp_path)
    _save_state_snapshot("reviewer", {"review_iteration": 2}, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert data["_last_node"] == "reviewer"
    assert data["review_iteration"] == 2


def test_creates_output_dir_if_missing(tmp_path):
    nested = tmp_path / "a" / "b" / "output"
    _save_state_snapshot("writer", {}, nested)
    assert (nested / "pipeline_state.json").exists()


def test_date_objects_serialized_as_string(tmp_path):
    state = {"pubDate": datetime.date(2026, 6, 26)}
    _save_state_snapshot("publisher", state, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert data["pubDate"] == "2026-06-26"


def test_none_values_preserved(tmp_path):
    state = {"outline": None, "draft": None, "output_path": None}
    _save_state_snapshot("outline_designer", state, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert data["outline"] is None
    assert data["draft"] is None


def test_nested_dict_preserved(tmp_path):
    state = {
        "draft": {
            "metadata": {"title": "Hello", "draft": True},
            "imports": ["import Foo from './Foo'"],
            "body": "Some prose.",
        }
    }
    _save_state_snapshot("writer", state, tmp_path)
    data = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert data["draft"]["metadata"]["title"] == "Hello"
    assert data["draft"]["imports"] == ["import Foo from './Foo'"]


# ── _save_audit_step ───────────────────────────────────────────────────────────

def test_audit_step_outline_writes_string(tmp_path):
    _save_audit_step("outline_designer", {"outline": "# Outline\n\nbody"}, tmp_path)
    assert (tmp_path / "outline.md").read_text() == "# Outline\n\nbody"


def test_audit_step_writer_saves_body_without_frontmatter(tmp_path):
    state = {"draft": {"metadata": {"title": "X"}, "imports": ["import A"], "body": "draft prose"}}
    _save_audit_step("writer", state, tmp_path)
    content = (tmp_path / "writer.md").read_text()
    assert content == "draft prose"
    assert "title" not in content
    assert "import A" not in content


def test_audit_step_reviewer_saves_feedback(tmp_path):
    _save_audit_step("reviewer", {"review_feedback": "## Review — Round 1"}, tmp_path)
    assert (tmp_path / "reviewer.md").read_text() == "## Review — Round 1"


def test_audit_step_humanizer_saves_body(tmp_path):
    state = {"humanized": {"metadata": {}, "imports": [], "body": "humanized prose"}}
    _save_audit_step("humanizer", state, tmp_path)
    assert (tmp_path / "humanizer.md").read_text() == "humanized prose"


def test_audit_step_ignores_untracked_node(tmp_path):
    _save_audit_step("publisher", {"output_path": "/x"}, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_audit_step_writer_overwrites_across_rounds(tmp_path):
    _save_audit_step("writer", {"draft": {"body": "round 1"}}, tmp_path)
    _save_audit_step("writer", {"draft": {"body": "round 2"}}, tmp_path)
    assert (tmp_path / "writer.md").read_text() == "round 2"


def test_audit_step_handles_missing_payload(tmp_path):
    _save_audit_step("outline_designer", {}, tmp_path)
    assert (tmp_path / "outline.md").read_text() == ""
