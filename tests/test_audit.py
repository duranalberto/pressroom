"""Tests for src/audit.py — run-id allocation and per-step body snapshots."""

from __future__ import annotations

from src.audit import (
    allocate_run_id,
    format_run_id,
    run_dir,
    write_step_body,
)


# ── allocate_run_id ────────────────────────────────────────────────────────────

def test_allocate_starts_at_one_when_missing(tmp_path):
    counter = tmp_path / ".run_id"
    assert allocate_run_id(counter) == 1
    assert counter.read_text() == "1"


def test_allocate_increments_existing(tmp_path):
    counter = tmp_path / ".run_id"
    counter.write_text("41")
    assert allocate_run_id(counter) == 42
    assert counter.read_text() == "42"


def test_allocate_is_monotonic_across_calls(tmp_path):
    counter = tmp_path / ".run_id"
    ids = [allocate_run_id(counter) for _ in range(3)]
    assert ids == [1, 2, 3]


def test_allocate_recovers_from_garbage(tmp_path):
    counter = tmp_path / ".run_id"
    counter.write_text("not a number")
    assert allocate_run_id(counter) == 1


def test_allocate_creates_parent_dir(tmp_path):
    counter = tmp_path / "nested" / "dir" / ".run_id"
    assert allocate_run_id(counter) == 1
    assert counter.exists()


# ── format_run_id ──────────────────────────────────────────────────────────────

def test_format_zero_pads_to_four(tmp_path):
    assert format_run_id(42) == "0042"
    assert format_run_id(1) == "0001"


def test_format_does_not_truncate_large_ids():
    assert format_run_id(12345) == "12345"


# ── run_dir ────────────────────────────────────────────────────────────────────

def test_run_dir_layout(tmp_path):
    result = run_dir(tmp_path, "0042")
    assert result == tmp_path / "audit" / "0042"


# ── write_step_body ────────────────────────────────────────────────────────────

def test_write_step_body_creates_file(tmp_path):
    d = tmp_path / "audit" / "0001"
    write_step_body(d, "outline", "# An outline\n\nbody")
    assert (d / "outline.md").read_text() == "# An outline\n\nbody"


def test_write_step_body_creates_missing_dir(tmp_path):
    d = tmp_path / "audit" / "0007"
    write_step_body(d, "writer", "draft body")
    assert (d / "writer.md").exists()


def test_write_step_body_none_becomes_empty(tmp_path):
    d = tmp_path / "audit" / "0002"
    write_step_body(d, "reviewer", None)  # type: ignore[arg-type]
    assert (d / "reviewer.md").read_text() == ""


def test_write_step_body_overwrites(tmp_path):
    d = tmp_path / "audit" / "0003"
    write_step_body(d, "writer", "round 1")
    write_step_body(d, "writer", "round 2")
    assert (d / "writer.md").read_text() == "round 2"
