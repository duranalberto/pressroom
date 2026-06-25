# DaisyUI Publication Fences

Static publication UI components are authored as a fenced ```daisyui code block
holding one strict JSON object. The fence needs **no imports** and renders to
static HTML at build time. Use it for callouts, chat messages, lists, steps,
section headers, and browser/phone/window mockups.

Strict JSON only: double quotes, no comments, no trailing commas, no functions,
no `undefined`, only finite numbers. Emit ONE fence containing ONE object.

## Base fields (every component accepts these)

| Field | Type | Purpose |
| --- | --- | --- |
| `component` | string | Required. Selects the renderer (see the list below). |
| `id` | string | Optional root element id. |
| `class` | string | Optional extra classes on the root element. |
| `ariaLabel` / `aria-label` | string | Optional accessible label. |
| `ariaLabelledBy` / `aria-labelledby` | string | Optional labelling ref. |

Required strings must be non-empty after trimming.

## Content blocks

`content`, `header`, `footer`, `caption`, and `toolbar` take a plain string or
an array of blocks. A plain string becomes a paragraph. Block shapes:

| `type` | Fields | Renders |
| --- | --- | --- |
| `text` | `text` | escaped inline text |
| `paragraph` | `text` | `<p>` |
| `pre` | `text` | `<pre><code>` |
| `list` | `items: string[]`, optional `style: "ordered" \| "unordered"` | `<ul>`/`<ol>` |
| `image` | `src`, `alt`, optional `class`, `width`, `height` | static `<img>` |
| `link` | `href`, `label`, optional `external`, `class` | static `<a>` |

Block text is escaped — there is no inline Markdown or HTML. To include a link,
use a separate `link` block, not inline `[text](url)`.

## Components

### `callout`
Supporting context, risk, caution, or a failure note.
- `content` (required), `variant` (`note` | `information` | `warning` | `caution` | `error`, default `note`), `title` (optional).

```daisyui
{
  "component": "callout",
  "variant": "warning",
  "title": "Before you rely on this",
  "content": [
    { "type": "paragraph", "text": "The figures below come from a single filing." },
    { "type": "link", "href": "https://example.com/source", "label": "Read the source filing", "external": true }
  ]
}
```

### `chat-bubble`
One static message where sender, side, or status matters.
- `content` (required), `align` (`start` | `end`), `color` (`neutral` | `primary` | `secondary` | `accent` | `info` | `success` | `warning` | `error`), optional `header`, `footer` (block arrays).

### `list`
An information-rich collection of peer rows.
- `items` (required array). Each item: `title` (required), optional `subtitle`, `description`, `href`, `media`, `status`, `action`.
- `media`: `{ "kind": "marker", "label": "01" }` or `{ "kind": "image", "src": "/x.png", "alt": "…" }`.
- `status`: `{ "label": "Verified", "color": "success" }` (same colors as chat-bubble).
- `action`: `{ "label": "Notes", "href": "/x/", "external": false }`.

```daisyui
{
  "component": "list",
  "items": [
    { "title": "DCF", "subtitle": "Base case", "media": { "kind": "marker", "label": "01" }, "status": { "label": "$412", "color": "success" } },
    { "title": "NAV", "subtitle": "Bear case", "media": { "kind": "marker", "label": "02" }, "status": { "label": "-$30", "color": "error" } }
  ]
}
```

### `steps`
A linear, branch-free sequence or current progress.
- `items` (required): each `{ "label": "…", optional "marker": "…", "color": "…" }`.
- Optional `currentStep` (1-based), `activeColor`, `orientation` (`responsive` | `horizontal` | `vertical`).

```daisyui
{
  "component": "steps",
  "currentStep": 2,
  "activeColor": "primary",
  "items": [
    { "label": "Filing read" },
    { "label": "Model run", "marker": "2" },
    { "label": "Reviewed" }
  ]
}
```

### `section-header`
A styled section heading with an optional action link.
- `title` (required), `level` (`2` | `3`, default `2`), optional `link: { "href", "label", "external" }`.

### `mockup-browser`
Content in a browser frame when the route/address matters.
- `content` (required), `url` (required unless `toolbar` is present), optional `toolbar`, `caption`.

### `mockup-phone`
A mobile screen or narrow-state preview.
- `content` (required), optional `caption`.

### `mockup-window`
A desktop app surface, generated report, or bounded output.
- `content` (required), optional `header`, `caption`.

Use `pre` content blocks for command output or logs inside a mockup-window.
