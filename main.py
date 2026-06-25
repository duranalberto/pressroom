#!/usr/bin/env python3
"""
theJournal Publication Pipeline
================================
Multi-agent LangChain/LangGraph system that turns a petition brief into a
publication-ready .mdx file for albertoduran.com.

Usage
-----
  python main.py run                             # reads all files from input/
  python main.py run --input path/to/dir         # custom input directory
  python main.py run --template finance-analysis # use a specific question template
  python main.py run --max-iterations 2          # tighter review loop
  python main.py templates                       # list available templates
"""

from __future__ import annotations

import datetime
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import typer
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from src.agents.loader import _discover_files
from src.audit import (
    NODE_TO_STEP,
    allocate_run_id,
    format_run_id,
    run_dir as audit_run_dir,
    write_step_body,
)
from src.config import BASE_DIR, Config
from src.docs_loader import list_templates, load_template
from src.graph import build_graph
from src.llm import check_ollama
from src.state import PublicationState

app = typer.Typer(
    name="thejournal",
    help="Multi-agent publication pipeline for theJournal at albertoduran.com.",
)
console = Console()


# ── Node display ─────────────────────────────────────────────────────────────

def _show_node(name: str, output: dict) -> None:
    labels = {
        "loader":           ("Loader",            "bright_black"),
        "interview":        ("Outline Designer", "green"),
        "outline_designer": ("Outline Designer", "green"),
        "visualizer":       ("Visualizer",        "blue"),
        "writer":           ("Content Writer",    "blue"),
        "reviewer":         ("Reviewer",           "yellow"),
        "humanizer":        ("Humanizer",          "magenta"),
        "metadata":         ("Metadata",           "bright_magenta"),
        "publisher":        ("Publisher",          "cyan"),
    }
    label, color = labels.get(name, (name, "white"))
    console.print(Rule(f"[bold {color}]{label}[/bold {color}]"))

    if name == "outline_designer" and output.get("outline"):
        preview = output["outline"][:600].strip()
        console.print(Panel(preview + (" …" if len(output["outline"]) > 600 else ""),
                            title="Outline preview", border_style=color))

    elif name == "writer":
        draft_doc = output.get("draft") or {}
        body = draft_doc.get("body", "") if isinstance(draft_doc, dict) else ""
        words = len(body.split())
        console.print(f"  Draft: ~{words:,} words")

    elif name == "reviewer":
        if output.get("review_approved"):
            console.print("  [green]Approved[/green]")
        else:
            iteration = output.get("review_iteration", "?")
            console.print(f"  [yellow]Issues found — round {iteration}[/yellow]")
            feedback = output.get("review_feedback", "")
            if feedback:
                console.print(Panel(feedback[:800], title="Feedback", border_style="yellow"))

    elif name == "humanizer":
        console.print("  Humanization complete")

    elif name == "publisher":
        path = output.get("output_path", "")
        if path:
            console.print(f"  Saved to [bold]{path}[/bold]")


# ── Question parsing ──────────────────────────────────────────────────────────

def _extract_understanding(text: str) -> str:
    """Pull the UNDERSTANDING block from the LLM output."""
    m = re.search(r"UNDERSTANDING:\s*(.*?)(?=QUESTIONS:|$)", text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _parse_questions_with_defaults(text: str) -> list[dict[str, str]]:
    """Extract questions and their LLM-suggested defaults from the QUESTIONS block.

    Returns a list of {text, default} dicts. `default` is an empty string when the
    LLM omitted a DEFAULT line (the user must type an answer).
    """
    m = re.search(r"QUESTIONS:\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return []

    results: list[dict[str, str]] = []
    current_text: str | None = None
    current_default = ""

    for line in m.group(1).splitlines():
        stripped = line.strip()
        q_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        d_match = re.match(r"^DEFAULT:\s*(.+)$", stripped, re.IGNORECASE)

        if q_match:
            if current_text is not None:
                results.append({"text": current_text, "default": current_default.strip()})
            current_text = q_match.group(1).strip()
            current_default = ""
        elif d_match and current_text is not None:
            current_default = d_match.group(1).strip()
        elif stripped and current_text is not None and not current_default:
            # Continuation of the default on the next line
            current_default += " " + stripped

    if current_text is not None:
        results.append({"text": current_text, "default": current_default.strip()})

    return results


# ── Template configuration (Phase 1 — before graph starts) ───────────────────

def _collect_template_answers(template: dict[str, Any], ask_all: bool = False) -> dict:
    """Resolve template configuration before the graph starts.

    Silent mode (default):
      Fields with a non-empty default → applied silently, shown as a dim summary.
      Fields with an empty default    → user is prompted (required input).

    Interactive mode (ask_all=True / --ask flag):
      All fields are prompted; existing defaults are pre-filled.

    Returns: {tone, audience, additional_context}
    """
    config_fields = template.get("config", [])
    template_name = template.get("name", "default")

    # Categorise fields
    silent_fields: list[dict] = []   # has non-empty default AND not ask_all
    prompt_fields: list[dict] = []   # must be prompted

    for f in config_fields:
        default = (f.get("default") or "").strip()
        if default and not ask_all:
            silent_fields.append(f)
        else:
            prompt_fields.append(f)

    # ── Header ──────────────────────────────────────────────────────────────
    header = "[bold]Step 1 — Configuration[/bold]"
    if ask_all:
        header += "  [dim](--ask: all fields shown)[/dim]"
    console.print(Rule(header))
    console.print()
    console.print(f"[bold]Template:[/bold] {template_name}")
    console.print()

    # ── Silently-applied defaults ────────────────────────────────────────────
    if silent_fields:
        console.print("[dim]Applied from defaults:[/dim]")
        for f in silent_fields:
            label = f.get("label", f.get("field", ""))
            default = (f.get("default") or "").strip()
            console.print(f"  [dim]{label} → {default}[/dim]")
        console.print()

    # ── Prompt for fields that need user input ───────────────────────────────
    prompted_answers: dict[str, str] = {}
    if prompt_fields:
        for f in prompt_fields:
            field = f.get("field", "")
            label = f.get("label", field)
            hint = f.get("hint", "")
            default = (f.get("default") or "").strip()
            prompt_text = f"{label}  [{hint}]" if hint else label
            prompted_answers[field] = Prompt.ask(prompt_text, default=default)
        console.print()
    elif not ask_all:
        console.print("[dim]No additional input required. Use --ask to override any default.[/dim]")
        console.print()

    # ── Assemble full answer dict (template field order preserved) ───────────
    answers: dict[str, str] = {}
    for f in config_fields:
        field = f.get("field", "")
        default = (f.get("default") or "").strip()
        answers[field] = prompted_answers.get(field, default)

    # Extract well-known state fields; everything else goes into additional_context
    tone = answers.pop("tone", "conversational") or "conversational"
    audience = answers.pop("audience", "developers and technical readers") or "developers and technical readers"

    context_parts: list[str] = []
    for f in config_fields:
        field = f.get("field", "")
        if field in ("tone", "audience"):
            continue
        value = (answers.get(field) or "").strip()
        if value:
            context_parts.append(f"{f.get('label', field)}: {value}")

    return {
        "tone": tone,
        "audience": audience,
        "additional_context": "\n\n".join(context_parts),
    }


# ── Follow-up Q&A (Phase 2 — after outline designer generates questions) ─────

def _collect_followup_answers(interrupt_value: dict) -> dict:
    """Show the LLM's understanding, then ask its follow-up questions with defaults.

    Each question uses the LLM's suggested answer as the default — the user presses
    Enter to accept it or types their own answer.

    Returns: {followup_context} — a formatted string merged into additional_context.
    """
    llm_output = interrupt_value.get("questions", "")
    understanding = _extract_understanding(llm_output)
    questions = _parse_questions_with_defaults(llm_output)

    # ── Understanding panel ──────────────────────────────────────────────────
    if understanding:
        console.print()
        console.print(Panel(
            understanding,
            title="[bold green]Outline Designer — Understanding[/bold green]",
            border_style="green",
        ))

    # ── Follow-up questions ──────────────────────────────────────────────────
    context_parts: list[str] = []

    if questions:
        console.print()
        console.print(Rule("[bold]Step 2 — Follow-up questions[/bold]"))
        console.print()
        console.print("[dim]The outline designer needs a few more details specific to this article.[/dim]")
        console.print("[dim]Press Enter to accept the suggested answer, or type your own.[/dim]")
        console.print()
        for i, q in enumerate(questions, 1):
            default = q["default"]
            prompt_text = f"Q{i}  {q['text']}"
            answer = Prompt.ask(prompt_text, default=default)
            if answer.strip():
                context_parts.append(f"Q: {q['text']}\nA: {answer.strip()}")
    else:
        # Graceful fallback when LLM output didn't follow the expected format
        console.print()
        extra = Prompt.ask(
            "Additional context for the outline designer  (press Enter to skip)",
            default="",
        )
        if extra.strip():
            context_parts.append(extra.strip())

    console.print()
    return {"followup_context": "\n\n".join(context_parts)}


# ── State snapshot ────────────────────────────────────────────────────────────

def _save_state_snapshot(node: str, state_values: dict, output_dir: Path) -> None:
    """Overwrite output/pipeline_state.json with the current pipeline state."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "_saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "_last_node": node,
            **state_values,
        }
        (output_dir / "pipeline_state.json").write_text(
            json.dumps(snapshot, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        console.print(f"[dim]Warning: could not save state snapshot — {exc}[/dim]")


# ── Audit trail ───────────────────────────────────────────────────────────────

def _save_audit_step(node: str, state_values: dict, run_dir: Path) -> None:
    """Snapshot the body delivered by an intermediary step into the run's audit dir.

    Only the four intermediary nodes in NODE_TO_STEP produce a body worth tracing:
    outline (a string), writer/humanizer (the MDX body, no frontmatter), and reviewer
    (its feedback verdict). Writer and reviewer fire once per review round; the file
    holds the last round, while pipeline_state.json carries the full per-round history.
    """
    step = NODE_TO_STEP.get(node)
    if not step:
        return

    if node == "outline_designer":
        body = state_values.get("outline") or ""
    elif node == "writer":
        draft = state_values.get("draft") or {}
        body = draft.get("body", "") if isinstance(draft, dict) else ""
    elif node == "reviewer":
        body = state_values.get("review_feedback") or ""
    elif node == "humanizer":
        humanized = state_values.get("humanized") or {}
        body = humanized.get("body", "") if isinstance(humanized, dict) else ""
    else:  # pragma: no cover - guarded by NODE_TO_STEP
        return

    write_step_body(run_dir, step, body)


# ── CLI commands ──────────────────────────────────────────────────────────────

@app.command(name="templates")
def list_templates_cmd() -> None:
    """List all available question templates."""
    entries = list_templates()
    if not entries:
        console.print("[yellow]No templates found in the templates/ directory.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Available Templates", border_style="blue")
    table.add_column("File (--template)", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Description")

    for e in entries:
        table.add_row(e["file"], e["name"], e["description"])

    console.print(table)


@app.command()
def run(
    input_dir: Path = typer.Option(
        Path("input"),
        "--input", "-i",
        help="Directory with petition files (.md / .mdx / .txt)",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Directory for the final .mdx file (default: output/)",
    ),
    template: str = typer.Option(
        "default",
        "--template", "-t",
        help="Configuration template to use (filename without .yaml, from templates/ directory)",
    ),
    ask: bool = typer.Option(
        False,
        "--ask", "-a",
        help="Prompt for every configuration field, even those with defaults.",
    ),
    max_iterations: int = typer.Option(
        3,
        "--max-iterations", "-m",
        help="Maximum reviewer → writer revision loops",
    ),
    thread_id: str = typer.Option(
        "",
        "--thread-id",
        help="LangGraph checkpoint thread ID. Defaults to a new UUID per run.",
    ),
) -> None:
    """Run the full publication pipeline."""

    cfg = Config()
    effective_thread_id = thread_id or str(uuid.uuid4())

    check_ollama()

    if not input_dir.exists():
        console.print(f"[red]Input directory not found: {input_dir}[/red]")
        raise typer.Exit(1)

    # Load template early to fail fast if it doesn't exist
    try:
        template_data = load_template(template)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    effective_output = output_dir or cfg.output_dir

    # Allocate a numeric run id from the git-ignored counter. It prefixes the final
    # filename and names this run's audit directory under output/audit/<id>/.
    run_id = format_run_id(allocate_run_id(BASE_DIR / ".run_id"))
    run_audit_dir = audit_run_dir(effective_output, run_id)

    console.print(Panel(
        f"[bold]theJournal Publication Pipeline[/bold]\n"
        f"Run #{run_id}  ·  Template: {template_data.get('name', template)}\n"
        "Load → Outline → Visualize → Write → Review → Humanize → Metadata → Publish",
        border_style="blue",
    ))

    # Fail fast if the input directory has no readable petition files. The loader
    # node performs the actual reading once the graph starts.
    if not _discover_files(input_dir):
        console.print(f"[red]No .md / .mdx / .txt / .json files found in {input_dir}[/red]")
        raise typer.Exit(1)

    # ── Phase 1: resolve template configuration before the graph starts ──────
    template_answers = _collect_template_answers(template_data, ask_all=ask)

    graph = build_graph()
    graph_config = {"configurable": {"thread_id": effective_thread_id}}

    initial: PublicationState = {
        "input_dir": str(input_dir),
        "petition_content": "",
        "input_file_paths": [],
        "input_files": [],
        "template_name": template,
        "template_data": {},
        "run_id": run_id,
        # Template answers go directly into state
        "tone": template_answers["tone"],
        "audience": template_answers["audience"],
        "additional_context": template_answers["additional_context"],
        "followup_questions": None,
        "outline": None,
        "draft": None,
        "humanized": None,
        "metadata": None,
        "final_publication": None,
        "artifacts": [],
        "review_feedback": None,
        "review_iteration": 0,
        "max_iterations": max_iterations,
        "review_approved": False,
        "output_path": None,
        "errors": [],
    }

    console.print(Rule("[bold]Pipeline starting[/bold]"))

    # ── Phase 2: graph runs until outline designer interrupts ─────────────────
    interrupted = False
    interrupt_value: dict = {}

    try:
        for event in graph.stream(initial, graph_config, stream_mode="updates"):
            if "__interrupt__" in event:
                interrupted = True
                interrupt_value = event["__interrupt__"][0].value
                break
            for node, output in event.items():
                if not node.startswith("__"):
                    _show_node(node, output)
                    snap = graph.get_state(graph_config)
                    values = dict(snap.values)
                    _save_state_snapshot(node, values, effective_output)
                    _save_state_snapshot(node, values, run_audit_dir)
                    _save_audit_step(node, values, run_audit_dir)
    except Exception as exc:
        console.print(f"[red]Pipeline error: {exc}[/red]")
        raise typer.Exit(1) from exc

    # ── Phase 3: follow-up questions (with LLM-generated defaults) ───────────
    if interrupted:
        followup = _collect_followup_answers(interrupt_value)
        try:
            for event in graph.stream(Command(resume=followup), graph_config, stream_mode="updates"):
                for node, output in event.items():
                    if not node.startswith("__"):
                        _show_node(node, output)
                        snap = graph.get_state(graph_config)
                        values = dict(snap.values)
                        _save_state_snapshot(node, values, effective_output)
                        _save_state_snapshot(node, values, run_audit_dir)
                        _save_audit_step(node, values, run_audit_dir)
        except Exception as exc:
            console.print(f"[red]Pipeline error after resume: {exc}[/red]")
            raise typer.Exit(1) from exc

    # ── Final status ──────────────────────────────────────────────────────────
    final_state = graph.get_state(graph_config)
    output_path = final_state.values.get("output_path")
    errors = final_state.values.get("errors", [])

    console.print()
    if output_path:
        console.print(Panel(
            f"[green]Done![/green]\n\nPublication saved to:\n[bold]{output_path}[/bold]",
            border_style="green",
        ))
    else:
        console.print("[red]Pipeline finished but no output file was produced.[/red]")

    if errors:
        console.print("[yellow]Errors recorded:[/yellow]")
        for err in errors:
            console.print(f"  - {err}")


if __name__ == "__main__":
    app()
