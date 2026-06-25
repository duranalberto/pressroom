"""Agent 2 — Content Writer.

Writes the MDX publication body from the outline on the first pass,
or revises it based on reviewer feedback on subsequent passes.

Docs loaded:
  None — body-only writer rules are inline.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from src.llm import build_model, invoke_with_retry
from src.mdx_document import MDXDocument
from src.state import PublicationState
from src.template_config import apply_finetune
from src.agents._style import style_rules_block

_console = Console()

_SYSTEM = """\
You are an expert MDX body writer for theJournal at albertoduran.com.

You produce only the body of a publication: a strong hook, well-structured sections,
and natural prose that follows every rule below. Another pipeline step handles document
metadata, imports, and file assembly.

ABSOLUTE CONSTRAINTS:
- Regular code fences (```python, ```sql, ```bash, etc.) are allowed for code examples.
- Target reading time: 10-16 minutes (1,400-3,000 prose words, adjusted for code/diagrams).
- Use `##` for sections, `###` and `####` for subsections. NEVER use HTML heading tags
  (`<h2>`, `<h3>`, `<h4>` …) — they do not render.
- Every section planned in the outline MUST appear in the body as its own `## ` heading,
  written with the exact section title from the outline. NEVER write a section title as a
  plain paragraph or drop its `##` marker — a bare title line renders as body text, not a
  heading.
- Before every `##` heading output a `---` separator in this exact pattern:
    [blank line]
    ---
    [blank line]
    ## Section Title
    [blank line]
  Do NOT place `---` before `###` or `####` headings.
- Put every heading (`##`, `###`, `####`) on its own line with exactly one blank line
  before and after it.
- Hook paragraph: 40-90 words, no heading above it, signals problem + promises payoff.
- No H1 headings.
{style_rules}
- Do not add document metadata blocks, import statements, or file-level wrappers.

IMMUTABLE SYNTAX FROM THE OUTLINE:
- Treat every fenced code block from the outline as syntax, not prose. Preserve its
  language tag, content, and indentation exactly when it belongs in the body.
- Treat any MDX/JSX component syntax from the outline as read-only. Do not rename,
  edit, wrap, unwrap, or replace it.
- artifact-slot fences (```artifact-slot … ```) are code fences like any other. Copy
  them verbatim at their position. Do not read, interpret, or transform their content.
  Another pipeline step handles them entirely.
""".format(style_rules=style_rules_block())

_FIRST_DRAFT_PROMPT = """\
Write the MDX publication body based on the outline below.

OUTLINE:
{outline}

AUTHOR PREFERENCES:
- Tone: {tone}
- Audience: {audience}
- Additional context: {context}

Copy every artifact-slot fence from the outline verbatim at its position in the body.
Do NOT create diagrams, MDX components, UI components, or imports inline.
Do NOT add document metadata blocks, import statements, or file-level wrappers.
Do NOT wrap the output in code fences (no ```mdx or ``` markers around the whole body).
"""

_REVISION_PROMPT = """\
Revise the publication to address the reviewer's feedback. Fix every issue listed.
Preserve everything that was correct.

REVIEWER FEEDBACK (round {iteration}):
{feedback}

CURRENT DRAFT:
{draft}

AUTHOR PREFERENCES:
- Tone: {tone}
- Audience: {audience}
- Additional context: {context}

SOURCE MATERIAL (original petition — for reference when course-correcting):
{petition}

Deliver the complete revised body only.
Do NOT add document metadata blocks, import statements, or file-level wrappers.
Do NOT wrap the output in code fences (no ```mdx or ``` markers around the whole body).
"""


def _build_system(state: PublicationState) -> str:
    """Compose the writer system prompt, appending any template fine-tuning."""
    template = state.get("template_data") or {}
    return apply_finetune(_SYSTEM, template, "writer")


def run(state: PublicationState) -> dict:
    """Write the first draft or revise based on reviewer feedback.

    Reads: outline, tone, audience, additional_context, review_feedback,
           review_iteration, petition_content, template_data
    Writes: draft
    """
    iteration = state.get("review_iteration", 0)
    if iteration > 0:
        _console.print(f"  [blue]Content Writer:[/blue] revising draft (round {iteration})…")
    else:
        _console.print("  [blue]Content Writer:[/blue] writing first draft…")
    llm = build_model()

    feedback = state.get("review_feedback")

    if feedback and iteration > 0:
        current_doc = state.get("draft")
        current_body = current_doc["body"] if current_doc else ""
        user_msg = _REVISION_PROMPT.format(
            iteration=iteration,
            feedback=feedback,
            draft=current_body,
            tone=state.get("tone", "conversational"),
            audience=state.get("audience", "developers"),
            context=state.get("additional_context") or "none provided",
            petition=state.get("petition_content", "not available"),
        )
    else:
        user_msg = _FIRST_DRAFT_PROMPT.format(
            outline=state.get("outline", ""),
            tone=state.get("tone", "conversational"),
            audience=state.get("audience", "developers"),
            context=state.get("additional_context") or "none provided",
        )

    try:
        draft_str = invoke_with_retry(llm, [
            SystemMessage(content=_build_system(state)),
            HumanMessage(content=user_msg),
        ])
    except Exception as exc:
        _console.print(f"  [red]Content Writer:[/red] LLM call failed — {exc}")
        return {"errors": [f"Writer: LLM call failed — {exc}"]}

    return {"draft": MDXDocument(metadata={}, imports=[], body=draft_str.strip())}
