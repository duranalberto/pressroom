# List Component

`List.astro` renders a typed collection of information-rich rows using DaisyUI's list component. It supports local images or text markers, titles, metadata, wrapped descriptions, semantic status badges, one row-level link, and one action button per row without client-side JavaScript.

**Import path:** `@components/ui/display/List.astro`

## Component signature

```ts
// Props interface (extends HTMLAttributes<"ul">)
interface Props {
  items: ListItem[];   // required; must be non-empty
  itemClass?: string;  // classes added to every generated list row
  class?: string;      // classes added to the outer <ul>
  // All other HTMLAttributes<"ul"> are forwarded to the outer <ul>.
}

interface ListItem {
  title: string;            // required; must be non-empty
  href?: string;            // makes the entire row a clickable link
  ariaLabel?: string;       // aria-label for the row link (when href is set)
  subtitle?: string;        // compact metadata below the title
  description?: string;     // wrapped descriptive text on a separate row
  media?: ListItemMedia;    // leading image or decorative text marker
  status?: ListStatus;      // badge displayed beside the title
  action?: ListAction;      // trailing link button
  class?: string;           // classes added to this row only
  contentClass?: string;    // classes added to the title/subtitle region
}

type ListItemMedia =
  | { kind: "image"; src: ImageMetadata; alt: string; class?: string }
  | { kind: "marker"; label: string; class?: string };

interface ListStatus {
  label: string;            // required; must be non-empty
  color?: ListStatusColor;  // omit for DaisyUI default badge surface
  class?: string;
}

interface ListAction {
  label: string;            // required; must be non-empty
  href: string;             // required; must be non-empty
  ariaLabel?: string;       // supplements short visible labels
  external?: boolean;       // adds target="_blank" rel="noopener noreferrer"
  class?: string;
}

type ListStatusColor =
  | "neutral" | "primary" | "secondary" | "accent"
  | "info" | "success" | "warning" | "error";
```

## Astro usage

```astro
---
import List, {
  type ListItem,
} from "@components/ui/display/List.astro";
import releaseImage from "@assets/releases/v2.png";

const releases: ListItem[] = [
  {
    title: "Version 2.0",
    subtitle: "Production release",
    description: "Introduces the new publication rendering pipeline.",
    media: { kind: "image", src: releaseImage, alt: "Version 2 artwork" },
    status: { label: "Ready", color: "success" },
    action: { label: "Read notes", href: "/releases/v2/" },
  },
];
---

<List items={releases} aria-label="Recent releases" />
```

Standard `<ul>` attributes are forwarded to the list. Add an `aria-label` or `aria-labelledby` whenever the surrounding heading does not clearly identify the collection.

## Row-level link vs. action

There are two separate link mechanisms per row:

- **`href` on `ListItem`** — makes the whole row a clickable link using a full-width overlay anchor. Use for rows where the primary interaction is reading or navigating to the item. Supply `ariaLabel` on the item when the title alone does not describe the destination.
- **`action` on `ListItem`** — renders a `btn btn-sm btn-ghost` trailing button. Use when the row has separate content and one secondary action (such as "View run" or "Download").

Both can coexist on the same row: the overlay row link and the trailing action button are independently clickable.

## MDX publication usage

Import the component and any local image assets after the publication frontmatter.

```mdx
import List from "@components/ui/display/List.astro";
import serviceLogo from "@assets/thejournal/example/service.png";

<List
  aria-label="Deployment services"
  class="my-8 shadow-sm"
  items={[
    {
      title: "Build service",
      subtitle: "Artifact producer",
      description: "Compiles the site and records immutable output metadata.",
      media: { kind: "image", src: serviceLogo, alt: "Build service logo" },
      status: { label: "Healthy", color: "success" },
      action: { label: "View run", href: "/thejournal/build-run/" },
    },
    {
      title: "Deployment review",
      subtitle: "Manual approval",
      href: "/thejournal/deployment-review/",
      media: { kind: "marker", label: "02" },
      status: { label: "Waiting", color: "warning" },
    },
  ]}
/>
```

The component applies `not-prose`, so publication typography does not alter the row layout. Its own text styles remain theme-aware; additional classes can be supplied for local presentation.

## Props

| Prop                     | Type                      | Default | Purpose                                                                                                           |
| ------------------------ | ------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| `items`                  | `ListItem[]`              | —       | Required array of typed rows. Empty arrays and blank required labels throw a build-time error.                    |
| `itemClass`              | `string`                  | —       | Classes added to every generated `.list-row`.                                                                     |
| `class`                  | `string`                  | —       | Classes added to the outer `<ul>` alongside the default surface, border, and DaisyUI list classes.                |
| Standard list attributes | `HTMLAttributes<"ul">`    | —       | Attributes such as `id`, `aria-label`, `aria-labelledby`, `data-*`, and `role` are forwarded to the outer `<ul>`. |

## Status colors

| Color       | DaisyUI badge class   |
| ----------- | --------------------- |
| `neutral`   | `badge-neutral`       |
| `primary`   | `badge-primary`       |
| `secondary` | `badge-secondary`     |
| `accent`    | `badge-accent`        |
| `info`      | `badge-info`          |
| `success`   | `badge-success`       |
| `warning`   | `badge-warning`       |
| `error`     | `badge-error`         |
| *(omitted)* | DaisyUI default badge |

## Build-time errors

The following conditions throw during `astro build` or `astro dev`:

- `items` array is empty.
- Any `item.title` is blank or whitespace-only.
- Any `item.media.label` (marker kind) is blank or whitespace-only.
- Any `item.status.label` is blank or whitespace-only.
- Any `item.action.label` is blank or whitespace-only.
- Any `item.action.href` is blank or whitespace-only.
- Any `item.href` is blank or whitespace-only.

## Images and markers

Image media only accepts imported local `ImageMetadata`. Astro determines the intrinsic dimensions and optimizes the output; the component supplies lazy loading and a square crop. Use meaningful alternative text when the image contributes information and `alt: ""` when it is redundant with the row title.

Markers are visual identifiers such as `01`, `A`, or `✓`. They are hidden from assistive technology because list semantics and the row title already identify the item. Do not put essential status information only in a marker; use the visible title, description, or status instead.

## Responsive behavior and customization

- Rows follow DaisyUI's horizontal grid at larger widths, while descriptions occupy the wrapped description column.
- At narrow widths, actions move to a full-width row to prevent crowded controls and horizontal page overflow.
- Long titles, metadata, and descriptions wrap instead of widening the publication.
- The outer list uses the current theme's base surface, border, content color, and rounded-box token.
- Use `class` for outer margin, width, or shadow; `itemClass` for shared row treatment; and item-level hooks for targeted adjustments.

## Accessibility

The component renders an unordered semantic list. Use ordinary ordered Markdown or `Steps` when position or progress matters.

Action text should describe its destination. Supply `ariaLabel` when a short visible label such as "Open" needs more context. External-link behavior should be evident from the label or surrounding prose because it opens a new browser tab.

Status badges supplement the row text; do not rely on badge color alone. Images need deliberate alternative text, while markers are decorative. Interactive buttons, menus, selection state, and multiple-action toolbars are outside this static publication component.
