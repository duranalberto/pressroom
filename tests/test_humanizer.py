"""Tests for src/agents/humanizer.py — pure preservation helpers."""

from __future__ import annotations

from src.agents.humanizer import (
    _SYSTEM,
    _build_system,
    _preserves_structure,
    _extract_mdx_component_blocks,
)
from src.agents.reviewer import _SYSTEM as _REVIEWER_SYSTEM


def test_build_system_appends_finetune_when_set():
    system = _build_system({
        "template_data": {"agents": {"humanizer": {"prompt": "Prefer active voice."}}},
    })
    assert "ADDITIONAL INSTRUCTIONS (from template)" in system
    assert "Prefer active voice." in system


def test_build_system_no_finetune_when_unset():
    system = _build_system({"template_data": {}})
    assert "ADDITIONAL INSTRUCTIONS (from template)" not in system


def test_system_prompt_has_generic_mdx_preservation_rules():
    assert "ARTIFACT PLACEHOLDER RULES" not in _SYSTEM
    assert "artifact-preserve-rules" not in _SYSTEM
    assert "frontmatter" not in _SYSTEM.lower()
    assert "mdx-blog-writer" not in _SYSTEM
    assert "Rewrite prose only" in _SYSTEM
    assert "All fenced code blocks" in _SYSTEM
    assert "Mermaid" not in _SYSTEM
    assert "mermaid" not in _SYSTEM
    assert "All MDX/JSX component blocks" in _SYSTEM


def test_system_prompt_no_longer_injects_the_whole_skill():
    """The 5,107-word SKILL.md dump is gone; the prompt now triages per draft."""
    assert "all 33 patterns" not in _SYSTEM
    assert "{patterns}" in _SYSTEM  # placeholder filled per-draft by _build_system


def test_build_system_injects_only_detected_patterns():
    dirty = _build_system({
        "template_data": {},
        "draft": {"body": "We leverage a robust pipeline to delve into the data.",
                  "metadata": {}, "imports": []},
    })
    clean = _build_system({
        "template_data": {},
        "draft": {"body": "The cache holds 64 entries and evicts the oldest first.",
                  "metadata": {}, "imports": []},
    })
    assert "Overused AI Vocabulary" in dirty
    assert "Overused AI Vocabulary" not in clean
    # The always-on voice core is present in both.
    assert "Personality and Soul" in dirty
    assert "Personality and Soul" in clean


def test_build_system_embeds_the_shared_style_canon():
    from src.agents._style import BODY_STYLE_RULES

    system = _build_system({"template_data": {}, "draft": {"body": "", "metadata": {}, "imports": []}})
    for rule in BODY_STYLE_RULES:
        assert rule in system


def test_valid_same_h2s_and_separators():
    original = "## Section One\n\n---\n\nContent here."
    output = "## Section One\n\n---\n\nRewritten content here."
    assert _preserves_structure(original, output) is True


def test_invalid_missing_h2():
    original = "## Section One\n\n---\n\nContent"
    output = "### Renamed Section\n\n---\n\nContent"
    assert _preserves_structure(original, output) is False


def test_invalid_renamed_h2():
    original = "## Original Title\n\n---\n\nContent"
    output = "## Changed Title\n\n---\n\nContent"
    assert _preserves_structure(original, output) is False


def test_invalid_renamed_h3():
    original = "## Section\n\n### Original Detail\n\nContent"
    output = "## Section\n\n### Changed Detail\n\nContent"
    assert _preserves_structure(original, output) is False


def test_invalid_fewer_separators():
    original = "\n---\n\n## Section\n\n---\n\nContent"
    output = "\n---\n\n## Section\n\nContent"  # one --- removed
    assert _preserves_structure(original, output) is False


def test_invalid_extra_separator():
    original = "## Section\n\nContent"
    output = "## Section\n\n---\n\nContent"
    assert _preserves_structure(original, output) is False


def test_valid_no_headings_no_separators():
    original = "Just prose content."
    output = "Just prose content rewritten."
    assert _preserves_structure(original, output) is True


def test_invalid_extra_h2_added():
    original = "## Section One\n\n---\n\nContent"
    output = "## Section One\n\n---\n\nContent\n\n## Extra Section"
    assert _preserves_structure(original, output) is False


def test_valid_multiple_h2s_all_preserved():
    original = "## A\n\n---\n\n## B\n\n---\n\n## C"
    output = "## A\n\n---\n\n## B\n\n---\n\n## C\n\nDifferent prose."
    assert _preserves_structure(original, output) is True


def test_invalid_all_h2s_dropped():
    original = "## Section One\n\n## Section Two"
    output = "All headings removed."
    assert _preserves_structure(original, output) is False


def test_valid_rewrites_prose_while_preserving_fenced_blocks():
    original = "This is stiff.\n\n```python\nprint('keep')\n```\n"
    output = "This reads better.\n\n```python\nprint('keep')\n```\n"
    assert _preserves_structure(original, output) is True


def test_invalid_changed_fenced_block():
    original = "Text.\n\n```python\nprint('keep')\n```\n"
    output = "Text.\n\n```python\nprint('changed')\n```\n"
    assert _preserves_structure(original, output) is False


def test_invalid_changed_markdown_link_anchor():
    original = "Read the [official docs](https://example.com/docs)."
    output = "Read the [documentation](https://example.com/docs)."
    assert _preserves_structure(original, output) is False


def test_invalid_changed_markdown_link_target():
    original = "Read the [official docs](https://example.com/docs)."
    output = "Read the [official docs](https://example.com/changed)."
    assert _preserves_structure(original, output) is False


def test_extract_mdx_component_blocks_preserves_container_block():
    content = (
        "Before.\n\n"
        '<Callout variant="information" title="Keep">\n'
        "  <p>Do not rewrite this child.</p>\n"
        "</Callout>\n\n"
        "After."
    )
    assert _extract_mdx_component_blocks(content) == [
        '<Callout variant="information" title="Keep">\n'
        "  <p>Do not rewrite this child.</p>\n"
        "</Callout>\n"
    ]


def test_extract_mdx_component_blocks_handles_multiline_self_closing_component():
    content = (
        "Before.\n\n"
        "<EChart\n"
        '  title="Revenue"\n'
        "  option={{}}\n"
        "/>\n\n"
        "After."
    )
    assert _extract_mdx_component_blocks(content) == [
        "<EChart\n"
        '  title="Revenue"\n'
        "  option={{}}\n"
        "/>\n"
    ]


def test_extract_mdx_component_blocks_ignores_code_fences():
    content = (
        "```mdx\n"
        "<Callout>Example only.</Callout>\n"
        "```\n\n"
        "<Callout>Real component.</Callout>\n"
    )
    assert _extract_mdx_component_blocks(content) == ["<Callout>Real component.</Callout>\n"]


def test_llm_path_falls_back_when_headings_stripped():
    """If the LLM humanizer drops ## markers, _cli_output_is_valid catches it."""
    original = "## Section One\n\nProse.\n\n## Section Two\n\nMore prose."
    llm_output = "Section One\n\nProse.\n\nSection Two\n\nMore prose."
    assert _preserves_structure(original, llm_output) is False


def test_llm_path_passes_when_headings_preserved():
    """If the LLM humanizer preserves ## markers, _cli_output_is_valid passes."""
    original = "## Section One\n\nProse.\n\n## Section Two\n\nMore prose."
    llm_output = "## Section One\n\nRewritten prose.\n\n## Section Two\n\nBetter prose."
    assert _preserves_structure(original, llm_output) is True


def test_reviewer_criterion_9_uses_first_level_heading_language():
    """Criterion 9 must be unambiguous — 'first-level heading' not bare '#'."""
    assert "first-level heading" in _REVIEWER_SYSTEM
    # Must not use ambiguous bare `#` phrasing that LLMs could misread as any heading
    assert "A body with no `#` heading is CORRECT" not in _REVIEWER_SYSTEM


def test_invalid_changed_mdx_component_block():
    original = (
        "Before.\n\n"
        '<Callout variant="information" title="Keep">\n'
        "  <p>Do not rewrite this child.</p>\n"
        "</Callout>\n\n"
        "After."
    )
    output = (
        "Before rewritten.\n\n"
        '<Callout variant="warning" title="Keep">\n'
        "  <p>Do not rewrite this child.</p>\n"
        "</Callout>\n\n"
        "After rewritten."
    )
    assert _preserves_structure(original, output) is False
