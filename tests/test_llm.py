"""Tests for src/llm.py — strip_fences pure function."""

from __future__ import annotations

from src.llm import strip_fences


def test_strip_fences_mdx_wrapper():
    text = "```mdx\nHello\n```"
    assert strip_fences(text) == "Hello"


def test_strip_fences_generic_wrapper():
    text = "```\nHello\n```"
    assert strip_fences(text) == "Hello"


def test_strip_fences_markdown_wrapper():
    text = "```markdown\nHello\n```"
    assert strip_fences(text) == "Hello"


def test_strip_fences_no_fence_unchanged():
    text = "Hello world"
    assert strip_fences(text) == "Hello world"


def test_strip_fences_strips_outer_whitespace():
    text = "  \nHello\n  "
    assert strip_fences(text) == "Hello"


def test_strip_fences_preserves_inner_mermaid_fence():
    # Only outer fence removed; inner mermaid block must survive
    text = "```mdx\nSome text\n\n```mermaid\ngraph LR\nA --> B\n```\n```"
    result = strip_fences(text)
    assert "```mermaid" in result
    assert "graph LR" in result
    assert "A --> B" in result


def test_strip_fences_preserves_inner_code_block():
    text = "```mdx\nProse\n\n```python\nprint('hi')\n```\n```"
    result = strip_fences(text)
    assert "```python" in result
    assert "print('hi')" in result


def test_strip_fences_no_trailing_fence_not_stripped():
    # Opening fence present but no closing fence — content kept as-is after stripping opener
    text = "```mdx\nHello"
    result = strip_fences(text)
    assert "Hello" in result
    # No trailing ``` to strip, so result should not end with ``` on its own line
    assert not result.endswith("```")


def test_strip_fences_empty_string():
    assert strip_fences("") == ""


def test_strip_fences_only_fence_markers():
    text = "```\n```"
    result = strip_fences(text)
    assert result == ""


# ── Content-specific fences must NOT be stripped ──────────────────────────────

def test_strip_fences_preserves_mermaid_fence():
    """Mermaid artifacts returned as a bare ```mermaid block must keep their fences."""
    text = "```mermaid\nflowchart TD\nA --> B\n```"
    result = strip_fences(text)
    assert result.startswith("```mermaid")
    assert result.endswith("```")
    assert "flowchart TD" in result


def test_strip_fences_preserves_python_fence():
    text = "```python\nprint('hi')\n```"
    result = strip_fences(text)
    assert result.startswith("```python")
    assert result.endswith("```")


def test_strip_fences_preserves_javascript_fence():
    text = "```javascript\nconsole.log('hi')\n```"
    result = strip_fences(text)
    assert result.startswith("```javascript")


def test_strip_fences_mermaid_case_insensitive_not_stripped():
    text = "```Mermaid\nflowchart TD\nA --> B\n```"
    result = strip_fences(text)
    assert result.startswith("```Mermaid")
