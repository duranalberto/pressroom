# Mockup Browser Component

`MockupBrowser.astro` presents arbitrary content in DaisyUI's browser mockup. It is a static, theme-aware component with a generated address display or custom toolbar, and it adds no client-side JavaScript.

**Import path:** `@components/ui/display/MockupBrowser.astro`

## Component signature

```ts
// Props interface (extends HTMLAttributes<"figure">)
interface Props {
  url?: string;           // static address text; required unless toolbar slot is filled
  class?: string;         // outer <figure> classes
  browserClass?: string;  // .mockup-browser frame classes
  toolbarClass?: string;  // toolbar region classes
  addressClass?: string;  // generated address display classes (unused when toolbar slot is filled)
  contentClass?: string;  // default-slot viewport classes
  captionClass?: string;  // <figcaption> classes (only rendered when caption slot is filled)
  // All other HTMLAttributes<"figure"> are forwarded to the outer <figure>.
}
```

## Astro usage

```astro
---
import MockupBrowser from "@components/ui/display/MockupBrowser.astro";
---

<MockupBrowser
  url="https://example.com/account"
  aria-label="Account page browser preview"
>
  <div class="grid min-h-72 place-items-center p-6">
    <h2>Account</h2>
  </div>
</MockupBrowser>
```

The optional `caption` slot adds supporting context below the browser frame.

```astro
<MockupBrowser
  url="https://example.com/reports/weekly"
  browserClass="shadow-2xl"
  contentClass="bg-base-200"
  aria-label="Weekly report browser preview"
>
  <div class="grid min-h-72 place-items-center p-6">Weekly report</div>
  <span slot="caption">The report at its hosted route.</span>
</MockupBrowser>
```

## Custom toolbar

Use the `toolbar` slot when the publication needs browser-specific context beyond one URL, such as an environment badge or a deliberately simplified local-preview address. The slot replaces the generated address display, so `url` can be omitted.

```astro
<MockupBrowser aria-label="Local preview browser state">
  <div slot="toolbar" class="flex min-w-0 items-center gap-2">
    <span class="badge badge-warning">Preview</span>
    <span class="truncate font-mono text-sm">localhost:4321/report</span>
  </div>

  <div class="grid min-h-64 place-items-center p-6">Preview ready</div>
</MockupBrowser>
```

When the `toolbar` slot is filled, `url` and `addressClass` are ignored entirely. Without a custom toolbar, `url` must contain non-whitespace text — otherwise the build throws.

## Screenshot usage

Use Astro's `Image` component for local screenshots. A direct image child is treated as static presentation: it cannot receive pointer input, be selected, or start a native drag gesture.

```astro
---
import { Image } from "astro:assets";
import MockupBrowser from "@components/ui/display/MockupBrowser.astro";
import dashboardScreenshot from "@assets/dashboard-desktop.png";
---

<MockupBrowser
  url="https://example.com/dashboard"
  aria-label="Hosted dashboard screenshot"
>
  <Image
    src={dashboardScreenshot}
    alt="Dashboard showing weekly activity and two unread alerts"
    widths={[640, 960, 1280]}
    sizes="(max-width: 1024px) 100vw, 960px"
  />
  <span slot="caption">The production dashboard route.</span>
</MockupBrowser>
```

Image optimization and alternative text remain consumer responsibilities. Nested images inside composed content are not suppressed because they may belong to links or controls; consumers own their drag and interaction behavior.

## MDX publication usage

Import the component after the publication frontmatter.

```mdx
import MockupBrowser from "@components/ui/display/MockupBrowser.astro";

<MockupBrowser
  url="https://status.example.com/outage"
  aria-label="Service outage page"
  browserClass="shadow-xl"
>
  <div className="grid min-h-64 place-items-center bg-base-200 p-8 text-center">
    <div>
      <strong className="text-error">Service unavailable</strong>
      <p className="mt-2 text-base-content/70">Retry after 30 seconds.</p>
    </div>
  </div>
  <span slot="caption">The failure as readers encounter it in-browser.</span>
</MockupBrowser>
```

The outer figure applies `not-prose`. Add spacing and typography classes needed by composed viewport or toolbar content.

## Props

| Prop                       | Type                        | Default | Purpose                                                                                              |
| -------------------------- | --------------------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `url`                      | `string`                    | —       | Static address text. Required unless the `toolbar` slot is present.                                  |
| `class`                    | `string`                    | —       | Adds classes to the outer `<figure>`.                                                                |
| `browserClass`             | `string`                    | —       | Adds classes to the DaisyUI `.mockup-browser` frame.                                                 |
| `toolbarClass`             | `string`                    | —       | Adds classes to the `.mockup-browser-toolbar` region.                                                |
| `addressClass`             | `string`                    | —       | Adds classes to the generated address display; unused when a custom toolbar is supplied.             |
| `contentClass`             | `string`                    | —       | Adds classes to the default-slot viewport.                                                           |
| `captionClass`             | `string`                    | —       | Adds classes to the optional `<figcaption>`.                                                         |
| Standard figure attributes | `HTMLAttributes<"figure">`  | —       | Forwards attributes such as `id`, `aria-label`, `aria-labelledby`, and `data-*` to the outer figure. |

All class hooks are optional and merge with component defaults.

## Slots

| Slot      | Purpose                                                         | Rendered when    |
| --------- | --------------------------------------------------------------- | ---------------- |
| Default   | Required browser viewport content supplied by the consumer.     | Always           |
| `toolbar` | Optional replacement for the generated static address display.  | Slot is filled   |
| `caption` | Optional supporting text rendered as `<figcaption>`.            | Slot is filled   |

## Build-time errors

- `toolbar` slot is empty **and** `url` is missing or blank (whitespace-only).

## Styling and responsive behavior

- The frame fills its available width and follows the active DaisyUI light or dark theme.
- Long generated URLs truncate inside the address display instead of widening the page.
- Wide viewport content scrolls inside the browser frame.
- The toolbar becomes more compact on narrow screens.
- Direct screenshot images are non-draggable; composed controls and nested media retain normal pointer behavior.
- Use `class` for outer spacing or width and the region-specific hooks for frame, toolbar, address, viewport, and caption styling.

## Accessibility

Use `aria-label` when a short phrase identifies the complete browser demonstration. If visible viewport content provides the title, give it an `id` and use `aria-labelledby` on `MockupBrowser`. The generated URL is visible context, not an editable field or link.

Screenshots need useful alternative text when they convey information. Slotted links, buttons, form controls, focus behavior, and nested images remain consumer responsibilities. Do not use browser chrome when the URL or browser context adds nothing; use `MockupWindow` or a normal image instead.
