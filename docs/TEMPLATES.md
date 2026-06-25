# Template Authoring Guide

theJournal has two kinds of templates: **publication templates** and **visual templates**.
They work at different layers of the pipeline and are authored independently.

---

## Publication templates

A publication template configures the entire pipeline for a specific content type. It lives
in `templates/<id>.yaml` and is selected when you run the pipeline (e.g.
`templates/finance-analysis.yaml`).

### What a publication template controls

| Section | What it does |
|---|---|
| `name` / `description` | Human-readable label; shown at selection time |
| `goal` | Injected into the outline designer's system prompt — defines the publication's purpose and constraints |
| `agents` | Per-agent fine-tuning: extra prompt instructions and (for `outline`) the section structure |
| `visuals` | Preconfigured visual artifacts the outline places automatically |
| `config` | Config fields prompted from the user before the pipeline starts |
| `frontmatter` | Steering text for the metadata node (title / description / tags) |

### Minimal skeleton

```yaml
name: "My Publication Type"
description: >
  One paragraph describing when to use this template.

goal: |
  Plain-text instructions for the outline designer that define the editorial
  goal and any hard constraints (e.g. which input files to use, what the
  verdict format looks like, what to never invent).

agents:
  outline:
    prompt: |
      Optional extra instructions appended to the outline agent's system prompt.
    structure:
      - id: intro
        title: "Introduction"
        description: >
          What goes in this section.
      - id: body
        title: "Main Content"
        description: >
          What goes in this section.

  writer:
    prompt: |
      Optional extra instructions for the writer agent.

  reviewer:
    prompt: |
      Optional extra blocking criteria appended to the reviewer's system prompt.

  humanizer:
    prompt: |
      What the humanizer must preserve exactly while removing AI patterns.
```

Every key under `agents` is optional. Omit a key and nothing is added to that agent —
no mention of fine-tuning reaches the model.

### Section structure (`agents.outline.structure`)

The structure is a list of section objects. Each object defines one `###`-level section
in the outline. Required keys: `id` (kebab-case, referenced by preconfigured visuals)
and `title`. `description` is optional but highly recommended — it is injected into the
outline agent's context.

```yaml
structure:
  - id: company-overview
    title: "What Does This Company Actually Do?"
    description: >
      Plain-English overview from the profile block.
  - id: verdict
    title: "Should a New Investor Buy This Stock?"
    description: >
      The verdict taken directly from analysis.json.
```

The outline designer follows this order but may add sections the template did not name.
Any extra sections appear after the template-defined ones in the final publication.

### Preconfigured visuals (`visuals`)

Each entry links a visual template to a section and provides its data bindings. The
outline designer places the artifact-slot fence automatically in the named section; the
visualizer resolves `bind` deterministically (no LLM in the data path).

```yaml
visuals:
  - id: price-3m              # unique artifact id — used as the placeholder token
    template: price-line      # visual template id from templates/visuals/
    section: market-snapshot  # id of the structure section that receives the fence
    params:
      title: "Closing price, last 3 months"
      name: "Close"
      preset: currency
    bind:
      series: "valuation_data.json:historical_data.price_history?last=63"
    transform:                # optional — applied to a slot after resolution
      series: { scale: 1.0e-9, round: 1 }
```

`bind` maps each `extract` slot declared by the visual template to a data spec
(see [Binding grammar](#binding-grammar) below). `params` maps each `params` key the
visual template accepts. `transform` is optional and applies a numeric scale/round to a
slot after resolution.

### Config fields (`config`)

Fields listed here are resolved before the pipeline runs. A field with a `default` is
applied silently; a field without one prompts the user interactively.

```yaml
config:
  - field: tone
    label: "Tone"
    hint: "conversational / educational / formal / narrative"
    default: "conversational and educational"

  - field: audience
    label: "Target audience"
    hint: "Who will read this and their experience level"
    # No default — the user is prompted for this value.
```

### Frontmatter guidance (`frontmatter`)

Three optional keys steer the metadata node. Each is injected verbatim into the LLM
prompt that designs the publication's title, description, and tags.

```yaml
frontmatter:
  title: >
    Name the company and signal an investment analysis, e.g. "Is Salesforce a Buy?".
  description: >
    One sentence naming the company and the kind of analysis. Under 160 characters.
  tags: >
    Include the ticker and sector. Lowercase kebab-case, 2 to 5 tags.
```

---

## Visual templates

A visual template is a declarative recipe for one visual component. It lives in
`templates/visuals/<id>.yaml`. Code fills its `render` string with extracted data and
author params — no LLM ever writes chart option objects or balances braces.

### Fields

| Field | Required | Description |
|---|---|---|
| `id` | yes | Kebab-case identifier; must match the filename |
| `kind` | yes | `echart`, `ui`, or `mermaid` — routes to the specialized renderer |
| `type` | yes | For `echart`: builder name (e.g. `lineChartOption`) or `raw`; for `ui`: component name (e.g. `Callout`) |
| `summary` | yes | One-line description shown in the visual menu the outline designer sees |
| `params` | no | Author-supplied values (title, labels, presets). Each key: `required`, `default`, `enum`, `type`, `desc` |
| `extract` | no | Data slots resolved from input files. Each key: `type` (e.g. `number[]`, `string`), `desc` |
| `labels` | no | Axis label declarations — tells the renderer how to build each axis label array |
| `derive` | no | Params computed deterministically from a resolved data slot (a value map) |
| `imports` | yes | MDX import statements injected at the top of the publication |
| `render` | yes | The JSX/MDX snippet with `@@token@@` placeholders |

### Render tokens

Place tokens **bare** in the `render` string — no surrounding quotes, brackets, or
braces. The renderer substitutes each token with a complete JS/JSON literal.

| Token | Source |
|---|---|
| `@@param:<name>@@` | A value from `params`, supplied by the author |
| `@@data:<slot>@@` | A resolved data slot from `extract`, as a JSON array or value |
| `@@label:<name>@@` | A label array built from the `labels` declaration |
| `@@text:<name>@@` | A resolved `extract` slot, HTML-escaped for prose |

### `labels` modes

```yaml
labels:
  x: { from: param, name: categories }      # param supplies the literal label array
  x: { from: window, of: series, start: "Oldest", end: "Latest" }  # endpoint labels only
  x: { from: sequential, of: series }       # D-(n-1)…D-0 relative labels
  y: { from: data, of: categories }         # labels read straight from a resolved data slot
```

### `derive` block

Computes a param value from a resolved data slot via a value map. An explicit `param`
on the fence or in the publication template always wins over a derived value.

```yaml
derive:
  variant:
    from: recommendation    # the extract slot to read
    map:
      Buy: information
      Hold: note
      Sell: caution
    default: information    # fallback when the value is not in the map
```

### Minimal echart example

```yaml
id: my-line-chart
kind: echart
type: lineChartOption
summary: >
  Trend of a single numeric series. Pick for "how this value moved over time".

params:
  title: { required: true, desc: "Figure title" }
  name:  { default: "Value", desc: "Series name" }
  preset: { default: "currency", enum: ["currency", "percent"], desc: "client formatter" }

extract:
  series: { type: "number[]", desc: "y values, oldest -> newest" }

labels:
  x: { from: window, of: series, start: "Oldest", end: "Latest" }

imports:
  - 'import EChart from "@components/ui/mdx/EChart.astro";'
  - 'import { lineChartOption } from "@integrations/echarts/options";'

render: |
  <EChart
    title={@@param:title@@}
    option={lineChartOption({ x: @@label:x@@, y: @@data:series@@, name: @@param:name@@ })}
    optionClientPreset={@@param:preset@@}
    width={760}
    height={360}
  />
```

### Minimal UI component example

```yaml
id: my-callout
kind: ui
type: Callout
summary: >
  Highlighted callout box. Pick to surface a verdict or alert.

params:
  variant: { default: "information", enum: ["note", "information", "warning", "caution", "error"] }
  title:   { default: "Note", desc: "Callout heading" }

extract:
  message: { type: "string", desc: "the text to display" }

imports:
  - 'import Callout from "@components/ui/display/Callout.astro";'

render: |
  <Callout variant={@@param:variant@@} title={@@param:title@@}>
    @@text:message@@
  </Callout>
```

### Raw ECharts option (multi-series)

When a builder cannot express the shape (e.g. multiple series), use `type: raw` and
write the full ECharts option object directly in `render`:

```yaml
id: my-grouped-bar
kind: echart
type: raw
summary: >
  Grouped bars comparing two series across the same categories.

params:
  title:  { required: true, desc: "Figure title" }
  name_a: { default: "Series A", desc: "first series name" }
  name_b: { default: "Series B", desc: "second series name" }
  preset: { default: "currency", enum: ["currency", "percent"] }

extract:
  series_a:   { type: "number[]", desc: "first series values" }
  series_b:   { type: "number[]", desc: "second series values" }
  categories: { type: "string[]", desc: "one label per group" }

labels:
  y: { from: data, of: categories }

imports:
  - 'import EChart from "@components/ui/mdx/EChart.astro";'

render: |
  <EChart
    title={@@param:title@@}
    optionClientPreset={@@param:preset@@}
    width={760}
    height={400}
    option={{
      tooltip: { trigger: "axis" },
      legend: { data: [@@param:name_a@@, @@param:name_b@@], top: 0 },
      grid: { left: 8, right: 24, top: 40, bottom: 8, containLabel: true },
      xAxis: { type: "value" },
      yAxis: { type: "category", data: @@label:y@@ },
      series: [
        { name: @@param:name_a@@, type: "bar", data: @@data:series_a@@ },
        { name: @@param:name_b@@, type: "bar", data: @@data:series_b@@ }
      ]
    }}
  />
```

---

## Binding grammar

Bindings appear in a publication template's `visuals[*].bind` or on an artifact-slot
fence in the outline. Each binding maps an `extract` slot to a path in an input file.
Files are resolved relative to `input/`.

| Form | Meaning |
|---|---|
| `file:path` | Single value or array at a JSON path |
| `file:path?last=N` | Tail-slice an array to its last N items (newest, since series run oldest→newest) |
| `file:[p1, p2, …]` | Assemble one array from several paths |
| `file:list[key=value].field` | Project `field` from each object in `list` whose `key` equals `value`, in list order. Adapts to variable-length sets (e.g. only the models that ran). |

**Examples:**

```yaml
bind:
  series: "valuation_data.json:historical_data.price_history?last=63"
  values: "valuation_data.json:stock_metrics.financials.history.revenue_annual"
  series_a: "valuation_data.json:summary.rows[scenario=Bear].intrinsic_value"
  categories: "valuation_data.json:summary.rows[scenario=Base].model_name"
  mixed: "valuation_data.json:[stock_metrics.market_data.current_price, summary.composite_intrinsic]"
```

Resolution failures degrade loudly instead of fabricating data: a failed binding is
recorded in `state["errors"]` and the artifact is skipped by the publisher.

---

## Where the templates are loaded

| Template type | Directory | Loader |
|---|---|---|
| Publication templates | `templates/*.yaml` | `src/agents/loader.py` → `state["template"]` |
| Visual templates | `templates/visuals/*.yaml` | `src/visuals/registry.py` → indexed by `id` |

The visual registry's `menu()` exposes `id`, `kind`, `type`, `summary`, and `params` to
the outline designer — never `render` or the internal data wiring.

---

## Checklist for a new publication template

- [ ] Create `templates/<id>.yaml` with `name`, `description`, `goal`
- [ ] Add `agents.outline.structure` with at least one section
- [ ] Add per-agent `prompt` keys for any editorial constraints
- [ ] Add `visuals` entries for each preconfigured chart, referencing visual template ids
      that exist in `templates/visuals/`
- [ ] Verify every `bind` path exists in the actual input files for your content type
- [ ] Add `config` fields for any user-supplied values the pipeline needs
- [ ] Optionally add `frontmatter` guidance for title/description/tags

## Checklist for a new visual template

- [ ] Create `templates/visuals/<id>.yaml`; `id` must match the filename
- [ ] Set `kind` (`echart`, `ui`, or `mermaid`) and `type`
- [ ] Write a one-line `summary` (this is what the outline designer reads)
- [ ] Declare all `params` with `default` or `required: true`
- [ ] Declare all `extract` slots with `type` and `desc`
- [ ] Add `labels` entries for any axis that needs a label array
- [ ] Add `imports` (must be valid MDX import statements)
- [ ] Write `render` using only `@@param:*@@`, `@@data:*@@`, `@@label:*@@`, `@@text:*@@` tokens
- [ ] Add `derive` if any param should be computed from extracted data
- [ ] Reference the new template id in a publication template's `visuals` list or test it
      with an artifact-slot fence in the outline
