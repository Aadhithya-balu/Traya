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
| [`EnrollWizard.tsx`](#enrollwizard) | `EnrollWizard` |
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

**Emergency Mode is now a first-class state of this component.** Two changes in
Phase 1, both load-bearing:

1. `logout` is rendered only when `isAuthed && !onEmergencyFlow`, and the
   overflow menu button is suppressed entirely on those routes via
   `hideMenu`. Previously `logout` was reachable from `/emergency/*`, so one
   mis-tap mid-emergency destroyed the session. That is the whole of the
   reported "emergency logs me out" complaint — there is no automatic logout
   anywhere in the codebase.
2. The `admin` entry in `moreItems` is gated on the same flag, because
   navigating to `/admin` mid-emergency is a distraction at best.

Suppressing the menu rather than only the logout row is deliberate: the sheet
holds the language switch and theme toggle, and changing either mid-emergency
is a mistake waiting to happen. Asserted by
`test_logout_is_not_reachable_from_an_emergency_route`.

Defects:

- `TabButton` accepts a `to?: string` prop that is never used; `Layout` passes
  `to=""`. Dead prop - remove it. The only remaining defect here.
- ~~The theme toggle knob never moves.~~ **Fixed in Phase 1.** It used
  `-translate-x-5.5`, which is not in the replaced `theme.spacing` table, so the
  class compiled to nothing and only the icon changed. It is now positioned from
  `left-0.5 top-0.5` and travels `translate-x-0` to `translate-x-6`, which is
  the exact width of a `w-6` knob inside a `w-12` track.

**Both fixed bars are now opaque, and `.tap` reaches five controls here.**
Phase 2: the app bar was `bg-canvas/90` and the tab bar `bg-surface/95`, both
with `backdrop-blur`, so content scrolled legibly under them and a blur sat
behind a colour that was nearly solid. They are `bg-canvas` and `bg-surface` now
with the blur removed — `test_no_backdrop_blur_without_a_solid_background` fails
if either returns. `tabClasses` carries `tap`, because `py-2` gave 41px, one
under the floor, and these are the most-tapped controls in the app. The language
pills and the theme toggle carry `tap -my-2`: 44px of hit area around a 28px
control.
  Unchanged, and now the only defect on this component.

## Guards

`components/Guards.tsx` -> `Protected`, `AdminOnly`. Both take `children`.
See [routing.md](routing.md#guards) for the logic.

Both render a hardcoded English `Loading...` string (not an i18n key). The
`text-slate-400` is fixed — migrated to `text-muted` in Phase 1 — so the fallback
is legible in both themes. The string itself is still Phase 2 work; replace it
with `t("common.loading")`.

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

`ListRow` and the `Tabs` strip both gained `tap` in Phase 2 — they were
`py-3 text-sm` and `py-3 text-sm` with no minimum, so a two-word row measured
under 44px.

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
- ~~`TONE_CLASS` uses classes Tailwind drops.~~ **Fixed in Phase 1.** `bg-ok/15`
  and its siblings were no-ops because the ramp had no `<alpha-value>`; see
  [design system](design-system.md#every-colour-is-stored-twice-and-the-second-copy-is-load-bearing).
  Badge tints now render. Asserted by
  `test_every_opacity_modifier_on_a_ramp_colour_resolves`.

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

**Still dead code, and that is now a contradiction rather than an oversight.**
Phase 1 added a local `EngineDisclosure` inside `EmergencyHub.tsx` rather than
wiring this component, because the notice had to be positioned above the
confidence bar and had to be non-dismissible, and that needed page-level
knowledge this component does not have.

The result is **two implementations of the same disclosure**, one of which is
the documented, i18n-backed, reusable one. That is a real duplication and the
duplicate is the uglier of the pair. Phase 2 should consolidate: promote
`EngineDisclosure` into this component, keep the placement rule, and render it
in `Demo` too — `Demo` shows an `IdentifyResult` with no disclosure at all,
which is the same omission in a page a reviewer is far more likely to open
first.

Per [ADR 0001](../decisions/0001-simulation-biometric-engine.md) the disclosure
belongs on every result.

## QualityPanel

`components/QualityPanel.tsx` -> `QualityPanel`.

| Prop | Type |
|---|---|
| `quality` | `QualityScores` |
| `usable` | `boolean` (optional) - overrides `quality.usable_for_matching` |

Renders the four real engine scores - blur, lighting, face visibility, occlusion
- as labelled bars, plus a usable/unusable badge and a bulleted list of
`quality.reasons`.

**The `NaN` hazard is fixed, and the fix was the type, not the arithmetic.**
`CaptureOut` is a *flat* shape (`image_quality_score`, `blur_score`, ...) whose
scores are all nullable, because the backend declares them `float | None = None`
and a capture can fail before any score exists. `Emergency.tsx` bridged it to
`Quality` with `as unknown as Quality`, so a null score reached
`Math.round(null * 100)` and then `width: NaN%` — a silently collapsed meter on
exactly the images where quality mattered most.

The prop is now `QualityScores`, whose scores are nullable, and a local `pct`
prints `--` and renders a zero-width bar for an absent score. `CaptureOut` and
`Quality` are both structurally assignable to it.
The remaining shape mismatch is real and unfixed: the API sends quality **flat**
on `CaptureOut` and **nested** inside `IdentifyResult.quality`. The component
now accepts either, which removed the cast, but it did not unify the API. The
proper fix is one nested `quality` object on both responses, which is a breaking
API change and belongs with the Phase 3 schema work. Until then, the component
handles both and `CaptureOut` no longer needs adapting.

The badge tints render correctly now — the `<alpha-value>` fix in Phase 1
resolved the same issue here as in `StatusBadge`.

## EnrollWizard

`components/EnrollWizard.tsx` -> `EnrollWizard`.

| Prop | Type |
|---|---|
| `onEnrolled` | `(status: EnrollmentComplete) => void` |
| `onCancel` | `() => void` |

The guided face-enrollment flow, mounted by `Profile` only when the person taps
*Start face enrollment* and holds `biometric_enrollment` consent at `active`.
Replaced the old 2-4 file upload there. It is deliberately **not** a route: a
half-finished enrollment is server state with a 20-minute TTL, and a page that
can be reloaded should resume rather than restart.

| Behaviour | Why |
|---|---|
| Mounts by calling `startEnrollment`, then renders `EnrollmentState` | The person is never shown a step the server has not agreed is current. Reload resumes. |
| One capture per request, via `submitEnrollmentSample` | The coach asks for one pose at a time. Batch submission is how the old upload path lost that. |
| Renders `verdict.guidance` as i18n keys, not sentences | Guidance codes come from the engine, so the wizard cannot disagree with `QualityPanel` about why a capture was refused. |
| Capture button disabled until `camera.active`; a file input remains | No camera or a denied permission must not dead-end enrollment - an upload is the same endpoint with one image. |
| *Start over* calls `cancelEnrollment` first | Discarding has to release the server-side row and its pending vectors, not merely unmount the component. |
| A 409/410 on submit clears state and shows only *Start over* | Those mean the enrollment is gone or finished server-side. Resuming would fail on every subsequent capture. |

Two things it deliberately does **not** do: it never advances the step itself
(that is `verdict.matched_step`), and it never computes how many samples are
still needed - `min_samples` and `can_complete` come from the server, so the two
minimums in the system cannot drift apart.

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
