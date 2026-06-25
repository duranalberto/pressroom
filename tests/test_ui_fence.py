"""Tests for the UI sub-agent's daisyui-fence contract (src/agents/visualizer/_ui).

The freeform UI path no longer authors JSX + imports; it emits one ``daisyui`` fence.
These cover the deterministic pieces: the single fence doc loads and covers the
components, and the system prompt embeds that doc and states the fence contract.
"""

from __future__ import annotations

from src.agents.visualizer import _ui
from src.docs_loader import load_doc


def test_fence_doc_is_loadable_and_covers_components():
    doc = load_doc(_ui._FENCE_DOC).lower()
    assert "daisyui" in doc
    for component in ("callout", "list", "steps", "chat-bubble", "mockup-window"):
        assert component in doc


def test_system_prompt_embeds_doc_and_states_fence_contract():
    system = _ui._SYSTEM.format(component_doc="DOC-MARKER")
    assert "DOC-MARKER" in system
    assert "```daisyui" in system
    # The contract forbids imports and JSX — assert the guidance is present.
    assert "no imports" in system.lower()
    assert "no jsx" in system.lower() or "`<component>`" in system.lower()
