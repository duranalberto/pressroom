# Callout Component

`Callout.astro` renders a static, card-like publication note with a semantic variant, decorative icon, visible title, and arbitrary Astro or MDX content. It requires no client-side JavaScript.

**Import path:** `@components/ui/display/Callout.astro`

## Component signature

```ts
// Props interface (extends Omit<HTMLAttributes<"aside">, "style">)
interface Props {
  variant?: CalloutVariant;         // defaults to "note"
  title?: string;                   // overrides variant default; must be non-empty if set
  icon?: Icon;                      // overrides variant default icon
  palette?: Partial<CalloutPalette>; // per-instance color overrides
  class?: string;                   // outer <aside> classes
  headerClass?: string;             // icon-and-title header region
  iconClass?: string;               // icon surface
  titleClass?: string;              // visible title
  contentClass?: string;            // default-slot content region
  // All other HTMLAttributes<"aside"> except raw "style" are forwarded.
}

type CalloutVariant = "note" | "information" | "warning" | "caution" | "error";

interface CalloutPalette {
  accent: string;       // --callout-accent
  surface: string;      // --callout-surface
  border: string;       // --callout-border
  title: string;        // --callout-title
  content: string;      // --callout-content
  icon: string;         // --callout-icon
  iconSurface: string;  // --callout-icon-surface
}
```

## Astro usage

```astro
---
import Callout from "@components/ui/display/Callout.astro";
---

<Callout variant="information">
  The static build preserves this information when JavaScript is disabled.
</Callout>
```

Each variant supplies a default title, icon, and theme-aware color treatment.

| Variant       | Default title | Default accent token |
| ------------- | ------------- | -------------------- |
| `note`        | Notes         | `primary`            |
| `information` | Information   | `info`               |
| `warning`     | Warning       | `warning`            |
| `caution`     | Caution       | `secondary`          |
| `error`       | Error         | `error`              |

`note` is the default when `variant` is omitted.

## Custom titles and icons

A custom title changes the visible heading without changing the variant's semantic styling or default icon.

```astro
<Callout variant="warning" title="Deployment risk">
  This operation replaces the current production assets.
</Callout>
```

Pass an `Icon` object to replace the default icon. Icons remain decorative because the visible title already identifies the callout.

```astro
---
import type { Icon } from "@appTypes/icon";

const databaseIcon: Icon = {
  text: "",
  viewBox: "0 0 24 24",
  content: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/>',
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
};
---

<Callout variant="caution" title="Database migration" icon={databaseIcon}>
  Take a verified backup before applying the migration.
</Callout>
```

## MDX publication usage

Import `Callout` after the publication frontmatter. The default slot accepts text, links, lists, code, Astro components, and other MDX-compatible content.

```mdx
import Callout from "@components/ui/display/Callout.astro";

<Callout variant="note" title="Reader context">
  <p>
    The examples use fixture data. See the
    <a href="/thejournal/methodology/">methodology</a> before comparing results.
  </p>
  <ul>
    <li>Values are rounded.</li>
    <li>Timestamps use UTC.</li>
  </ul>
</Callout>
```

The component applies `not-prose` and provides its own readable spacing for paragraphs, lists, links, inline code, blockquotes, and preformatted content. Nested components retain their own presentation contracts.

## Props

| Prop                      | Type                        | Default                | Purpose                                                                                                      |
| ------------------------- | --------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------ |
| `variant`                 | `CalloutVariant`            | `"note"`               | Semantic meaning: `note`, `information`, `warning`, `caution`, or `error`.                                   |
| `title`                   | `string`                    | variant default        | Optional nonblank title replacing the variant default.                                                       |
| `icon`                    | `Icon`                      | variant default        | Optional `Icon` object replacing the variant icon.                                                           |
| `palette`                 | `Partial<CalloutPalette>`   | variant default colors | Optional per-instance CSS variable overrides.                                                                |
| `class`                   | `string`                    | —                      | Adds classes to the outer card-like `<aside>`.                                                               |
| `headerClass`             | `string`                    | —                      | Adds classes to the icon-and-title header.                                                                   |
| `iconClass`               | `string`                    | —                      | Adds classes to the icon surface.                                                                            |
| `titleClass`              | `string`                    | —                      | Adds classes to the visible title.                                                                           |
| `contentClass`            | `string`                    | —                      | Adds classes to the default-slot content region.                                                             |
| Standard aside attributes | `HTMLAttributes<"aside">`   | —                      | Forwards attributes such as `id`, `aria-label`, `aria-labelledby`, and `data-*`; raw `style` is not exposed. |

## Slots

| Slot    | Purpose                                        |
| ------- | ---------------------------------------------- |
| Default | Required. The callout body content to display. |

## Build-time errors

The following conditions throw during `astro build` or `astro dev`:

- `variant` is not one of the five supported values.
- `title` is provided but blank (empty or whitespace-only).
- A `palette` key is blank, whitespace-only, or not a valid `CalloutPalette` property name.

## Palette customization

`palette` accepts any subset of the exported `CalloutPalette` fields. Each field maps directly to a CSS custom property on the `<aside>`:

| Palette field | CSS variable             | Controls                     |
| ------------- | ------------------------ | ---------------------------- |
| `accent`      | `--callout-accent`       | Left accent bar color        |
| `surface`     | `--callout-surface`      | Card background               |
| `border`      | `--callout-border`       | Card border                  |
| `title`       | `--callout-title`        | Title text color             |
| `content`     | `--callout-content`      | Body text color              |
| `icon`        | `--callout-icon`         | Icon fill/stroke color       |
| `iconSurface` | `--callout-icon-surface` | Icon background circle color |

Use theme variables and `color-mix()` so overrides continue to adapt to light and dark themes.

```mdx
<Callout
  variant="caution"
  title="Editorial checkpoint"
  palette={{
    accent: "var(--color-accent)",
    surface:
      "color-mix(in oklab, var(--color-accent) 12%, var(--color-base-100))",
    border:
      "color-mix(in oklab, var(--color-accent) 45%, var(--color-base-300))",
    title: "var(--color-base-content)",
    content: "var(--color-base-content)",
    icon: "var(--color-accent)",
    iconSurface:
      "color-mix(in oklab, var(--color-accent) 20%, var(--color-base-100))",
  }}
>
  Confirm the publication date and image rights before release.
</Callout>
```

Palette values are trusted author-provided CSS values. Consumers are responsible for contrast when overriding defaults. Prefer existing DaisyUI semantic tokens over hardcoded colors.

## Styling and responsive behavior

- The card fills its available width and keeps long text from widening the publication.
- A semantic accent edge, border, surface, and icon treatment distinguish the variants without relying on color alone.
- Code blocks and other wide preformatted content scroll within the callout.
- Padding becomes more compact at narrow widths.
- Use the palette for colors and region class hooks for layout or typography.

## Accessibility and content guidance

The visible title communicates the callout type, so the icon is hidden from assistive technology. Custom titles should remain specific enough to preserve the meaning of their variant. Color is supplemental rather than the only severity signal.

Callouts are static supporting content. They do not use `role="alert"`, announce updates, dismiss themselves, or manage focus. Use application feedback components for live errors, form validation, toast notifications, and changing status messages.

Use ordinary prose for information that belongs in the main reading flow and a blockquote for quoted material. Reserve callouts for context or consequences readers could reasonably miss while scanning.
