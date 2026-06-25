# theJournal — Agent Instructions

This file is the single source of truth for any AI coding agent working in this repository
(Claude Code, OpenAI Codex, Cursor, Copilot, or similar).

---

## Project overview

LangGraph pipeline that converts petition briefs from `input/` into `.mdx`
publications saved to `output/`. Pipeline stages in order:

```
loader → interview → outline_designer → visualizer → writer
       → reviewer ⇄ writer → humanizer → metadata → publisher
```

- `loader` reads input files + the template into state (first node).
- `interview` generates the follow-up questions; `outline_designer` interrupts for the
  human answers (kept separate so the question LLM call is not re-run on resume).
- `metadata` designs the frontmatter (title/description/tags) with an LLM, guided by the
  template's optional `frontmatter` section, falling back to deterministic derivation.
- Agents: `src/agents/{loader,outline,visualizer,writer,reviewer,humanizer,metadata,publisher}.py`
  (the `interview` node is `outline.run_interview`).
- Graph wiring and review-loop routing: `src/graph.py`
- Shared state schema: `src/state.py`
- MDX parsing/rendering utilities: `src/mdx_document.py`
- CLI entry point: `main.py` (Typer + Rich)

---

## Rules for every implementation task

### 1. Run the test suite before reporting done

```bash
venv/bin/python -m pytest tests/ -v
```

All tests must pass. Fix failures before finishing — never skip with `-k` or `--ignore`.

### 2. Update tests whenever you modify source code

When you change a source file, update the corresponding test file in `tests/` so the tests
reflect the new behaviour. This applies to:

- **Changed logic** — update assertions to match the new expected output.
- **Renamed function or argument** — update every reference in the test file.
- **Deleted function** — remove the tests for it.
- **New function or branch** — add tests that cover it.
- **Bug fix** — add a test that would have caught the bug (regression test).

Do not leave tests that pass only because they still test the old, pre-change behaviour.
Do not leave tests that now fail silently because an assertion was too loose.

### 3. New behaviour must have tests

If you add a new pure function, new conditional branch, or new helper, write at least one
test for the happy path and one for the edge/failure path before calling the task done.

---

## Test coverage map

| Source file | Test file | Functions covered |
|---|---|---|
| `src/mdx_document.py` | `tests/test_mdx_document.py` | `_fm_value`, `parse_mdx`, `render_mdx`, `strip_em_dashes` |
| `src/agents/publisher.py` | `tests/test_publisher.py` | `_slug_from_metadata`, `_inject_artifacts`, `_merge_artifact_imports`, `_strip_remaining_placeholders`, `run` |
| `src/agents/metadata.py` | `tests/test_metadata.py` | `_format_frontmatter_guidance`, `_title_from_body`, `_first_prose_paragraph`, `_truncate_description`, `_derive_tags`, `_assemble`, `run` |
| `src/graph.py` | `tests/test_graph_routing.py` | `_route_review` |
| `src/llm.py` | `tests/test_llm.py` | `strip_fences` |
| `src/agents/visualizer/` | `tests/test_visualizer.py` | `_split_imports`, `_classify_artifact`, `_validate_artifact` (fence JSON), `_prepare`, `run` (templated + freeform) |
| `src/agents/visualizer/_ui.py` | `tests/test_ui_fence.py` | daisyui-fence contract (doc loads, prompt embeds it) |
| `src/json_query.py` | `tests/test_json_query.py` | `query`, `JsonQueryError` (navigation, `last=`, sandbox, cache) |
| `src/agents/visualizer/_databind.py` | `tests/test_databind.py` | `parse_slots`, `parse_inline_params`, `parse_data_spec`, `resolve_spec`, `substitute_data_tokens` |
| `src/agents/visualizer/_echart.py` | `tests/test_echart.py` | `render_template` (deterministic fill) |
| `src/agents/visualizer/_mermaid.py` | `tests/test_mermaid.py` | `sanitize` (label quoting, de-chaining), `render` (doc loading) |
| `src/agents/visualizer/_extractor.py` | `tests/test_extractor.py` | `looks_like_spec`, `resolve` (static + intent + transform) |
| `src/visuals/registry.py` | `tests/test_visual_registry.py` | `load_visuals`, `get`, `menu`, tolerant loading |
| `src/visuals/render.py` | `tests/test_visual_render.py` | `render_visual` (token namespaces, labels, failures) |
| `src/agents/humanizer.py` | `tests/test_humanizer.py` | `_preserves_structure`, `_extract_mdx_component_blocks` |
| `src/docs_loader.py` | `tests/test_docs_loader.py` | `load_doc`, `load_skill` (caching) |
| `src/agents/loader.py` | `tests/test_loader.py` | `_summarize_json`, `_read_file`, `_discover_files`, `run` |
| `src/audit.py` | `tests/test_audit.py` | `allocate_run_id`, `format_run_id`, `run_dir`, `write_step_body` |
| `src/template_config.py` | `tests/test_template_config.py` | `agent_prompt`, `apply_finetune`, `outline_structure`, `section_titles`, `warn_unknown_agents` |
| `src/agents/writer.py` | `tests/test_writer.py` | `_build_system` |
| `src/agents/reviewer.py` | `tests/test_reviewer.py` | `_build_system`, `_build_facts`, `_count_prose_colons`, `_prose_word_count`, `_count_unlabeled_fences`, `_count_missing_h2_separators`, `_has_hook` |
| `src/agents/humanizer.py` | `tests/test_humanizer.py` | `_preserves_structure`, `_build_system` |
| `src/agents/_style.py` | `tests/test_style.py` | `BODY_STYLE_RULES`, `style_rules_block` |
| `src/agents/humanizer_patterns.py` | `tests/test_humanizer_patterns.py` | `prose_only`, `select_patterns`, `render_patterns`, `apply_mechanical_fixes`, pattern detectors |
| `src/agents/outline.py` | `tests/test_outline.py` | `_build_system`, `_build_interview_system`, `_build_template_context`, `_build_visuals_block` |
| `main.py` | `tests/test_main.py` | `_save_state_snapshot`, `_save_audit_step` |

When you add a new source file, add a new test file and register it in this table.

---

## What NOT to test

- **LLM calls** (`build_model`, `invoke_with_retry`) — require a live Ollama instance.
  If you need to test agent orchestration, mock the LLM; do not call it for real.
- **Agent `run()` functions end-to-end** — these call the LLM; keep them out of unit tests.
- **`main.py` CLI and stream loops** — require a running graph + Ollama; test pure helpers
  separately (e.g. `_save_state_snapshot` has its own tests via `tmp_path`).

---

## Code conventions

- Pure helper functions are module-level with a leading `_` prefix.
- `MDXDocument` is a `TypedDict` — always pass `metadata=`, `imports=`, `body=` as kwargs.
- `Artifact` TypedDict requires `id`, `content`, and `import_lines`.
- Artifact placement: the outline defines artifacts as ` ```artifact-slot ` fences (id +
  context, read by the visualizer); the writer places each one in the body as a short
  `@@artifact:<id>@@` token, which the publisher swaps for the rendered artifact. The
  fence form is still injected as a tolerant backstop (`ARTIFACT_SLOT_ID_RE`,
  `ARTIFACT_TOKEN_RE` in `mdx_document.py`).
- `render_mdx` always appends a trailing newline.
- `parse_mdx` returns body without import lines (those live in `imports`).
- Agents never perform file I/O directly — that is `publisher.py`'s responsibility.
  The orchestrator (`main.py`) owns the other disk writes: state snapshots and the audit
  trail. `src/audit.py` holds the audit helpers.

---

## Audit trail

Every run is given an incrementing numeric id (zero-padded, e.g. `0042`), allocated from
the git-ignored counter file `.run_id` at the repo root. The id prefixes the final
publication filename and names a per-run audit directory, so any published `.mdx` traces
straight back to what each intermediary agent delivered.

```
output/
  0042-2026-06-28-salesforce-is-it-a-buy.mdx   ← final file, id-prefixed
  audit/
    0042/                                       ← run dir, named by id
      pipeline_state.json                       ← full state snapshot (per-round history)
      outline.md                                ← outline_designer → state["outline"]
      writer.md                                 ← writer → draft["body"] (no frontmatter)
      reviewer.md                               ← reviewer → review_feedback verdict
      humanizer.md                              ← humanizer → humanized["body"]
```

- The id lives in `state["run_id"]`; the publisher reads it to prefix the filename.
- The four step files hold the **body only** (no frontmatter / imports), so they diff cleanly.
- `writer.md` and `reviewer.md` reflect the **last** review round (writer ⇄ reviewer loops).
  The full per-round history is in `pipeline_state.json` (`review_iteration`, `review_feedback`).
- Audit writes never raise — a disk problem in the trail must never abort a publication.

**To trace a defect in a published file:** open `output/audit/<id>/` for the id in its
filename, then read `outline.md → writer.md → reviewer.md → humanizer.md` in order to
localize which step introduced the problem. See `docs/AUDIT_TRAIL.md` for the full recipe.

---

## Per-agent fine-tuning (templates)

Templates may carry an optional `agents:` block that fine-tunes individual agents without
editing their built-in prompts. Supported agents: `outline`, `writer`, `reviewer`,
`humanizer`. Every key is optional — omit a key (or the whole block) and **nothing** is
added to that agent's prompt, and the fine-tuning is never mentioned to the model.

```yaml
agents:
  outline:
    prompt: |            # free-form text appended to the agent's system prompt
      Favor short, skimmable sections.
    structure:           # outline-only: the section plan (was top-level `outline_structure`)
      - id: intro
        title: "Why it matters"
        description: "Set up the problem before any code."
  writer:    { prompt: "Open each section with a one-sentence takeaway." }
  reviewer:  { prompt: "Reject any code block that is not explained first." }
  humanizer: { prompt: "Prefer active voice and short sentences." }
```

Helpers live in `src/template_config.py`; each agent calls `apply_finetune(system, …)` to
append its prompt. Two rules for that wiring:

- **Concatenate, never `str.format`.** The reviewer's base prompt has literal `{{ }}` and a
  user prompt may contain braces. `apply_finetune` concatenates for this reason.
- **The humanizer interpolates its skill first**, so fine-tuning is appended *after* that
  `.format()` call (see `humanizer._build_system`).

Backward compatibility: the legacy top-level `outline_structure` key is still read by
`template_config.outline_structure` as a fallback when `agents.outline.structure` is absent.

---

## Prompt architecture (keep prompts small and single-purpose)

The pipeline targets a local model, so every system prompt is kept to one job with only the
context that job needs. Four conventions enforce this — preserve them when editing agents:

- **One style canon, imported everywhere.** `src/agents/_style.py` holds `BODY_STYLE_RULES`
  (no em dashes, no prose colons, no hollow contrasts, no invented facts). The writer,
  reviewer, and humanizer all embed it via `style_rules_block()` instead of restating the
  rules. Never re-inline these rules in an agent — a second copy drifts and makes the
  writer/reviewer loop diverge. Add or change a rule in `_style.py` only.
- **Outline interview vs. outline are separate prompts.** `outline.run_interview` uses the
  lean `_SYSTEM_INTERVIEW` (built by `_build_interview_system`) — no visual menu, no
  artifact rules, no input-file schema, because asking follow-up questions needs none of it.
  Only the outline node (`_build_system`) carries the heavy visual/template/schema context.
  Don't merge them back into one prompt.
- **Reviewer = deterministic linter + editor.** `reviewer._build_facts(body)` pre-computes
  every mechanical check (colons, em dashes, first-level headings, unlabeled fences, section
  count, hook presence, word count/reading time) into a `[PIPELINE FACTS]` block the model is
  told to trust. The LLM judges only the editorial criteria E1–E5. When a check can be done in
  code, add it to `_build_facts` — do not add a numbered criterion the model must self-verify.
- **Humanizer triages patterns per draft.** Instead of injecting the whole
  `skills/humanizer/SKILL.md`, `humanizer._build_system` calls
  `humanizer_patterns.select_patterns(body)`, which runs cheap detectors and injects guidance
  only for the AI patterns actually present (plus an always-on voice core, capped at
  `_MAX_DETECTED`). Purely mechanical patterns (curly quotes) are fixed in
  `apply_mechanical_fixes` before the LLM runs. The full `SKILL.md` stays on disk as the human
  reference; add a new pattern by appending a `Pattern` (with a detector) to `CATALOGUE`, not
  by enlarging the prompt.

---

## Visual templates (deterministic, declarative visuals)

Complex/specific visuals — charts especially — are produced from **visual templates**, not
hand-authored by an LLM. A template is a declarative recipe; code fills its `render` string
with extracted data and author params, so the fence JSON is never transcribed by a model.
Every visual is emitted as a fenced code block — ```echart / ```daisyui (strict JSON) or
```mermaid — and carries **no imports**, matching the albertoduran publication fence
contract (`context/DAISYUI_FENCES.md` for UI, ECharts fence JSON for charts). This removed the bug-prone
authoring prompts (x/y length, flat-y, parenthesis counting, token-placement) — those
failure classes are now structurally impossible.

**Where things live**
- `templates/visuals/<id>.yaml` — the templates. Fields: `id` (name), `kind`
  (`echart`/`ui`/`mermaid` — routes the specialized renderer), `type` (chart/component
  label), `summary`, `params`, `extract` (data slots), `labels`, `imports` (kept in the
  schema but `[]` — fences need none), `render` (a fenced ```echart/```daisyui block).
- `src/visuals/registry.py` — loads/indexes templates; `menu()` is the catalogue the
  outline sees (id/kind/type/summary/params — never the render internals).
- `src/visuals/render.py` — `render_visual()` deterministic token fill.
- `src/agents/visualizer/_extractor.py` — resolves a template's data bindings.
- `src/agents/visualizer/{_echart,_ui}.py` — `render_template()` per-kind entry points.

**Render tokens** (placed BARE — substitution emits the full literal, so a template author
never wraps a token in quotes/brackets): `@@data:<slot>@@` (extracted, JSON), `@@param:<name>@@`
(author value, JSON), `@@label:<name>@@` (axis labels), `@@text:<name>@@` (JSX-escaped prose),
`@@str:<name>@@` (a value interpolated INSIDE a fence's JSON string — JSON-escaped, no
surrounding quotes; e.g. a callout's `"content"`).

**Authoring a visual** — reference a template on the artifact-slot fence, or preconfigure it
in the publication template's `visuals:` block (see `templates/finance-analysis.yaml`):

```yaml
visuals:
  - id: price-3m
    template: price-line
    section: market-snapshot        # structure id where the outline places the fence
    params: { title: "...", name: "Close", preset: currency }
    bind: { series: "valuation_data.json:historical_data.price_history?last=63" }
```

The outline places each fence (`id="..." template="..."`); the visualizer reconciles any it
missed (injecting the fence into its section before the writer runs), resolves `bind`, and
renders. The outline and orchestrator know templates *exist and how to configure them*, never
how they are built.

**The extractor** (`_extractor.resolve`) turns each `bind` into values. A binding is either a
static spec in the `_databind` grammar (resolved with no LLM) or a human intent (an LLM step
proposes a path *against the live JSON schema*, validated, then read deterministically — the
LLM locates, never authors a value).

Binding grammar (reused from `_databind`):

| Form | Meaning |
|---|---|
| `file:path` | one value/array at a JSON path |
| `file:path?last=N` | tail-slice an array to its last N items (newest, since series run oldest→newest) |
| `file:[p1, p2, …]` | assemble one array from several paths (handles heterogeneous keys) |
| `file:list[key=value].field` | project `field` from each object in `list` whose `key` equals `value`, in list order — adapts to a variable-length set (e.g. only the valuation models that actually ran). Parallel projections stay aligned; zero matches degrade loudly. |

- `src/json_query.py` does the lookup — **rooted at the input dir** (sandboxed, no
  traversal), reading the raw file so it bypasses the loader's array trimming.
- Resolution failures **degrade, never fabricate**: a failed/missing binding is recorded in
  `state["errors"]` and the artifact is skipped (its placeholder is stripped by the
  publisher) rather than shipping invented or partial values.

**Charts are template-only.** An echart slot without a template degrades loudly instead of
being hand-authored. Mermaid and one-off UI components still have a freeform LLM path for
visuals without a template: `_mermaid.render` emits a ```mermaid fence, and `_ui.render`
emits a ```daisyui fence from the compact `context/DAISYUI_FENCES.md` schema (no imports,
no JSX). The orchestrator validates each fence's JSON in `_validate_artifact`.

**Mermaid authoring.** `_mermaid.render` loads the distilled `docs/MERMAID_AUTHORING.md`,
**not** `skills/design-doc-mermaid/SKILL.md` — that file is a hierarchical orchestrator
(table-of-contents + scripts), almost no syntax, and overloads small models; the full
per-type guides total ~4,500 lines and time out Ollama. After generation, `_mermaid.sanitize`
deterministically fixes the two recurring model errors (unquoted special-char labels like
`A[Price ($1)]`, and `;`-chained statements crammed on one line) — a safety net applied
inside `_mermaid.render` to every generated diagram before it is returned.

**Label & unit helpers (deterministic).** `render.py` label modes: `sequential` (D-(n-1)…D-0),
`window` (label only the endpoints — for series with no real axis, e.g. dates), `param`,
`static`, and `data` (labels read straight from a resolved data slot — e.g. category names
extracted from the input, so a chart's axis adapts to a variable-length set). The extractor
applies an optional per-slot `transform` (`{scale, round}`) after resolution — e.g.
dollars→billions — declared in a template's `extract.<slot>.transform` or, per use, in a
publication template's visual `transform:` map.

**Derived params (deterministic).** A template may declare a `derive:` block that computes a
param from a resolved data slot via a value map — e.g. `verdict-callout` picks its Callout
`variant` from the Buy/Hold/Sell `recommendation` (Buy→information, Hold→note, Sell→caution).
An explicit param on the fence or in the publication template always wins over a derived one.
