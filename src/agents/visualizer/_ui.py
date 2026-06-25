"""UI Component sub-agent — generates a static ``daisyui`` publication fence for a
one-off Callout, ChatBubble, List, Steps, SectionHeader, or Mockup* component.

Public interface:
    render(artifact_id, context, llm) -> str

The returned string is a single fenced ```daisyui block holding one JSON object — no
imports, no JSX. The orchestrator (__init__.py) validates the fence JSON and assembles
the Artifact.

Prompt strategy: load ONE focused fence doc (DAISYUI_FENCES.md) rather than the seven
per-component Astro docs. A single compact doc keeps local Ollama models reliable while
covering every publication component in one JSON schema, and the fence contract removes
the whole class of import/closing-tag mistakes the old JSX prompt had to police.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.docs_loader import load_doc
from src.llm import invoke_with_retry
from src.visuals.registry import VisualTemplate
from src.visuals.render import render_visual

# Single fence schema doc covering every publication component. Kept small on purpose:
# loading all seven Astro component docs (~1,100 lines) overloads local Ollama models.
_FENCE_DOC = "DAISYUI_FENCES.md"

_SYSTEM = """\
You are a UI component specialist for theJournal at albertoduran.com.

Your only job: produce ONE static publication component as a fenced ```daisyui block
holding a single strict JSON object, for the component described in the creation prompt.

## COMPONENT DOCUMENTATION

{component_doc}

ABSOLUTE RULES:
- Output ONLY the fenced block: ```daisyui, then the JSON object, then the closing ```.
  Nothing else — no prose, no explanation, no imports, no JSX or `<Component>` tags.
- The JSON must be strict: double quotes, no comments, no trailing commas, no functions,
  no undefined, only finite numbers.
- Use exactly one `"component"` value from the documentation. Do not invent fields.
- Content block text is escaped — no inline Markdown or HTML. For a link, use a `link`
  content block, never `[text](url)`.
- Use realistic, contextually appropriate content — not lorem-ipsum placeholders.
"""

_PROMPT = """\
Create the daisyui fence for this UI component.

Artifact id: {artifact_id}

Creation prompt:
{context}

Output ONLY the fenced ```daisyui block containing one JSON object.
"""


def render_template(
    template: VisualTemplate,
    data: dict[str, Any],
    params: dict[str, Any],
) -> tuple[list[str], str]:
    """Render a UI visual template to ``(import_lines, body)`` deterministically.

    The templated path for UI components (e.g. a verdict Callout) fills a fixed daisyui
    fence with extracted values, so no LLM authoring is needed. Non-templated UI slots still
    use the freeform :func:`render` above.
    """
    return render_visual(template, data=data, params=params)


def render(artifact_id: str, context: str, llm) -> str:
    """Generate a one-off daisyui component fence from the creation prompt."""
    cold_llm = llm.model_copy(update={"temperature": 0.5, "validate_model_on_init": False})
    system = _SYSTEM.format(component_doc=load_doc(_FENCE_DOC))
    return invoke_with_retry(cold_llm, [
        SystemMessage(content=system),
        HumanMessage(content=_PROMPT.format(
            artifact_id=artifact_id,
            context=context.strip(),
        )),
    ])
