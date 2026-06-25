"""Agent 1 — Outline Designer.

Two-phase interaction:
  Phase 1 (before graph starts):  template questions answered in main.py and stored
                                   in state as tone / audience / additional_context.
  Phase 2 (this node runs):       reads that context, generates petition-specific
                                   follow-up questions WITH LLM-suggested defaults,
                                   interrupts for human input, then produces the outline
                                   .

Docs loaded:
  visual-components-menu.md   — component types, when to add a visual, placeholder format
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from rich.console import Console

from src.config import Config
from src.docs_loader import load_doc, load_template
from src.llm import build_model, invoke_with_retry
from src.state import PublicationState
from src.template_config import apply_finetune, outline_structure
from src.visuals import registry as visual_registry

_console = Console()

_SYSTEM_INTERVIEW = """\
You are a publication outline designer for theJournal, the blog section of albertoduran.com.

Right now you are doing ONE job: interviewing the author. Read the petition and the
preferences they already gave (tone, audience, context), then ask only for what is still
missing. You are NOT designing the outline yet, and you are NOT planning any visuals — so do
not mention sections, charts, diagrams, or components. Keep your whole attention on
surfacing the few decisions that most shape a publication's angle, depth, and scope.

## TEMPLATE USED

{template_context}
"""

_SYSTEM = """\
You are a publication outline designer for theJournal, the blog section of albertoduran.com.

Your job: design a detailed, section-by-section outline for the publication body, using the
petition and the author's answers. The follow-up interview is already done — the answers are
in the user message.

## BODY PLANNING RULES

- Plan only the body of the publication.
- The body starts with a 40-90 word hook paragraph, with no heading above it.
- The body uses `##` sections with optional `###` and `####` subsections. Use `###`/`####` to break up long sections. 
  Do not plan a `#` heading.
- Every `##` section will be preceded by a `---` separator in the final body.
- Target reading time is 10-16 minutes, roughly 1,400-3,000 prose words.
- Plan concrete claims, examples, and technical details only when supported by the petition
  or user-provided context. Do not invent facts or data.

## VISUAL COMPONENTS AVAILABLE

{visual_menu}

## TEMPLATE USED

{template_context}
"""

_QUESTIONS_PROMPT = """\
The author has already answered the following baseline questions for this publication:

TONE: {tone}
AUDIENCE: {audience}
INITIAL CONTEXT:
{initial_context}

Do NOT generate questions that repeat what is already answered above. Focus only on
petition-specific gaps — details unique to this article that are not covered above.

PETITION CONTENT:
{petition}

Generate 3-5 targeted follow-up questions. For each question, provide your best assumed
default answer — the response you would most likely select if you were writing this article
yourself. The user can accept your default by pressing Enter without typing anything.

Focus on:
- The specific angle, perspective, or emphasis for this exact topic
- Technical decisions, trade-offs, or design choices worth exploring
- Concrete data, examples, benchmarks, or case studies to include
- Scope boundaries: what to include vs. exclude, depth per section
- Related content, prior work, or resources to reference

Output format (use exactly — it is parsed programmatically):

UNDERSTANDING:
[your 2-sentence summary of what this publication is about and its main value]

QUESTIONS:
1. [question text]
   DEFAULT: [your best assumed answer]
2. [question text]
   DEFAULT: [your best assumed answer]
3. [question text]
   DEFAULT: [your best assumed answer]
"""

_OUTLINE_PROMPT = """\
Design a detailed publication outline.

PETITION CONTENT:
{petition}

USER PREFERENCES:
- Tone: {tone}
- Audience: {audience}
- Full context from Q&A:
{context}

Produce the outline in this format:

## Planning Notes
- type: [standalone | vault — with rationale]

## Hook Concept
[What the 40-90 word opening paragraph will establish — the problem signaled, the payoff promised, the opening move]

## Section Plan

List each body section as a `###` heading whose text is the EXACT section title (the writer
copies this title verbatim into the body as a `## ` heading, so write a clean, final title —
no brackets, no annotations):

### Section Title Goes Here
- Key points: ...
- Est. words: ~XXX

[If a visual would genuinely help this section, place an artifact-slot fence here.
 The context must be a detailed creation prompt for the visualizer: include component
 type, all data values or node names, title, configuration.
 Do NOT use double-quote characters inside the context string.]

```artifact-slot
id="<kebab-id>" context="<full creation prompt>"
```

### Next Section Title
...
[Omit the fence entirely if no visual is needed for this section.]

CODE FENCE RULES:
- Visual component placeholders ONLY: use the artifact-slot fence shown above.
- Code examples in section descriptions: use a standard language fence (```python,
  ```sql, ```bash, etc.). These pass through as-is to the final article.
- Never use artifact-slot for a real code example.

## Totals
- Estimated word count: X,XXX-X,XXX words
- Estimated reading time: XX-XX minutes

VISUAL PLACEMENT RULES:
- Add at most one visual per section. Only add one when it genuinely helps the reader.
- PRECONFIGURED VISUALS (listed in your system prompt) are already wired to the input data.
  Place each one's artifact-slot fence verbatim in its named section. Do NOT add a `context`,
  `data`, numbers, or an option object — they render deterministically.
- For any OTHER visual, prefer a visual template: add a fence with `template="<id>"` choosing
  an id from VISUAL TEMPLATES AVAILABLE. Charts (echart) MUST use a template.
- For a Mermaid diagram or a one-off UI component with no template, write a freeform fence
  with a `context` creation brief. Start a Mermaid context with the exact target, such as
  `Mermaid flowchart TD`, `Mermaid sequenceDiagram`, `Mermaid erDiagram`, or `Mermaid gantt`,
  then specify the nodes, labels, and direction. Reference only data present in the petition.
- Ids must be unique across the outline and use lowercase kebab-case.
- Do NOT try to write the actual MDX — the visualizer node renders every artifact.
"""


def _build_template_context(template: dict) -> str:
    """Format a template's name, goal, structure, and config into a prompt block.

    Args:
        template: Loaded template dict (from ``load_template``).

    Returns:
        Multi-line string block describing the template for injection into the
        outline system prompt.
    """
    lines = [f"Template: {template.get('name', 'default')}"]
    description = (template.get("description") or "").strip()
    if description:
        first_line = description.split("\n")[0].strip()
        lines.append(f"Description: {first_line}")

    # Publication goal — the strongest constraint on what the outline must produce.
    goal = (template.get("goal") or "").strip()
    if goal:
        lines.append("\nPublication Goal (follow this precisely):")
        for goal_line in goal.splitlines():
            stripped = goal_line.strip()
            if stripped:
                lines.append(f"  {stripped}")

    # Recommended section structure — guide the outline agent on section order and content.
    structure = outline_structure(template)
    if structure:
        lines.append(
            "\nRequired Publication Structure (use these sections in this order; "
            "you may add sub-sections but do not remove or reorder these `##` sections):"
        )
        for i, section in enumerate(structure, 1):
            title = section.get("title", "")
            desc = (section.get("description") or "").strip().replace("\n", " ")
            lines.append(f"  {i}. {title}")
            if desc:
                lines.append(f"     → {desc}")

    # Config fields already answered — do not ask the user again for these.
    config = template.get("config", [])
    if config:
        lines.append("\nConfiguration already collected (do not ask again):")
        for field in config:
            label = field.get("label", field.get("field", ""))
            hint = field.get("hint", "")
            lines.append(f"  - {label}" + (f" ({hint})" if hint else ""))

    return "\n".join(lines)


def _build_visuals_block(template: dict) -> str:
    """Build the visual-templates menu and preconfigured-visuals block for the outline.

    The outline sees which templates exist and how to place them, but never the
    render internals. Preconfigured visuals list the exact fence the outline must
    copy verbatim into the correct section.

    Args:
        template: Loaded template dict (from ``load_template``).

    Returns:
        Multi-line string ready to append to the outline system prompt, or
        ``""`` when neither a template menu nor preconfigured visuals exist.
    """
    lines: list[str] = []

    menu = visual_registry.menu()
    if menu:
        lines.append("## VISUAL TEMPLATES AVAILABLE")
        lines.append("")
        lines.append(
            "Reference one by id on an artifact-slot fence (template=\"<id>\") to request a "
            "deterministic visual. Charts must use a template."
        )
        for entry in menu:
            lines.append(f"  - {entry['id']} ({entry['kind']}/{entry['type']}) — {entry['summary']}")
        lines.append("")

    visuals = template.get("visuals") or []
    if visuals:
        titles = {
            s.get("id"): (s.get("title") or "").strip()
            for s in outline_structure(template) if isinstance(s, dict)
        }
        lines.append("## PRECONFIGURED VISUALS (place each fence verbatim in its section)")
        lines.append("")
        for v in visuals:
            section = v.get("section", "")
            where = titles.get(section) or section or "the most relevant section"
            lines.append(f'- In section "{where}", place this fence:')
            lines.append("```artifact-slot")
            lines.append(f'id="{v.get("id", "")}" template="{v.get("template", "")}"')
            lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip()


def _resolve_template(state: PublicationState) -> dict:
    """Return the template from state, loading it from disk as a fallback.

    The loader node pre-loads the template into state so downstream nodes
    do not re-read disk. This fallback keeps the outline builders usable in
    isolation and in tests where the loader has not run.

    Returns:
        Loaded template dict, or a minimal ``{"name": "default", "questions": []}``
        if the template file is not found.
    """
    template = state.get("template_data") or {}
    if not template:
        template_name = state.get("template_name", "default") or "default"
        try:
            template = load_template(template_name)
        except FileNotFoundError:
            template = {"name": "default", "questions": []}
    return template


def _build_interview_system(state: PublicationState) -> str:
    """Compose the lean interview system prompt.

    The interview node only asks follow-up questions, so it deliberately omits the visual
    menu, artifact-placement rules, and input-file schema that the outline node needs.
    Carrying that ~1,200-word block here only distracts the model from the one job of
    surfacing gaps — keeping it out is what makes the questions sharp on a local model.
    """
    template = _resolve_template(state)
    system = _SYSTEM_INTERVIEW.format(template_context=_build_template_context(template))
    return apply_finetune(system, template, "outline")


def _build_system(state: PublicationState) -> str:
    """Compose the outline system prompt (visual menu + template context + input schema).

    Prefers the template already loaded into state by the loader node; falls back to
    loading it directly so the function stays usable in isolation (and in tests).
    """
    template = _resolve_template(state)
    system = _SYSTEM.format(
        visual_menu=load_doc("visual-components-menu.md"),
        template_context=_build_template_context(template),
    )
    visuals_block = _build_visuals_block(template)
    if visuals_block:
        system += "\n\n" + visuals_block
    system += _build_input_files_context(state)
    return apply_finetune(system, template, "outline")


def _json_schema_lines(data: Any, depth: int = 2, indent: int = 4) -> list[str]:
    """Return indented key-skeleton lines for a JSON dict up to ``depth`` levels.

    Args:
        data: The parsed JSON value. Only dicts produce output; other types
            return ``[]``.
        depth: Maximum nesting depth to expand. At depth 0 returns ``[]``.
        indent: Number of spaces for each indentation level.

    Returns:
        List of indented strings suitable for appending to a prompt block.
    """
    if not isinstance(data, dict) or depth == 0:
        return []
    pad = " " * indent
    keys_line = f"{pad}keys: {', '.join(data.keys())}"
    lines = [keys_line]
    for k, v in data.items():
        if isinstance(v, dict) and v:
            child_keys = ", ".join(v.keys())
            lines.append(f"{pad}{k} → {child_keys}")
    return lines


def _build_input_files_context(state: PublicationState) -> str:
    """List the input files the outline may reference in `data=` directives.

    For JSON files, emits a two-level schema skeleton (top-level keys + each dict
    child's keys) so the LLM can reference exact paths rather than guessing them.
    """
    files = state.get("input_files") or []
    if not files:
        return ""

    input_dir = Path(state.get("input_dir") or Config().input_dir)
    lines: list[str] = []
    for f in files:
        name = f["name"]
        lines.append(f"  - {name}")
        if name.endswith(".json"):
            try:
                data = json.loads((input_dir / name).read_text(encoding="utf-8"))
                lines.extend(_json_schema_lines(data))
            except Exception:
                pass  # degrade gracefully — file name still listed above

    return (
        "\n\n## INPUT FILES AVAILABLE (for data= directives)\n\n"
        + "\n".join(lines)
        + "\n"
    )


def run_interview(state: PublicationState) -> dict:
    """Generate petition-specific follow-up questions and commit them to state.

    Runs as its own node so the LLM call commits before the outline node
    interrupts for human input. On resume, the outline node reads the already-
    committed questions instead of regenerating them, so this work runs exactly
    once per pipeline run.

    Reads: petition_content, tone, audience, additional_context, template_data
    Writes: followup_questions, tone, audience
    """
    _console.print("  [green]Outline Designer:[/green] analyzing petition and generating questions…")
    llm = build_model()
    system = _build_interview_system(state)

    # Template answers already in state from Phase 1 collection in main.py
    tone = state.get("tone") or "conversational"
    audience = state.get("audience") or "developers and technical readers"
    initial_context = state.get("additional_context") or "none provided"

    questions = invoke_with_retry(llm, [
        SystemMessage(content=system),
        HumanMessage(content=_QUESTIONS_PROMPT.format(
            petition=state["petition_content"],
            tone=tone,
            audience=audience,
            initial_context=initial_context,
        )),
    ])

    _console.print("  [green]Outline Designer:[/green] questions ready — waiting for your input…")
    return {"followup_questions": questions, "tone": tone, "audience": audience}


def run(state: PublicationState) -> dict:
    """Interrupt for human follow-up answers, then generate the section outline.

    Reads the questions already committed by ``run_interview``. On resume, only
    this node replays — no LLM work is repeated before the interrupt resolves.

    Reads: followup_questions, tone, audience, additional_context,
           petition_content, template_data, input_files, input_dir
    Writes: outline, tone, audience, additional_context
    """
    # Step 1 — interrupt: pause for human follow-up input. Everything before this line
    # re-runs on resume, so it must stay cheap and side-effect free (no LLM calls).
    user_input: dict = interrupt({
        "agent": "outline_designer",
        "questions": state.get("followup_questions", ""),
    })

    # Receive only follow-up answers; tone/audience already in state
    followup_context = user_input.get("followup_context", "")
    combined_context = "\n\n".join(filter(None, [
        state.get("additional_context", ""),
        followup_context,
    ])) or "none provided"

    _console.print("  [green]Outline Designer:[/green] generating section outline…")

    tone = state.get("tone") or "conversational"
    audience = state.get("audience") or "developers and technical readers"
    system = _build_system(state)
    llm = build_model()

    # Step 2 — generate the outline with the full picture
    outline = invoke_with_retry(llm, [
        SystemMessage(content=system),
        HumanMessage(content=_OUTLINE_PROMPT.format(
            petition=state["petition_content"],
            tone=tone,
            audience=audience,
            context=combined_context,
        )),
    ])

    return {
        "outline": outline,
        "tone": tone,
        "audience": audience,
        "additional_context": combined_context,
    }
