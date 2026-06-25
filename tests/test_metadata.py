"""Tests for src/agents/metadata.py — frontmatter design (LLM + deterministic fallback)."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents import metadata
from src.agents.metadata import (
    _MetadataResult,
    _assemble,
    _derive_tags,
    _first_prose_paragraph,
    _format_frontmatter_guidance,
    _title_from_body,
    _truncate_description,
)
from src.mdx_document import MDXDocument


# ── _format_frontmatter_guidance ──────────────────────────────────────────────

def test_guidance_empty_when_no_frontmatter():
    assert _format_frontmatter_guidance({}) == ""
    assert _format_frontmatter_guidance({"frontmatter": {}}) == ""


def test_guidance_renders_provided_keys():
    out = _format_frontmatter_guidance({"frontmatter": {"title": "name the company", "tags": "use ticker"}})
    assert "TEMPLATE FRONTMATTER GUIDANCE" in out
    assert "title: name the company" in out
    assert "tags: use ticker" in out


# ── deterministic fallback helpers (relocated from publisher) ─────────────────

def test_title_from_first_h2_preserves_question_mark():
    body = "Hook.\n\n---\n\n## What Does This Company Actually Do?\n\nBody."
    assert _title_from_body(body) == "What Does This Company Actually Do?"


def test_title_fallback_when_no_h2():
    assert _title_from_body("Only a hook paragraph.") == "Publication"


def test_description_ends_on_sentence_boundary():
    # Longer than 160 chars so the truncator must cut — it should stop at a sentence end.
    text = (
        "The technology landscape moves fast. Sometimes stock prices detach completely "
        "from what a company is actually worth. If you are new to this it is tough to tell "
        "whether the market is panicking or the business is failing long term."
    )
    assert _truncate_description(text) == (
        "The technology landscape moves fast. Sometimes stock prices detach "
        "completely from what a company is actually worth."
    )


def test_derive_tags_drop_interrogative_filler():
    assert _derive_tags("finance-analysis", "What Does This Company Actually Do?") == [
        "finance-analysis",
        "company",
    ]


def test_first_prose_paragraph_skips_structure():
    body = "## Heading\n\nimport X from 'y'\n\nReal prose sentence here.\n"
    assert _first_prose_paragraph(body) == "Real prose sentence here"


# ── _MetadataResult coercion ──────────────────────────────────────────────────

def test_metadata_result_coerces_string_tags():
    r = _MetadataResult(title="T", description="D", tags="crm, stock-analysis salesforce")
    assert r.tags == ["crm", "stock-analysis", "salesforce"]


# ── _assemble ─────────────────────────────────────────────────────────────────

def test_assemble_fills_defaults_and_caps_tags():
    fields = _MetadataResult(title="A Title", description="A description.", tags=["a", "b", "c", "d", "e", "f"])
    meta = _assemble(fields, "finance-analysis", existing={})
    assert meta["title"] == "A Title"
    assert meta["author"] == "Alberto Duran"
    assert meta["draft"] is True
    assert meta["image"].endswith(".avif")
    assert len(meta["tags"]) == 5


def test_assemble_existing_values_override():
    fields = _MetadataResult(title="Derived", description="d", tags=["x"])
    meta = _assemble(fields, "default", existing={"title": "Kept", "draft": False})
    assert meta["title"] == "Kept"
    assert meta["draft"] is False


def test_assemble_empty_tags_fall_back_to_derived():
    fields = _MetadataResult(title="Better Queues", description="d", tags=[])
    meta = _assemble(fields, "finance-analysis", existing={})
    assert meta["tags"][0] == "finance-analysis"


# ── run (node) ────────────────────────────────────────────────────────────────

def _fake_llm(content: str):
    class FakeLLM:
        def model_copy(self, update):
            return self

        def invoke(self, messages):
            return SimpleNamespace(content=content, additional_kwargs={})

    return FakeLLM()


def _state(body: str, **extra) -> dict:
    base = {
        "humanized": MDXDocument(metadata={}, imports=[], body=body),
        "template_name": "finance-analysis",
        "template_data": {"frontmatter": {"title": "name the company"}},
        "tone": "conversational",
        "audience": "new investors",
    }
    base.update(extra)
    return base


def test_run_uses_llm_metadata_when_valid(monkeypatch):
    monkeypatch.setattr(
        metadata, "build_model",
        lambda temperature=None: _fake_llm('{"title": "Is CRM a Buy?", "description": "A beginner CRM analysis.", "tags": ["crm", "stock-analysis"]}'),
    )
    result = metadata.run(_state("Hook.\n\n---\n\n## What Does This Company Do?\n\nBody."))
    meta = result["metadata"]
    assert meta["title"] == "Is CRM a Buy?"
    # _truncate_description normalizes (strips trailing punctuation) for house style.
    assert meta["description"] == "A beginner CRM analysis"
    assert meta["tags"] == ["crm", "stock-analysis"]
    assert "errors" not in result


def test_run_falls_back_to_deterministic_on_bad_json(monkeypatch):
    monkeypatch.setattr(metadata, "build_model", lambda temperature=None: _fake_llm("not json at all"))
    result = metadata.run(_state("Hook.\n\n---\n\n## What Does This Company Actually Do?\n\nBody."))
    meta = result["metadata"]
    # Deterministic fallback derives the title from the first H2.
    assert meta["title"] == "What Does This Company Actually Do?"
    assert meta["tags"] == ["finance-analysis", "company"]
    assert "errors" in result  # the LLM failure is surfaced


def test_run_falls_back_when_build_model_raises(monkeypatch):
    def _boom(temperature=None):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(metadata, "build_model", _boom)
    result = metadata.run(_state("Hook.\n\n---\n\n## Ship It Already!\n\nBody."))
    assert result["metadata"]["title"] == "Ship It Already!"
    assert "errors" in result


def test_run_errors_when_no_body():
    result = metadata.run({"humanized": None, "template_name": "default"})
    assert "errors" in result
    assert "metadata" not in result
