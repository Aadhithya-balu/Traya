[../README.md](../README.md) | [Frontend index](README.md) | [Design system](design-system.md)

# UI Components

Every component in `src/components`, plus the complete icon set. No UI library
is installed; these are the only primitives available.

| File | Exports |
|---|---|
| [`Layout.tsx`](#layout) | `Layout` |
| [`Guards.tsx`](#guards) | `Protected`, `AdminOnly` |
| [`Sheet.tsx`](#sheet) | `Sheet` |
| [`Tabs.tsx`](#tabs) | `Tabs`, `ListRow` |
| [`StatusBadge.tsx`](#statusbadge) | `StatusBadge`, `ScoreBar`, `SimulationNotice` |
| [`QualityPanel.tsx`](#qualitypanel) | `QualityPanel` |
| [`icons.tsx`](#icons) | 17 icons |

---

## Layout

`components/Layout.tsx` -> `Layout`. No props. The app shell.

Composes a sticky `AppBar`, the `<Outlet />` content area, a fixed bottom tab
bar, and a `Sheet` overflow menu holding secondary navigation, the language
switch, the theme toggle and logout.

Internal pieces: `TabDef`, `PRIMARY_TABS` (four), `AppBar`, `TabLink`,
`TabButton`, `tabClasses`.

**It must render `<Outlet />`, not `{children}`.** `App.tsx` declares
`<Route element={<Layout />}>` with children, so the layout route has no props
to pass down. Rendering `{children}` here makes every page blank, and the
failure looks like a routing bug rather than a shell bug.

The tab bar is hidden entirely on `/emergency*`, and `<main>` padding switches
from `pb-tabbar` to `pb-safe` so the camera view gets full height.

Defects:

- `TabButton` accepts a `to?: string` prop that is never used; `Layout` passes
  `to=""`. Dead prop - remove it.
- The theme toggle knob uses `-translate-x-5.5`, which is not in the replaced
  `theme.spacing` scale, so the class produces nothing and **the knob never
  visibly moves** in either theme. Only the icon changes. Use a real token such
  as `-translate-x-4`.
- `bg-surface/95` and `bg-canvas/90` are dropped by Tailwind because ramp
  colours are plain `var(...)` strings with no `<alpha-value>` (see
  [design-system.md](design-system.md#the-opacity-modifier-does-not-work)), so
  **the tab bar and app bar have no background** - only `backdrop-blur`
  survives. Add an opaque token or a real background colour.

## Guards

`components/Guards.tsx` -> `Protected`, `AdminOnly`. Both take `children`.
See [routing.md](routing.md#guards) for the logic.

Both render a hardcoded English `Loading...` string (not an i18n key) in
`text-slate-400`, a removed token, so the fallback is nearly invisible in dark
mode. Replace with `t("common.loading")` in `text-muted`.

## Sheet

`components/Sheet.tsx` -> `Sheet`.

| Prop | Type |
|---|---|
| `open` | `boolean` |
| `title` | `string` |
| `onClose` | `() => void` |
| `children` | `ReactNode` |

A bottom sheet: scrim plus an `animate-sheet-in` panel, `role="dialog"`,
`aria-modal`, Escape to close, and a body scroll lock that saves and restores
`document.body.style.overflow`.

Returns `null` when `!open`, so it unmounts rather than hiding - meaning there
is no exit animation.

Accessibility gaps to close if you touch it: **no focus trap and no focus
restore.** Keyboard users can tab out of the sheet into the page behind it, and
focus is not returned to the trigger on close. Both are straightforward to add
and matter for a component that is already marked `aria-modal`.

The scrim is a `<button>` and the panel is its **sibling**, not its child, so
`onClose` appears twice. That is deliberate: it puts the panel above the scrim
in paint order without z-index gymnastics.

## Tabs

`components/Tabs.tsx` -> `Tabs` (generic over `T extends string`) and
`ListRow`.

| Component | Props |
|---|---|
| `Tabs` | `tabs: ReadonlyArray<{ id: T; label: StringKey }>`, `value: T`, `onChange: (id: T) => void` |
| `ListRow` | `to?: string`, `onClick?: () => void`, `title: string`, `subtitle?: string`, `trailing?: ReactNode` |

`Tabs` is a horizontally scrollable `role="tablist"` strip that keeps the
selected tab in view via a ref callback and `querySelector('[aria-selected]')`.
The ref callback runs that query on **every** ref invocation, not only when the
tab set changes, so it queries far more often than it needs to.

`ListRow` renders a `<Link>` when `to` is set and a `<button>` otherwise, so one
component serves both navigation rows and action rows. If neither `to` nor
`onClick` is given it still renders a button with no handler - make them a union
type if you want that to be a compile error.

`ListRow` is used only by `Layout`. `React.ReactNode` is referenced without
importing `React`; it compiles today via the UMD global from `@types/react`,
which is fragile. Prefer `import type { ReactNode } from "react"`.

## StatusBadge

`components/StatusBadge.tsx` -> `StatusBadge`, `ScoreBar`, `SimulationNotice`.

### StatusBadge

`{ status: string }`. Maps a backend status to a plain-language i18n label and a
tone, via the `STATUS` map and `TONE_CLASS`.

The mapping deliberately describes what a person should do rather than echoing
the enum, so nobody has to know what `REVIEW_REQUIRED` means.

| Status | Label key | Tone |
|---|---|---|
| `HIGH_CONFIDENCE` | `result.high` | ok |
| `REVIEW_REQUIRED` | `result.review` | warn |
| `LOW_CONFIDENCE` | `result.low` | warn |
| `NO_MATCH` | `result.none` | danger |
| `NO_FACE` | `result.none` | danger |
| `MULTIPLE_FACES` | `result.none` | danger |
| `POOR_QUALITY` | `emergency.quality.unusable` | danger |

Two issues:

- `NO_MATCH`, `NO_FACE` and `MULTIPLE_FACES` **collapse to the same label**, so
  a responder cannot distinguish "nobody is enrolled" from "two people are in
  frame" - and those need opposite responses. Split them.
- `TONE_CLASS` uses `bg-ok/15`, `bg-warn/15` and `bg-danger/15`, all of which
  Tailwind **drops** (see [design-system](design-system.md#the-opacity-modifier-does-not-work)).
  Badges currently render with text colour only and no tint.

### ScoreBar

| Prop | Type | Default |
|---|---|---|
| `value` | `number \| null` | required |
| `thresholdHigh` | `number` | `0.82` |
| `thresholdReview` | `number` | `0.62` |

Renders confidence as a bar with the percentage alongside, plus tick marks at
the two thresholds so a responder can see how close a result is to the review
line without reading the number. `null` renders `n/a` rather than `NaN%`.

`pct` is unclamped, so a backend value above 1.0 would overflow the bar. Clamp
it if the API is ever allowed to return one.

### SimulationNotice

`{ result?: IdentifyResult }`. The simulation banner.

**It is currently dead code - nothing renders it.** The docstring calls it "the
single most important banner in the product", and per
[ADR 0001](../decisions/0001-simulation-biometric-engine.md) it should be on
every result. Wire it into `EmergencyHub`, `Demo` and anywhere else an
`IdentifyResult` is shown. This is the highest-priority unused component in the
frontend.

## QualityPanel

`components/QualityPanel.tsx` -> `QualityPanel`.

| Prop | Type |
|---|---|
| `quality` | `Quality` |
| `usable` | `boolean` (optional) - overrides `quality.usable_for_matching` |

Renders the four real engine scores - blur, lighting, face visibility, occlusion
- as labelled bars, plus a usable/unusable badge and a bulleted list of
`quality.reasons`.

**Known type hazard.** `CaptureOut` is a *flat* shape
(`image_quality_score`, `blur_score`, ...) while `Quality` is what this component
requires. `Emergency.tsx` bridges them with `as unknown as Quality`, which
compiles but produces `NaN%` bars at runtime, because every field reads
`undefined`. If the two shapes ever diverge, nothing catches it.

Fix properly by giving the API one nested `quality` object on both
`CaptureOut` and `IdentifyOut`, and deleting the cast. Until then, do not pass a
`CaptureOut` to this component without adapting it first.

Note the badge reuses `bg-ok/15` and `bg-danger/15`, so it loses its tint for
the same reason the status badges do.

## Icons

`components/icons.tsx`. Inline SVG, no icon dependency. Seventeen glyphs.

`IconProps` is `Omit<SVGProps<SVGSVGElement>, "children"> & { size?: number }`.
The `base` helper sets `width`/`height` to `size` (default 22),
`viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`,
`strokeWidth={1.75}`, round caps and joins, `aria-hidden` and
`focusable="false"`.

One consistent stroke weight across the set is what makes a hand-rolled icon
family look deliberate rather than assembled. Keep it.

| Icon | Used in |
|---|---|
| `HomeIcon` | `Layout` primary tabs |
| `PulseIcon` | `Layout`, `Emergency` |
| `UserIcon` | `Layout` primary tabs |
| `GridIcon` | `Layout` primary tabs |
| `MoreIcon` | `Layout` app bar and tab bar |
| `ShieldIcon` | `Layout` More sheet |
| `BeakerIcon` | `Layout` More sheet |
| `SunIcon` | `Layout` theme toggle |
| `MoonIcon` | `Layout` theme toggle |
| `GlobeIcon` | `Layout` language switch |
| `CameraIcon` | `Emergency` |
| `CloseIcon` | `Sheet` |
| `ChevronRightIcon` | `Layout`, `Dashboard` |
| `ChevronLeftIcon` | **unused - dead code** |
| `CheckIcon` | `Landing`, `Register`, `Dashboard`, `QualityPanel` |
| `AlertIcon` | `Layout`, `Login`, `Register`, `Emergency`, `QualityPanel` |
| `ArrowIcon` | `Landing` |

Two cleanups: `ChevronLeftIcon` is never used, and the file docstring says
"fifteen glyphs" when there are seventeen. `IconProps` is not exported, so a
consumer cannot type their own icon-compatible component - export it if you
plan to add a custom glyph.
