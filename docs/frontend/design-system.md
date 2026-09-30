[../README.md](../README.md) | [Frontend index](README.md) | [Components](components.md)

# Design System

Monochrome by decision, not by accident. One token set, two themes, no
component library. See
[ADR 0004](../decisions/0004-monochrome-mobile-design-system.md) for why.

Three files own everything: `tailwind.config.js` (the token maps),
`index.css` (the values and the composed classes), `i18n/strings.ts` (every
user-visible word). There is no fourth place.

---

## Colour tokens

Colours are emitted as **CSS custom properties** in `index.css` and mapped into
Tailwind as the `ramp` object. Light and dark therefore share one set of class
names - `bg-surface` means the same thing in both themes, and there is no
`dark:bg-*` variant anywhere in the codebase.

`darkMode: "class"`, and `.dark` on `<html>` is the switch.

| Token | Role | Light | Dark |
|---|---|---|---|
| `--c-canvas` | Page background | `#f6f6f5` | `#0a0a0b` |
| `--c-surface` | Cards, sheets, bars | `#ffffff` | `#131314` |
| `--c-raised` | Inputs, secondary fills | `#f0f0ef` | `#1c1c1e` |
| `--c-line` | Default border | `#e2e2e0` | `#2a2a2d` |
| `--c-line-strong` | Emphasised border | `#c9c9c6` | `#3d3d41` |
| `--c-text` | Body text | `#17171a` | `#f2f2f0` |
| `--c-muted` | Secondary text | `#5c5c63` | `#a1a1a6` |
| `--c-faint` | Tertiary text, eyebrows | `#8a8a92` | `#6e6e75` |
| `--c-accent` | Interactive fill | `#17171a` | `#f2f2f0` |
| `--c-accent-text` | Accent-coloured text | `#17171a` | `#f2f2f0` |
| `--c-accent-fg` | Text on accent | `#ffffff` | `#0a0a0b` |
| `--c-danger` | Danger, stop, `no match` | `#b4231f` | `#e5484d` |
| `--c-danger-fg` | Text on danger | `#ffffff` | `#1a0a0a` |
| `--c-warn` | Caution, review required | `#8a5a00` | `#f0b429` |
| `--c-warn-fg` | Text on warn | `#ffffff` | `#1a1200` |
| `--c-ok` | Success, high confidence | `#1f6b3a` | `#3fa45c` |
| `--c-ok-fg` | Text on ok | `#ffffff` | `#06180c` |
| `--safe-top` | Notch inset | `env(safe-area-inset-top)` | same |
| `--safe-bottom` | Home indicator inset | `env(safe-area-inset-bottom)` | same |

Eight neutrals, then exactly three semantic hues. `accent` is
near-black/near-white, so the "brand" is a high-contrast neutral and the only
colour on screen is a status. That is the whole point: in an emergency, colour
must mean something, so nothing is allowed to be decorative.

Every `-fg` token exists because a single `accent` value is not always legible
against itself in both themes.

## The opacity modifier does not work

**`bg-ok/15`, `text-danger/80` and every other `/opacity` utility on a ramp
colour silently produces nothing.**

The ramp is a bare `var(--c-ok)` with no `<alpha-value>` placeholder, so
Tailwind cannot append an alpha channel and drops the class. Concretely, in the
current tree:

| Class | Where | Renders as |
|---|---|---|
| `bg-ok/15` | `StatusBadge`, `QualityPanel` | no tint |
| `bg-warn/15` | `StatusBadge` | no tint |
| `bg-danger/15` | `StatusBadge`, `QualityPanel` | no tint |
| `bg-surface/95` | `Layout` app bar and tab bar | no background |
| `bg-canvas/90` | `Layout` | no background |

Nothing errors; the classes are simply absent from the stylesheet. The app bar
and tab bar currently rely on `backdrop-blur` alone over `body`'s `bg-canvas`,
and the status badges have no background at all.

Two fixes, in order of preference:

1. **Add `<alpha-value>` to the ramp** using the `rgb(var(--c-ok) / <alpha-value>)`
   pattern, which means storing each channel as a separate custom property
   (`--c-ok-rgb: 31 107 58;`). Correct, but it touches every token.
2. **Add opaque `*-soft` tokens** - `--c-ok-soft`, `--c-warn-soft`,
   `--c-danger-soft`, `--c-surface-opaque` - with hand-picked light and dark
   values, and use those.

Option 2 is fewer changes and gives better control over contrast in each theme.
Until one is done, treat every `/opacity` ramp utility in the codebase as a
no-op. `check-docs.mjs` cannot catch this, because it is a CSS-generation
behaviour rather than a missing name.

## Spacing

`theme.spacing` is **replaced, not extended**, with a coarser ramp: `0.5` is
0.125rem, `1` is 0.25rem, and the scale jumps from `0.25rem` to `0.5rem` at `2`.
A cramped 360px screen is much easier to ship by accident with Tailwind's
default 0.25rem steps, so the finer steps were removed.

**The replacement has no `<alpha-value>`-style extras and drops a few standard
keys.** Anything outside the table - `0.75`, `13`, `28`, `5.5` - **generates
nothing**. `Layout` uses `-translate-x-5.5` for its theme knob, so the knob
does not move.

Available: `0`, `px`, `0.5`, `1`, `1.5`, `2`, `2.5`, `3`, `3.5`, `4`, `5`, `6`,
`7`, `8`, `9`, `10`, `11`, `12`, `14`, `16`, `20`, `24`, `32`, `40`, `48`,
`56`, `64`, `full`. Note the deliberate gap: there is no `13`.

## Component classes

`@layer components` in `index.css`. These are the only composed classes; reach
for one of these before writing a long `className`.

| Class | Purpose |
|---|---|
| `.tap` | `min-h-touch min-w-touch` (44px). Minimum target for anything tappable. |
| `.btn` | Base button. 2.75rem minimum height, disabled dimmed and inert. |
| `.btn-lg` | `.btn` plus 3.25rem height and `text-base`. |
| `.btn-block` | Full-width `.btn`. |
| `.btn-primary` | Accent fill. |
| `.btn-danger` | Danger fill. |
| `.btn-ghost` | Outlined, surface fill. |
| `.btn-quiet` | Text only, no border. |
| `.card` | Surface panel, `rounded-xl`, `p-4`. |
| `.card-raised` | `.card` on `--c-raised`. |
| `.input` | Full-width field, 2.75rem minimum, 16px font. |
| `.label` | Uppercase micro-label above a field. |
| `.badge` | Pill container. |
| `.divider` | One-pixel rule. |
| `.eyebrow` | Section title that reads as a heading. |
| `.scroll-x` | Edge-bleeding horizontal scroller with a hidden scrollbar. |

Three of these exist for reasons that are not obvious from the CSS, so do not
"simplify" them away:

- **`.input` is `text-base` (16px) on purpose.** Anything smaller makes iOS
  Safari zoom the viewport on focus, which breaks the layout mid-typing.
- **`.scroll-x` hides the scrollbar entirely.** A visible scrollbar in a tab
  strip competes with the tabs themselves. It scrolls, and the content bleeding
  to the screen edge is what tells you so.
- **`.btn` sets a hard `min-height` in plain CSS, not via a token.** That is
  what makes it survive the spacing replacement.

## Utilities

`@layer utilities` in `index.css`. Layout helpers for a device with a notch.

| Class | Value |
|---|---|
| `.pt-safe` | `padding-top: var(--safe-top)` |
| `.pb-safe` | `padding-bottom: var(--safe-bottom)` |
| `.pb-tabbar` | `calc(4.25rem + var(--safe-bottom))` |
| `.pt-appbar` | `calc(3.5rem + var(--safe-top))` |
| `.mt-appbar` | `calc(3.5rem + var(--safe-top))` |
| `.h-appbar` | `calc(3.5rem + var(--safe-top))` |

The three `*appbar` helpers exist so the fixed app bar's height is stated once.
`pb-tabbar` and `pb-safe` are the pair `Layout` swaps between: a tabbed page
needs room for the bar, a camera page does not.

## Global base rules

Four rules in `@layer base` that affect every screen:

1. `* { -webkit-tap-highlight-color: transparent }` - removes the grey flash on
   tap. Without it every button looks broken on mobile.
2. `html { -webkit-text-size-adjust: 100% }` - stops iOS inflating text in
   landscape.
3. `body { overflow-x: hidden }` - a stray wide child cannot create the
   horizontal scroll that makes a page feel broken. This masks overflow bugs;
   if something is overflowing, look for a fixed-width child rather than
   removing this.
4. `:focus-visible` gets one consistent ring (`ring-2 ring-accent
   ring-offset-2`). It is restyled, never removed - keyboard users need it.
5. `::selection` inverts text against canvas.

Plus a global `prefers-reduced-motion` block that collapses **every** animation
and transition to 0.01ms. No per-component opt-out exists, which is the point:
reduced motion is handled once, globally.

## Typography

| Token | Size / line height |
|---|---|
| `xs` | 0.75rem / 1rem |
| `sm` | 0.875rem / 1.25rem |
| `base` | 1rem / 1.5rem |
| `lg` | 1.125rem / 1.75rem |
| `xl` | 1.25rem / 1.75rem |
| `2xl` | 1.5rem / 2rem |
| `3xl` | 1.875rem / 2.25rem |
| `4xl` | 2.25rem / 2.5rem |

Line heights are set explicitly on every step. Sizing type without a paired
line height is what produces cramped screens, so the config makes you specify
both.

`sans` is `Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif`;
`mono` is `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`.

**`Inter` is declared but never loaded** - there is no `@font-face` and no
`<link>` in `index.html`, and the app loads no webfont. So every device
effectively renders in its system UI font. Either add the font or drop it from
the stack; today it is a dead first entry that makes the font look
intentionally chosen when it is not.

## Radii, motion, touch targets

`borderRadius` is replaced with an explicit set: `sm` 0.375rem, `DEFAULT`
0.5rem, `md` 0.625rem, `lg` 0.75rem, `xl` 1rem, `2xl` 1.25rem, `full` 9999px.
Cards are `xl`; buttons and inputs are `md`.

Three animations, all short and all transform- or opacity-only:

| Class | Keyframes | Duration / easing |
|---|---|---|
| `animate-sheet-in` | `translateY(100%)` -> `0` | 220ms `cubic-bezier(0.32, 0.72, 0, 1)` |
| `animate-fade-in` | `opacity 0` -> `1` | 160ms ease-out |
| `animate-rise` | `opacity 0` + `translateY(6px)` -> rest | 200ms `cubic-bezier(0.32, 0.72, 0, 1)` |

`transitionDuration` adds a single `150` step; that is the only one, so durations
are either the three above or 150ms.

`minHeight.touch` is 2.75rem, `minHeight.touch-lg` is 3rem, `minWidth.touch` is
2.75rem. 44px is the iOS guideline, and `.tap` applies it to both axes.

## i18n namespaces

`i18n/strings.ts` holds `en` and `ta`. Keys are **flat strings with a dotted
prefix**, not nested objects - `"nav.home"`, not `{ nav: { home } }`. Flat keys
keep the `StringKey` type trivially derivable and make grep for a visible string
reliable.

`i18n/index.ts` asserts at module load that `ta` defines **exactly** the same
key set as `en`, so a missing translation is a startup error rather than an
English word leaking into a Tamil screen.

Twenty namespaces:

| Namespace | Covers |
|---|---|
| `app` | Name, tagline. |
| `nav` | Tab bar, app bar, sheet entries. |
| `a11y` | Screen-reader and icon-button labels. |
| `lang` | Language names in their own language. |
| `common` | Save, cancel, delete, loading, yes, no. |
| `landing` | Hero, features, steps, CTAs. |
| `auth` | Login and register. |
| `emergency` | Capture flow, quality states, session start. |
| `result` | Match status labels and confidence copy. |
| `medical` | Medical profile and public summary. |
| `contact` | Emergency contacts and contact actions. |
| `location` | GPS, hospital list, routing. |
| `timeline` | Session event timeline. |
| `dashboard` | Summary tiles, enrolment CTA, access history. |
| `profile` | Profile sections, consent, enrolment, features. |
| `enroll` | Guided pose capture steps. |
| `demo` | Demo scenarios and results. |
| `admin` | Admin console tabs, roles, settings, audit. |
| `privacy` | Privacy principles. |
| `error` | Error and empty states. |

`useI18n()` returns `{ t, locale, setLocale, toggle }`. Missing keys fall back
to the key itself rather than rendering `undefined`.

Coverage is incomplete by design of the migration, not by accident: the legacy
pages still hardcode English, and `Privacy` does not even use its `privacy.*`
keys. The namespaces exist and are populated; the pages have not caught up.

## Legacy pages

Five pages still use the removed `ink-*` / `slate-*` palette and hardcoded
English: `EmergencyHub`, `Profile`, `Admin`, `Demo`, `Privacy`. See
[pages.md](pages.md) for the per-page defect list. `Privacy` is the worst -
`text-white` on a light canvas makes its headings invisible, and
`text-accent-400` no longer exists.

`Grep` for the old tokens before assuming a page is migrated:

```powershell
Select-String -Path src\pages\*.tsx -Pattern 'ink-|slate-|accent-\d|text-white'
```

Until that returns nothing for a page, treat it as legacy and do not add new
features to it - a rewrite is cheaper than a fix.
