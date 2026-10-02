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

Every colour row below is **two declarations**: the hex form and the RGB
channel triplet. The triplet is what Tailwind substitutes an alpha channel
into, so it is not optional. See "Every colour is stored twice" below.

| Token | Channels | Role | Light | Dark |
|---|---|---|---|---|
| `--c-canvas` | `--c-canvas-rgb` | Page background | `#f6f6f5` | `#0a0a0b` |
| `--c-surface` | `--c-surface-rgb` | Cards, sheets, bars | `#ffffff` | `#131314` |
| `--c-raised` | `--c-raised-rgb` | Inputs, secondary fills | `#f0f0ef` | `#1c1c1e` |
| `--c-line` | `--c-line-rgb` | Default border | `#e2e2e0` | `#2a2a2d` |
| `--c-line-strong` | `--c-line-strong-rgb` | Emphasised border | `#c9c9c6` | `#3d3d41` |
| `--c-text` | `--c-text-rgb` | Body text | `#17171a` | `#f2f2f0` |
| `--c-muted` | `--c-muted-rgb` | Secondary text | `#5c5c63` | `#a1a1a6` |
| `--c-faint` | `--c-faint-rgb` | Tertiary text, eyebrows | `#6a6a70` | `#86868c` |
| `--c-accent` | `--c-accent-rgb` | Interactive fill | `#17171a` | `#f2f2f0` |
| `--c-accent-text` | `--c-accent-text-rgb` | Accent-coloured text | `#17171a` | `#f2f2f0` |
| `--c-accent-fg` | `--c-accent-fg-rgb` | Text on accent | `#ffffff` | `#0a0a0b` |
| `--c-danger` | `--c-danger-rgb` | Danger, stop, `no match` | `#b4231f` | `#ea6e71` |
| `--c-danger-fg` | `--c-danger-fg-rgb` | Text on danger | `#ffffff` | `#1a0a0a` |
| `--c-warn` | `--c-warn-rgb` | Caution, review required | `#825500` | `#f0b429` |
| `--c-warn-fg` | `--c-warn-fg-rgb` | Text on warn | `#ffffff` | `#1a1200` |
| `--c-ok` | `--c-ok-rgb` | Success, high confidence | `#1f6b3a` | `#41aa5f` |
| `--c-ok-fg` | `--c-ok-fg-rgb` | Text on ok | `#ffffff` | `#06180c` |
| `--safe-top` | — | Notch inset | `env(safe-area-inset-top)` | same |
| `--safe-bottom` | — | Home indicator inset | `env(safe-area-inset-bottom)` | same |

Eight neutrals, then exactly three semantic hues. `accent` is
near-black/near-white, so the "brand" is a high-contrast neutral and the only
colour on screen is a status. That is the whole point: in an emergency, colour
must mean something, so nothing is allowed to be decorative.

Every `-fg` token exists because a single `accent` value is not always legible
against itself in both themes.

### Contrast is measured against the background that actually renders

`backend/tests/test_contrast.py` asserts AA (4.5:1) for every text token against
every background it is used on. It exists because four tokens passed a casual
eyeball check and failed the measurement, and the interesting part is *where*
they failed:

| Token | Was | Plain ramp | On its own tint | Now |
|---|---|---|---|---|
| light `--c-faint` | `#8a8a92` | 3.17 | — | `#6a6a70` (4.71) |
| dark `--c-faint` | `#6e6e75` | 3.91 | — | `#86868c` (4.70) |
| dark `--c-danger` | `#e5484d` | 4.35 | 3.71 on `bg-danger/15` | `#ea6e71` (4.57) |
| light `--c-warn` | `#8a5a00` | 5.20 | 4.26 on `bg-warn/15` | `#825500` (4.60) |
| dark `--c-ok` | `#3fa45c` | 5.41 | 4.40 on `bg-ok/15` | `#41aa5f` (4.64) |

Light `--c-warn` is the lesson. It cleared 5.20:1 on `canvas`, `surface` and
`raised` alike, so it passed every plain check. But a badge is `bg-warn/15 text-warn`,
and a 15% tint of the text colour over the background **pulls the background
toward the text**, which always makes the pair worse than the plain surface. At
`/15` over `raised` it was 4.26:1.

So a tinted pairing is the worst case, never a plain ramp colour, and the test
enumerates `bg-{tone}/{10,15} over {canvas,surface,raised}` for all three
semantic tones in both themes. Three of the five fixes above are invisible to a
contrast checker that only compares token against token.

Two rules the codebase learned the hard way:

1. **`-fg` means "on this colour", not "on the page".** The camera-error bar was
   `bg-danger/90 text-text`, which is 3.18:1 — below AA in both themes. It is
   now `text-accent-fg`, which is the ramp's own answer to that question and
   measures 5.63:1 and 5.48:1. `--c-accent-fg` differs per theme (white in
   light, near-black in dark), so a hardcoded colour would have passed in one
   theme and failed in the other.
2. **Solid beats translucent on a fixed bar.** `bg-canvas/90` and
   `bg-surface/95` with `backdrop-blur` were both wrong twice: translucent, so
   content scrolled legibly underneath the app bar on a result screen; and
   pointless, because a blur behind a solid colour costs a compositing layer per
   frame and shows nothing. Both bars are now opaque, and
   `test_no_backdrop_blur_without_a_solid_background` fails if
   `backdrop-blur` or a `bg-*/NN` bar returns to `Layout.tsx`.

## Every colour is stored twice, and the second copy is load-bearing

Each ramp token has a hex form and an RGB channel triplet:

| Token | Also | Purpose |
|---|---|---|
| `--c-danger` | `--c-danger-rgb` | hand-written CSS that wants a literal colour |
| `--c-danger-rgb` | — | `rgb(var(--c-danger-rgb) / <alpha-value>)` in `tailwind.config.js` |

**This is what makes `/opacity` work, and it was the single cause of the
missing backgrounds documented in the audit.** The ramp used to be a bare
`var(--c-danger)`, which is a valid colour string, so the build succeeded - but
Tailwind could not synthesise an alpha channel from it and dropped every
modifier class. `bg-danger/10`, `bg-ok/15`, `border-warn/40` and
`bg-canvas/90` were all absent from the stylesheet. The fixed app bar and tab bar
had no background, so page content scrolled visibly underneath both, and every
status badge tint was missing. Nothing errored, which is why it survived a
passing typecheck and build.

Verified in the current build output:

```css
.bg-danger\/10 { background-color: rgb(var(--c-danger-rgb) / .1) }
.border-warn\/40 { border-color: rgb(var(--c-warn-rgb) / .4) }
.bg-ok\/15      { background-color: rgb(var(--c-ok-rgb) / .15) }
```

Note that `bg-canvas/90` is no longer in that list: the app bar is opaque now.
The only heavy tint left is `bg-danger/90`, on the camera-error bar.

Two rules now keep it true. `test_every_opacity_modifier_on_a_ramp_colour_resolves`
asserts `<alpha-value>` is in the config and that every ramp name has an `-rgb`
twin in `index.css`. `test_no_component_uses_an_off_ramp_colour` and
`test_class_strings_do_not_contain_off_ramp_colours` assert no component uses a
numbered colour outside the ramp, because an unknown class is not an error - it
is simply missing from the output.

**Adding a colour means adding both lines.** A hex form alone will compile, and
every opacity modifier on it will be a silent no-op.

The `*-soft` alternative was rejected. Opaque tokens cannot darken or lighten
with the theme, so they would need a hand-picked light and dark pair per
semantic state, and a state added later would ship with one theme correct and
the other wrong.

## Spacing

`theme.spacing` is **replaced, not extended**, with a coarser ramp: `0.5` is
0.125rem, `1` is 0.25rem, and the scale jumps from `0.25rem` to `0.5rem` at `2`.
A cramped 360px screen is much easier to ship by accident with Tailwind's
default 0.25rem steps, so the finer steps were removed.

**The replacement drops a few standard keys.** Anything outside the table -
`0.75`, `13`, `28`, `5.5` - **generates nothing**, and it is not an error.

Available: `0`, `px`, `0.5`, `1`, `1.5`, `2`, `2.5`, `3`, `3.5`, `4`, `5`, `6`,
`7`, `8`, `9`, `10`, `11`, `12`, `14`, `16`, `20`, `24`, `32`, `40`, `48`,
`56`, `64`, `full`. Note the deliberate gaps: no `13`, no `5.5`.

**Phase 2 considered adding `5.5` and `13` and did not.** The migration plan
proposed it, because `-translate-x-5.5` had been compiling to nothing and
adding the key would have made that class work. But the caller was wrong, not
the scale: the theme knob is a `w-6` knob in a `w-12` track, so its travel is
1.5rem, which is `translate-x-6`. Adding `5.5` would have re-legalised the
exact trap that had just cost a bug - an off-scale value that looks fine and
produces no CSS - and left the next one undocumented.

`test_spacing_uses_only_values_in_the_theme_table` now covers
`translate-[xy]`, `scroll-m*` and the inset utilities as well, because the
earlier pattern omitted `translate` and so **could not have caught the bug it
was written for**. It strips comments before scanning, since both the test and
`index.css` now describe these traps in prose.

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

Four of these exist for reasons that are not obvious from the CSS, so do not
"simplify" them away:

- **`.input` is `text-base` (16px) on purpose.** Anything smaller makes iOS
  Safari zoom the viewport on focus, which breaks the layout mid-typing.
- **`.scroll-x` hides the scrollbar entirely.** A visible scrollbar in a tab
  strip competes with the tabs themselves. It scrolls, and the content bleeding
  to the screen edge is what tells you so. `Admin` and `EmergencyHub` were
  hand-rolling `flex gap-1 overflow-x-auto` instead, which is the same thing
  with a scrollbar showing; both now use the class.
- **`.btn` sets a hard `min-height` in plain CSS, not via a token.** That is
  what makes it survive the spacing replacement.
- **`.tap` was purged until Phase 2, because nothing used it.** Tailwind emits
  an unused `@layer components` class out of the bundle, so a documented class
  that no component referenced produced no CSS at all. It is applied now to the
  bottom tab bar, `ListRow`, the `Tabs` strip, the tab strips in `Admin` and
  `EmergencyHub`, the language toggle and the theme toggle.

`.tap` on a control that is already 44px is redundant; on one that is smaller
it is the whole point. The two places it needs a `-my-2` alongside it are
controls that must stay visually short: the language pills and the theme toggle.
`.tap` adds `min-height` and `-my-2` takes the difference back out, so the hit
area is 44px and the control is still 28px. Verified in the build output:

```css
.tap { min-height: 2.75rem; min-width: 2.75rem }
```

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
reduced motion is handled once, globally. `test_reduced_motion_covers_every_animation`
asserts the block still neutralises `animation-duration`,
`animation-iteration-count` and `transition-duration` — it was previously scoped
to the sheet entry only, which left `animate-fade-in` on the result screen and
`animate-pulse` on the recording indicator running regardless.

`index.css` also had a **second `.dark` block** in `@layer base` containing only
`color-scheme: dark`, a duplicate of the one that holds the dark ramp. Deleted
in Phase 2; it could not have applied anything the real block did not.

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

**`touch-lg` is unused**, which is the same failure `.tap` had: a token in the
config that no class references. It is 48px, and there is no control that needs
48px, so Phase 2 left it rather than inventing a use for it.

## i18n namespaces

**Phase 9 moved the catalogues out of TypeScript and into JSON.** They now live
at `i18n/locales/en.json` and `i18n/locales/ta.json`; `i18n/strings.ts` is a
typed re-export over them. Both files must be UTF-8 **without a BOM**.

The reason is a specific failure, not style. Two simulation-disclosure strings
were written through a PowerShell pipeline whose console encoding could not
represent the prose, and every character it could not encode became a literal
`?`. The safety banner shipped as two rows of question marks. Typecheck passed,
the build passed, and both catalogues were "symmetric" by key count - a row of
`?` is a perfectly valid string, and the key-count assertion could not see it.
Strings now live in data files that no shell touches, and
`test_no_catalogue_value_is_corrupted_by_an_encoding_round_trip` asserts the
signature directly.

The same failure mode applies to *editing* these files: `Get-Content` /
`Set-Content` on a BOM-less UTF-8 file in PowerShell 5.1 rewrites the Tamil as
mojibake and adds a BOM. Use the editor, or Python with explicit
`encoding="utf-8"`.

Keys are **flat strings with a dotted prefix**, not nested objects -
`"nav.home"`, not `{ nav: { home } }`. Flat keys keep the `StringKey` type
trivially derivable and make grep for a visible string reliable.

`i18n/index.tsx` asserts at module load that `ta` defines **exactly** the same
key set as `en`, in **both** directions, so a missing translation *and* an
orphaned English key are both startup errors. One direction is not enough: an
English key nobody renders is dead weight that looks like coverage.
`backend/tests/test_frontend_contract.py` asserts the same invariant from
pytest, which catches it before the client is ever loaded.

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
| `hub` | **New in Phase 9.** The emergency hub: tabs, live-region announcements, error copy, location, contact, medical, and the engine disclosure. |
| `result` | Match status labels, next actions and confidence copy. |
| `analytics` | **New in Phase 9.** Analytics status buckets, including `unknown`. |
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

Language names are the one place a Tamil word is correct inside `en.json`:
`lang.ta` is `தமிழ்` and `lang.en` is `English`, each in its own script, because
a language switcher that shows "Tamil" in a Latin alphabet is a guess at the
best. Asserted nowhere by a "no Tamil in English" rule, deliberately; the
corruption guard looks for `?` runs and `U+FFFD`, not for non-ASCII text.

**Coverage is complete as of Phase 9.** Every page resolves its user-visible copy
through `t()`. `Privacy` now renders the `privacy.*` keys that existed and were
unused, and the catalogues hold **440 keys each**, symmetric by construction.
`test_no_page_or_component_hardcodes_user_visible_english` fails the build when a
literal appears in a `.tsx` page or component, so the list of unwired namespaces
below is now a list of translation work, not a list of English the user can see.

That test is a scanner, and a scanner is only as good as its weakest
assumption, so two things about it are deliberate:

- **It strips comments first.** A Tailwind class named in prose is a class the
  build emits a rule for, so comments are not a safe place to be exempt.
- **It is mutation-checked.** The gate was re-run with each of the three English
  strings that actually shipped during this migration reinstated, and each one
  must fail the build. Two of the three initially passed, which is why the
  exclusions are named (`Escape`, arrow-key names, `.querySelector`, the demo
  password) rather than pattern-matched loosely.

`enroll` was the first namespace to be fully wired, in Phase 6, which is the
proof the flat-key scheme survives contact with a real flow. It was written in
Phase 0 and sat entirely unreferenced until Phase 6; `EnrollWizard` plus
`Profile` now use every one of them, in both languages. Two things about how it
is consumed are worth copying:

- **Guidance codes are keys, not sentences.** The engine returns
  `no_face_detected`, and `EnrollWizard` builds `enroll.guidance.${code}`. A
  backend that gains a reason code renders a raw code on screen until the string
  is added, which is the correct failure - a missing translation is loud here,
  while a paraphrased message would be silently inconsistent.
- **A key that cannot be constructed from a constant needs a cast.**
  `t(\`enroll.step.${step.key}\` as StringKey)` is the one `as` in the frontend,
  and it is unavoidable: `StringKey` is derived from `en`, so a template literal
  cannot prove membership. Everything else uses a literal key.

## The palette migration is done, and so is the string migration

`ink-*` and `slate-*` were removed from the theme, and six files were still using
them: `Admin`, `Demo`, `EmergencyHub`, `Privacy`, `Profile`, and `Guards`. Every
one of those classes was emitting no CSS, so those pages were rendering with no
card background, no border and no tint anywhere. All of them are now on the
ramp. Two tests hold the line, and they cover the case a component scan cannot:

```python
test_no_component_uses_an_off_ramp_colour          # JSX className
test_class_strings_do_not_contain_off_ramp_colours  # lookup tables in .ts
```

The second one exists because `utils/format.ts` builds badge tints as strings in
a data table. Three of those classes were invented and had never rendered.

**The string migration is closed.** Phase 9 took the last five pages onto
`hub.*`/`profile.*`/`admin.*`/`demo.*`/`privacy.*`, and
`test_no_page_or_component_hardcodes_user_visible_english` holds the line from
then on. Both migrations now share one lesson worth keeping: an `@layer
components` class that nothing references, a Tailwind colour with no
`<alpha-value>`, a spacing step outside `theme.spacing`, and an English literal
in a page are the same defect. **The build emitted nothing, nothing looked
broken, and only a machine could tell.** The tests exist because every one of
those was caught by a scanner rather than by looking at the screen.

To find un-migrated colour usage from the shell, the equivalent of the two tests
above:

```powershell
Select-String -Path src\pages\*.tsx -Pattern 'ink-|slate-|accent-\d|text-white'
```

Treat a page as finished when that returns nothing **and**
`test_no_page_or_component_hardcodes_user_visible_english` passes.
