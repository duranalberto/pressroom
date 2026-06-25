# Visual Components Menu

Quick reference for the outline designer. Use this to decide when to add a visual
to a section and how to write the creation prompt that the visualizer will execute.

---

## How to add a visual to a section

When a section would benefit from a visual, place a placeholder **after** the
key-points list, on its own line with a blank line above and below. Two forms:

````
```artifact-slot
id="<kebab-id>" template="<template-id>"
```
````

is the **templated** form (required for charts; rendered deterministically from the input
files — see "Charts" below). For a Mermaid diagram or a one-off UI component with no
template, use the **freeform** form with a creation prompt:

````
```artifact-slot
id="<kebab-id>" context="<creation prompt>"
```
````

Rules for writing the placeholder:
- `id` — lowercase kebab-case, unique across the outline, describes the visual
  (e.g. `revenue-trend`, `pipeline-flow`, `allocation-donut`)
- `context` — a full creation prompt telling the visualizer what to build, what
  data to include, and how to configure it. Write in plain English. Do NOT use
  double-quote characters inside the context string (use single quotes or
  rephrase instead).
- Only add a visual when it genuinely helps the reader — a chart for data that
  is better as a table wastes a section, and a diagram for a two-step process
  adds noise.
- To include a **code example** in a section description, use a standard language
  fence (`python`, `sql`, `bash`, etc.). Only `artifact-slot` fences are visual
  component placeholders — they are treated differently by every downstream agent.

What a freeform `context` prompt must include (Mermaid / one-off UI only — charts use a template):
1. Component type (e.g. 'Mermaid flowchart TD', 'Callout warning', 'Steps')
2. What the visual is communicating (the editorial point)
3. Specific labels or node names to use
4. Configuration hints (title, variant, orientation)

---

## Charts — use a visual template

Charts (EChart) are produced from **visual templates**, not written by hand. Do NOT specify
builder calls, option objects, or numbers in a `context`. Instead reference a template by id:

````
```artifact-slot
id="<kebab-id>" template="<template-id>"
```
````

Pick a `template-id` from the **VISUAL TEMPLATES AVAILABLE** list in your system prompt
(each lists its kind, type, and a one-line summary). Many publications also ship
**PRECONFIGURED VISUALS** — already wired to the input data; place each given fence verbatim
in its named section.

- The data is filled deterministically from the input files, so a chart never carries
  invented numbers and never needs an x/y length or option-shape warning.
- If no existing template fits the chart you need, prefer the closest one; do not fall back
  to hand-writing chart MDX (a chart slot without a template is skipped downstream).

---

## Mermaid — structural diagrams

Use when the section explains structure: processes, sequences, architecture,
relationships, lifecycles. Do not use for measured numeric data.

| Diagram type | Best for | Key elements to describe |
|--------------|----------|--------------------------|
| `flowchart TD` | Top-down process, pipeline, approval flow with branches | Node labels, edge conditions, decision points |
| `flowchart LR` | Left-to-right process or data flow | Same |
| `sequenceDiagram` | API calls, auth flows, service interactions over time | Participants, message labels, order of calls |
| `graph TB` with subgraphs | Layered architecture, bounded contexts, ownership | Components, groupings, relationships |
| `erDiagram` | Data model, schema, cardinality | Entities, relationships, field names |
| `stateDiagram-v2` | Lifecycle, status changes, retry states | States, transitions, triggers |
| `classDiagram` | Class hierarchy, interfaces, type responsibility | Classes, methods, inheritance arrows |
| `gantt` | Project timeline, milestones, delivery windows | Tasks, dates, sections |
| `mindmap` | Taxonomy, mental models, nested categories | Root node, branches, leaves |

**Mermaid notes:**
- Do NOT add `%%{init: ...}%%` theme blocks — the site owns Mermaid theming.
- One concept per diagram. Keep node labels short (≤4 words).
- No import statement needed for Mermaid; it renders as a code fence.

---

## UI Components — presentation patterns

Use these for recognizable interface patterns that prose cannot express clearly.
The visualizer renders each as a static `daisyui` code fence — no imports, no JSX. You
just choose the component and describe its content in the `context` prompt.

### Callout
A card-like note with a semantic variant and optional title. Use for supporting
information readers could miss while scanning: prerequisites, risks, warnings.

Variants: `note` · `information` · `warning` · `caution` · `error`

Context must specify: variant, optional custom title, body text content.

Renders as: `daisyui` fence, `"component": "callout"`.

### ChatBubble
A short message exchange or single system message. Use when sender identity or
message direction is part of the explanation.

Context must specify: sender names, message text, alignment (`start` or `end`),
optional color (`success`, `primary`, etc.), optional timestamp or footer.

Renders as: `daisyui` fence, `"component": "chat-bubble"`.

### List
Rich information rows, each with title, subtitle, description, status badge,
and optional link. Use for resource collections, service inventories, artifacts.

Context must specify: each row's title, subtitle, description, and status label
with color (`success`, `warning`, `error`, `info`).

Renders as: `daisyui` fence, `"component": "list"`.

### Steps
A linear progress sequence or branch-free checklist. Use for release stages,
onboarding steps, migration progress. Use `currentStep` when showing current
position.

Context must specify: step labels (in order), optional `currentStep` (1-based),
optional `activeColor`, optional `orientation` (`horizontal` or `vertical`).

Renders as: `daisyui` fence, `"component": "steps"`.

### MockupBrowser
A web-page frame with a visible URL bar. Use when the route or browser context
is part of what the reader must understand.

Context must specify: the URL to display, the content inside (can be descriptive
prose that the visualizer will format as a placeholder content block).

Renders as: `daisyui` fence, `"component": "mockup-browser"`.

### MockupPhone
A mobile device frame. Use when a mobile layout or responsive behavior is the
point of the visual.

Context must specify: what the screen displays (app state, message, or UI description).

Renders as: `daisyui` fence, `"component": "mockup-phone"`.

### MockupWindow
A generic desktop application frame. Use for dashboards, generated reports, or
output surfaces that need a boundary but not browser chrome.

Context must specify: optional header label, body content description.

Renders as: `daisyui` fence, `"component": "mockup-window"`.

---

## Example placeholders

````
```artifact-slot
id="revenue-trend" template="price-line"
```
````

````
```artifact-slot
id="pipeline-architecture" context="Mermaid flowchart TD showing the 6-node publication pipeline: outline_designer -> visualizer -> writer -> reviewer -> humanizer -> publisher. Add a dashed back-edge from reviewer to writer labeled 'revision (max 3x)'. Use short node labels."
```
````

````
```artifact-slot
id="deployment-warning" context="Callout with variant warning and title 'Before deploying'. Body: list two items — confirm the target environment is staging, keep a verified backup of the previous artifact available for rollback."
```
````

````
```artifact-slot
id="release-stages" context="Steps component showing 4 release stages: Build, Test, Deploy, Verify. currentStep is 3 (Deploy). activeColor success. Horizontal orientation."
```
````
