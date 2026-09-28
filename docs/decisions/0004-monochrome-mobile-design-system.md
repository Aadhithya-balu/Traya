[../README.md](../README.md) | [Decisions](README.md)

# ADR 0004: Monochrome, mobile-first, token-driven design system

- **Status:** Accepted
- **Date:** 2026-09-28
- **Affects:** `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/src/theme/`, `frontend/src/i18n/`, `frontend/src/components/`

## Context

The product is used in the worst possible lighting and by people who are
stressed. Colour is a liability: red and amber usually mean "something is wrong"
in a medical UI, and spending them on decoration destroys that signal. The first
build also carried a `ink-*`/`accent-*`/`slate-*` palette inherited from a
template that was never design-reviewed, and hardcoded English strings, which is
unusable for the Tamil-speaking population the product serves.

## Decision

1. **Monochrome by default.** The accent is near-black in light mode and
   near-white in dark mode. The only chromatic colours are semantic: `--c-danger`
   for critical, `--c-warn` for caution, `--c-ok` for confirmed. They are never
   used decoratively.
2. **Tokens, not palette classes.** All colour flows through 17 CSS custom
   properties aliased once in `tailwind.config.js` as `ramp`. Both themes are
   defined by overriding the variables under `.dark`, so a single class name works
   in both modes. Tailwind `dark:` variants are not used.
3. **Mobile is the primary target.** 44px minimum touch targets via `.btn`,
   `.input` and the `min-h-touch` token; `viewport-fit=cover` with
   `env(safe-area-inset-*)`; a fixed, thumb-reachable bottom tab bar; and
   `overflow-x: hidden` on `body` so nothing scrolls sideways at 320px.
4. **Theme is applied before first paint.** An inline script in `index.html`
   reads `localStorage` and `prefers-color-scheme` and sets the `.dark` class
   before the bundle executes, so there is no flash of the wrong theme.
5. **Every user-facing string is an i18n key.** `en` is `as const`, so
   `StringKey` is a literal union and `ta: Record<StringKey, string>` makes a
   missing Tamil translation a **compile error**.
6. **A simulation banner on every result**, per
   [ADR 0001](0001-simulation-biometric-engine.md).

## Consequences

**Good.** One class name per colour role, correct in both themes by
construction. A missing translation cannot reach production. No decorative
colour competes with a clinical signal. The touch targets and safe-area
handling make the app usable one-handed by a responder holding a phone in one
hand at night.

**Costs and sharp edges.**

- `theme.spacing` is **replaced**, not extended. A value outside the declared
  scale produces no CSS at all and fails silently. Adding a spacing value means
  editing `tailwind.config.js`.
- `ramp` colours are plain `var(--c-*)` strings, not functions containing
  `<alpha-value>`. **Tailwind cannot apply an opacity modifier to them**, so
  `bg-ok/15` is dropped and renders nothing. Use a real token or a border, not
  `/opacity`, on any ramp colour.
- `Inter` is declared in `fontFamily.sans` but never loaded, so the app silently
  falls back to `system-ui`. Either load it or stop declaring it.
- There is no `system` theme option in the UI. The theme provider writes
  `localStorage` on mount, which permanently pins the theme after the first
  visit instead of following the OS. This is a known bug, documented in
  [the design system](../frontend/design-system.md#known-defects) rather than
  papered over.
