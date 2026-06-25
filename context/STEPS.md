# Steps Component

`Steps.astro` renders a typed progress sequence using DaisyUI's steps component. It produces a semantic ordered list, requires no client-side JavaScript, and can be imported by Astro pages, layouts, components, and MDX publications.

**Import path:** `@components/ui/display/Steps.astro`

## Component signature

```ts
// Props interface (extends HTMLAttributes<"ol">)
interface Props {
  items: StepItem[];                              // required; must be non-empty
  currentStep?: number;                           // 1-based; integer within [1, items.length]
  activeColor?: StepColor;                        // defaults to "primary"
  orientation?: "responsive" | "horizontal" | "vertical"; // defaults to "responsive"
  itemClass?: string;                             // classes added to every step <li>
  class?: string;                                 // classes added to the outer <ol>
  // All HTMLAttributes<"ol"> are forwarded; tabindex has special auto-assignment (see below).
}

interface StepItem {
  label: string;       // required visible text
  marker?: string;     // DaisyUI data-content; omit for auto-numbering
  color?: StepColor;   // per-item color override; takes precedence over activeColor
  class?: string;      // classes added to this step's <li>
}

type StepColor =
  | "neutral" | "primary" | "secondary" | "accent"
  | "info" | "success" | "warning" | "error";
```

## Astro usage

```astro
---
import Steps, {
  type StepItem,
} from "@components/ui/display/Steps.astro";

const releaseSteps: StepItem[] = [
  { label: "Draft" },
  { label: "Review" },
  { label: "Publish" },
];
---

<Steps
  items={releaseSteps}
  currentStep={2}
  aria-label="Publication progress"
/>
```

`currentStep` is 1-based. The example colors Draft and Review with the default primary color and marks Review with `aria-current="step"`.

## MDX publication usage

Import the component after the publication frontmatter. Step arrays can be passed inline, which keeps MDX examples self-contained.

```mdx
import Steps from "@components/ui/display/Steps.astro";

<Steps
  aria-label="Deployment progress"
  currentStep={2}
  activeColor="success"
  items={[
    { label: "Build", marker: "✓" },
    { label: "Deploy", marker: "2" },
    { label: "Verify", marker: "3" },
  ]}
/>
```

The component applies `not-prose`, so publication typography does not alter the progress indicator.

## Props

| Prop                     | Type                                         | Default        | Purpose                                                                                                         |
| ------------------------ | -------------------------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------- |
| `items`                  | `StepItem[]`                                 | —              | Required array of step definitions. Empty arrays throw a build-time error.                                      |
| `currentStep`            | `number`                                     | —              | Optional 1-based current position. Must be an integer within `[1, items.length]`.                               |
| `activeColor`            | `StepColor`                                  | `"primary"`    | Semantic color applied from step 1 through the current step.                                                     |
| `orientation`            | `"responsive" \| "horizontal" \| "vertical"` | `"responsive"` | Layout direction. Responsive is vertical below `sm`, horizontal at `sm` and above.                              |
| `itemClass`              | `string`                                     | —              | Classes added to every generated step `<li>`.                                                                   |
| `class`                  | `string`                                     | —              | Classes added to the outer `<ol>`.                                                                              |
| Standard list attributes | `HTMLAttributes<"ol">`                       | —              | Attributes such as `id`, `aria-label`, `aria-labelledby`, and `data-*` are forwarded to the `<ol>`.            |

## tabindex auto-assignment

When `orientation` is `"responsive"` or `"horizontal"`, the component automatically sets `tabindex="0"` on the outer `<ol>` so keyboard users can focus the element and scroll an overflowing horizontal sequence. When `orientation` is `"vertical"`, `tabindex` is omitted by default because vertical overflow does not require scroll focus.

Pass an explicit `tabindex` prop to override this behavior in either direction:

```astro
<!-- Opt out of focus management on a horizontal list -->
<Steps orientation="horizontal" tabindex={-1} items={steps} />

<!-- Force focus on a vertical list -->
<Steps orientation="vertical" tabindex={0} items={steps} />
```

## Step items

Each item follows the exported `StepItem` interface.

- `label` is the visible step text. Required and must be non-empty.
- `marker` becomes DaisyUI's `data-content` value. Omit it to use automatic numbering (`1`, `2`, …). Pass a single character such as `"✓"` or `"!"` for custom markers.
- `color` overrides the computed active color for that specific item.
- `class` adds classes to one item; use `itemClass` for every item.

## Progress and color precedence

When `currentStep` is present:

1. Each item from position 1 through `currentStep` receives `activeColor`.
2. An explicit `color` declared on an individual item takes precedence over `activeColor`.
3. Items after `currentStep` remain in DaisyUI's pending (unstyled) state unless they carry their own `color`.

Omitting `currentStep` leaves every item pending except items with explicit `color` values.

```astro
<Steps
  currentStep={2}
  activeColor="primary"
  items={[
    { label: "Queued" },
    { label: "Running", color: "warning" },
    { label: "Complete" },
  ]}
/>
```

Result: Queued → `primary`, Running → `warning` (explicit overrides `activeColor`), Complete → pending.

## Step colors

| Color       | DaisyUI step class  |
| ----------- | ------------------- |
| `neutral`   | `step-neutral`      |
| `primary`   | `step-primary`      |
| `secondary` | `step-secondary`    |
| `accent`    | `step-accent`       |
| `info`      | `step-info`         |
| `success`   | `step-success`      |
| `warning`   | `step-warning`      |
| `error`     | `step-error`        |

## Orientation and overflow

| Orientation   | Below `sm` | At `sm` and above  | tabindex default |
| ------------- | ---------- | ------------------ | ---------------- |
| `responsive`  | vertical   | horizontal         | `0`              |
| `horizontal`  | horizontal | horizontal         | `0`              |
| `vertical`    | vertical   | vertical           | *(none)*         |

Horizontal layouts with more labels than available width trigger DaisyUI's internal horizontal scroll. The `tabindex="0"` default ensures keyboard-only users can reach and scroll the list.

## Build-time errors

- `items` array is empty.
- `currentStep` is not an integer.
- `currentStep` is less than 1 or greater than `items.length`.

## Accessibility

Use `aria-label` or `aria-labelledby` to explain what the sequence represents. The current item receives `aria-current="step"`; color is supplemental and is not the only current-state signal.

Keep labels short and meaningful. This component renders static text labels and text markers, not interactive controls or rich icon slots. Navigation, form progression, state changes, and announcements remain consumer responsibilities.
