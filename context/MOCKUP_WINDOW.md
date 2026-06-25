# Mockup Window Component

`MockupWindow.astro` presents arbitrary content in DaisyUI's window mockup. It is a static, theme-aware component with no client-side JavaScript and can be imported by Astro pages, layouts, components, and MDX publications.

**Import path:** `@components/ui/display/MockupWindow.astro`

## Component signature

```ts
// Props interface (extends HTMLAttributes<"figure">)
interface Props {
  class?: string;         // outer <figure> classes
  windowClass?: string;   // .mockup-window frame classes
  contentClass?: string;  // complete surface beneath window chrome (wraps header + body)
  headerClass?: string;   // optional header region classes (only rendered when header slot is filled)
  bodyClass?: string;     // default-slot body region classes
  captionClass?: string;  // <figcaption> classes (only rendered when caption slot is filled)
  // All other HTMLAttributes<"figure"> are forwarded to the outer <figure>.
}
```

## Astro usage

```astro
---
import MockupWindow from "@components/ui/display/MockupWindow.astro";
---

<MockupWindow aria-label="Account settings preview">
  <h2>Account settings</h2>
  <p>Window content belongs to the consumer.</p>
</MockupWindow>
```

The optional named slots add an in-window header and a caption below the frame.

```astro
<MockupWindow
  aria-labelledby="settings-preview-title"
  class="my-12"
  windowClass="shadow-2xl"
  bodyClass="grid min-h-72 place-items-center"
>
  <span id="settings-preview-title" slot="header">Settings preview</span>

  <p>Preview content</p>

  <span slot="caption">The settings screen at desktop width.</span>
</MockupWindow>
```

## MDX publication usage

Import the Astro component after the publication frontmatter, then use it like any other MDX component.

```mdx
import MockupWindow from "@components/ui/display/MockupWindow.astro";

<MockupWindow
  aria-label="Generated report preview"
  bodyClass="min-h-64"
>
  <strong slot="header">Report preview</strong>

<p>The default slot accepts MDX-compatible markup and components.</p>

  <span slot="caption">A report rendered during the build.</span>
</MockupWindow>
```

The component applies `not-prose` to its figure so publication typography does not restyle its internal interface. Add the typography and spacing needed by the slotted content explicitly.

When the default slot is a direct screenshot image, the component treats it as static presentation and prevents pointer input, selection, and native dragging. Images nested inside composed interface markup retain normal behavior for links and controls.

## Props

| Prop                       | Type                        | Default | Purpose                                                                                              |
| -------------------------- | --------------------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `class`                    | `string`                    | —       | Adds classes to the outer `<figure>`.                                                                |
| `windowClass`              | `string`                    | —       | Adds classes to the DaisyUI `.mockup-window` frame.                                                  |
| `contentClass`             | `string`                    | —       | Adds classes to the complete surface beneath the window chrome (contains both header and body).      |
| `headerClass`              | `string`                    | —       | Adds classes to the optional header region (only rendered when the `header` slot is filled).         |
| `bodyClass`                | `string`                    | —       | Adds classes to the default-slot body.                                                               |
| `captionClass`             | `string`                    | —       | Adds classes to the optional `<figcaption>`.                                                         |
| Standard figure attributes | `HTMLAttributes<"figure">`  | —       | Forwards attributes such as `id`, `aria-label`, `aria-labelledby`, and `data-*` to the outer figure. |

All class hooks are optional and are merged with the component defaults.

### `contentClass` vs `bodyClass`

These two props target different levels of the window interior:

- `contentClass` — the full content surface beneath the chrome (border-top + background). Use it to change the overall interior background or add a border.
- `bodyClass` — the scrollable body below the optional header. Use it to set `min-h-*`, `p-*`, layout, or overflow on the body alone.

Both can be used together; `bodyClass` wins for the body region.

## Slots

| Slot      | Purpose                                                  | Rendered when  |
| --------- | -------------------------------------------------------- | -------------- |
| Default   | Required window content supplied by the consumer.        | Always         |
| `header`  | Optional heading or compact toolbar above the body.      | Slot is filled |
| `caption` | Optional descriptive content rendered as `<figcaption>`. | Slot is filled |

Empty optional slots do not render their wrapper elements.

## Styling and behavior

- The frame uses DaisyUI's `mockup-window` component and the site's `base-100`, `base-200`, `base-300`, and `base-content` theme tokens.
- The component fills its available width by default. Use `class` for outer width or spacing and the region-specific hooks for internal layout.
- Wide body content scrolls inside the component instead of widening the page. Padding becomes more compact on narrow screens.
- Direct `<img>` and `<picture>` screenshot children are non-draggable. Nested images retain consumer-owned pointer and drag behavior.
- The component follows the active light or dark DaisyUI theme automatically.

## Accessibility

Use `aria-label` when a short label describes the entire mockup. When the header contains a visible title, give that title an `id` and use `aria-labelledby` on `MockupWindow`. Use the caption for supporting context rather than as the only label for important interactive content.

Slotted controls retain their own accessibility responsibilities. Use semantic links and buttons, visible focus styles, and meaningful control labels inside the window.
