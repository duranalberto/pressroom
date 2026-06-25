"""Tests for src/agents/reviewer.py — body-only review behavior."""

from __future__ import annotations

from types import SimpleNamespace

from src.agents import reviewer
from src.agents.reviewer import (
    _SYSTEM,
    _build_facts,
    _build_system,
    _count_missing_h2_separators,
    _count_prose_colons,
    _count_unlabeled_fences,
    _has_hook,
    _prose_word_count,
)
from src.mdx_document import MDXDocument


def test_build_system_appends_finetune_when_set():
    system = _build_system({
        "template_data": {"agents": {"reviewer": {"prompt": "Reject unexplained code."}}},
    })
    assert system.startswith(_SYSTEM)
    assert "ADDITIONAL INSTRUCTIONS (from template)" in system
    assert "Reject unexplained code." in system
    # The base prompt's literal {{ }} braces must survive (no str.format).
    assert '{{' in system


def test_build_system_is_base_when_unset():
    assert _build_system({"template_data": {}}) == _SYSTEM
    assert _build_system({}) == _SYSTEM


def test_reviewer_prompt_is_body_only():
    assert "frontmatter" not in _SYSTEM.lower()
    assert "THEJOURNAL_GUIDE_POLICY" not in _SYSTEM
    assert "mdx-blog-writer" not in _SYSTEM
    assert "mdx-rules" not in _SYSTEM
    assert "first-level heading" in _SYSTEM
    assert "document metadata blocks" in _SYSTEM


def test_reviewer_delegates_mechanical_checks_to_pipeline_facts():
    """The mechanical checks moved to the deterministic facts block; the system prompt
    must tell the model to trust those verdicts rather than re-scan for them."""
    assert "PIPELINE FACTS" in _SYSTEM
    assert "TRUST" in _SYSTEM
    # Editorial-only criteria remain.
    for marker in ("E1", "E2", "E3", "E4", "E5"):
        assert marker in _SYSTEM


def test_reviewer_embeds_the_shared_style_canon():
    from src.agents._style import BODY_STYLE_RULES

    for rule in BODY_STYLE_RULES:
        assert rule in _SYSTEM


def test_reviewer_no_longer_imports_render_mdx():
    assert not hasattr(reviewer, "render_mdx")


def test_reviewer_separator_check_is_a_deterministic_fact():
    """The `---` separator rule is resolved deterministically in the [PIPELINE FACTS]
    block, not left to the LLM's editorial judgment — the model is told to trust the
    facts rather than re-scan for separators (which caused an unfixable revision loop)."""
    missing = _build_facts("Hook.\n\n## A\n\nBody.")  # ## A has no --- before it
    assert "missing --- separator: 1 — FAIL" in missing
    present = _build_facts("Hook.\n\n---\n\n## A\n\nBody.")
    assert "missing --- separator: 0 — PASS" in present
    # The system prompt delegates mechanical checks to the facts block.
    assert "PIPELINE FACTS" in _SYSTEM and "TRUST" in _SYSTEM


def test_count_missing_h2_separators():
    assert _count_missing_h2_separators("Hook.\n\n## A\n\nBody.") == 1
    assert _count_missing_h2_separators("Hook.\n\n---\n\n## A\n\nBody.") == 0
    # Second section missing its separator is counted independently.
    assert _count_missing_h2_separators("Hook.\n\n---\n\n## A\n\nx\n\n## B") == 1


def test_reviewer_does_not_note_absent_first_level_heading():
    """Absence of a first-level heading is correct and must never be reported as an issue."""
    assert "first-level heading" in _SYSTEM
    assert "do not flag or mention the absence of first-level headings" in _SYSTEM


def test_run_reviews_body_without_rendering_metadata_or_imports(monkeypatch):
    captured: dict[str, str] = {}

    class FakeLLM:
        def model_copy(self, update):
            return self

        def invoke(self, messages):
            captured["system"] = messages[0].content
            captured["user"] = messages[-1].content
            return SimpleNamespace(
                content='{"approved": true, "summary": "Good body.", "issues": [], "suggestions": []}',
                additional_kwargs={},
            )

    monkeypatch.setattr(reviewer, "build_model", lambda temperature=None: FakeLLM())

    result = reviewer.run({
        "outline": "## Section Plan",
        "draft": MDXDocument(
            metadata={"title": "Hidden title"},
            imports=["import Hidden from './Hidden'"],
            body="Body hook.\n\n---\n\n## Section\n\nBody content.",
        ),
        "tone": "conversational",
        "audience": "developers",
        "review_iteration": 0,
        "max_iterations": 3,
    })

    assert result["review_approved"] is True
    assert "Body hook." in captured["user"]
    assert "Hidden title" not in captured["user"]
    assert "import Hidden" not in captured["user"]
    assert captured["system"] == _SYSTEM


# ── _count_prose_colons ────────────────────────────────────────────────────────

def test_count_prose_colons_zero_for_colon_free_prose():
    assert _count_prose_colons("The stock trades at $149 per share. Beta is 1.15.") == 0


def test_count_prose_colons_counts_prose_colons():
    body = "There are two issues: first, the price; second, the ratio: 1.5x."
    assert _count_prose_colons(body) == 2


def test_count_prose_colons_ignores_fenced_code_blocks():
    body = "Prose without colons.\n\n```python\nx: int = 1\ny: str = 'a'\n```\n\nMore prose."
    assert _count_prose_colons(body) == 0


def test_count_prose_colons_ignores_inline_code():
    body = "Use `x: int` to annotate types, but avoid colons in prose."
    assert _count_prose_colons(body) == 0


def test_count_prose_colons_ignores_urls():
    body = "Visit https://example.com/path:8080 for more information."
    assert _count_prose_colons(body) == 0


def test_count_prose_colons_mixed():
    body = (
        "Here is a prose colon: important.\n"
        "```sql\nSELECT x: 1\n```\n"
        "No colon in `code: here` inline either."
    )
    assert _count_prose_colons(body) == 1


def test_run_injects_pipeline_fact_into_draft(monkeypatch):
    """The PIPELINE FACT line must appear in what the reviewer LLM sees."""
    captured: dict[str, str] = {}

    class FakeLLM:
        def model_copy(self, update):
            return self

        def invoke(self, messages):
            captured["user"] = messages[-1].content
            return SimpleNamespace(
                content='{"approved": true, "summary": "OK", "issues": [], "suggestions": []}',
                additional_kwargs={},
            )

    monkeypatch.setattr(reviewer, "build_model", lambda temperature=None: FakeLLM())

    reviewer.run({
        "outline": "## Section Plan",
        "draft": MDXDocument(
            metadata={"title": "T"},
            imports=[],
            body="Clean prose with no colons.\n\n## Section\n\nContent.",
        ),
        "tone": "conversational",
        "audience": "developers",
        "review_iteration": 0,
        "max_iterations": 3,
    })

    assert "PIPELINE FACTS" in captured["user"]
    assert "Prose colons: 0" in captured["user"]
    assert "PASS" in captured["user"]


# ── deterministic linter helpers ────────────────────────────────────────────────

def test_prose_word_count_excludes_code():
    body = "one two three\n\n```python\nx = 1\ny = 2\n```\n\nfour five"
    assert _prose_word_count(body) == 5


def test_count_unlabeled_fences_flags_only_openers_without_language():
    labeled = "```python\nprint(1)\n```"
    unlabeled = "```\nplain\n```"
    assert _count_unlabeled_fences(labeled) == 0
    assert _count_unlabeled_fences(unlabeled) == 1
    assert _count_unlabeled_fences(labeled + "\n\n" + unlabeled) == 1


def test_count_unlabeled_fences_treats_artifact_slot_as_labeled():
    body = '```artifact-slot\nid="x" template="y"\n```'
    assert _count_unlabeled_fences(body) == 0


def test_has_hook_true_when_prose_precedes_first_section():
    assert _has_hook("A real hook sentence.\n\n## Section\n\nBody.") is True


def test_has_hook_false_when_section_comes_first():
    assert _has_hook("## Section\n\nBody.") is False


def test_build_facts_reports_each_check_with_a_verdict():
    body = "Clean hook prose.\n\n## A\n\nBody.\n\n## B\n\nMore body."
    facts = _build_facts(body)
    assert facts.startswith("[PIPELINE FACTS")
    assert "Prose colons: 0 — PASS" in facts
    assert "Em dashes: 0 — PASS" in facts
    assert "Number of ## sections: 2 — PASS" in facts
    assert "Hook before the first ## heading: present — PASS" in facts


def test_build_facts_marks_violations_fail():
    body = "Bad hook with a colon: here — and an em dash.\n\n## Only One Section\n\nBody."
    facts = _build_facts(body)
    assert "Em dashes: 1 — FAIL" in facts
    assert "Prose colons: 1 — FAIL" in facts
    assert "Number of ## sections: 1 — FAIL" in facts
