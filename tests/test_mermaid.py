"""Tests for src/agents/visualizer/_mermaid.py — deterministic sanitizer + doc loading."""

from __future__ import annotations

from src.agents.visualizer import _mermaid
from src.agents.visualizer._mermaid import sanitize


class _FakeLLM:
    def model_copy(self, update=None):
        return self


# ── sanitize: label quoting ──────────────────────────────────────────────────

def test_sanitize_quotes_parens_in_square_label():
    # The exact production defect: ( ) inside [ ] breaks the parser.
    out = sanitize("flowchart TD\nA[Low Model Agreement (22.25)] --> B[Next]")
    assert 'A["Low Model Agreement (22.25)"]' in out
    assert "B[Next]" in out  # clean label untouched


def test_sanitize_quotes_ampersand_label():
    out = sanitize("flowchart TD\nD[Moats & Catalysts]")
    assert 'D["Moats & Catalysts"]' in out


def test_sanitize_quotes_risky_rhombus():
    out = sanitize("flowchart TD\nB{Valid: yes?}")
    assert 'B{"Valid: yes?"}' in out


def test_sanitize_quotes_risky_edge_label():
    out = sanitize("flowchart TD\nA -->|Weight: 80%| B")
    assert '|"Weight: 80%"|' in out


def test_sanitize_leaves_clean_labels_untouched():
    src = "flowchart TD\nA[Start] --> B[Process]\nB -->|Yes| C[Done]"
    assert sanitize(src) == src


def test_sanitize_skips_already_quoted():
    src = 'flowchart TD\nA["Price ($1)"] --> B'
    assert sanitize(src) == src


# ── sanitize: de-chaining ────────────────────────────────────────────────────

def test_sanitize_dechains_semicolon_statements():
    out = sanitize("flowchart TD\nA-->B; B-->C; C-->D")
    lines = [l for l in out.split("\n") if l.strip()]
    assert "A-->B" in lines and "B-->C" in lines and "C-->D" in lines


def test_sanitize_does_not_split_semicolon_inside_quotes():
    out = sanitize('flowchart TD\nA["a; b"] --> B')
    assert 'A["a; b"]' in out
    assert out.count("\n") == 1  # header + one statement line, not split


def test_sanitize_preserves_fence_lines():
    src = "```mermaid\nflowchart TD\nA[x]\n```"
    out = sanitize(src)
    assert out.startswith("```mermaid")
    assert out.rstrip().endswith("```")


def test_sanitize_leaves_classdef_untouched():
    src = "flowchart TD\nclassDef hot fill:#f00,stroke:#333,color:black"
    assert sanitize(src) == src


# ── render: loads the distilled doc, not the orchestrator SKILL.md ────────────

def test_render_loads_distilled_authoring_doc(monkeypatch):
    seen = {}

    def fake_load_doc(name):
        seen["doc"] = name
        return "MERMAID RULES"

    def fake_invoke(llm, messages):
        seen["system"] = messages[0].content
        return "```mermaid\nflowchart TD\nA-->B\n```"

    monkeypatch.setattr(_mermaid, "load_doc", fake_load_doc)
    monkeypatch.setattr(_mermaid, "invoke_with_retry", fake_invoke)

    _mermaid.render("d1", "flowchart of the pipeline", _FakeLLM())

    assert seen["doc"] == "MERMAID_AUTHORING.md"
    assert "MERMAID RULES" in seen["system"]


def test_render_does_not_import_load_skill():
    # The node must not fall back to the SKILL.md orchestrator loader.
    assert not hasattr(_mermaid, "load_skill")
