/** @type {import('tailwindcss').Config} */

// TRAYA is deliberately monochrome. The only hues in the interface are the
// three that carry meaning: red for danger/stop, amber for caution, and a
// single desaturated accent for interactive affordances. Everything else is
// a neutral on a light-to-dark ramp, so identity and status read without
// decoration. Colours are emitted as CSS custom properties (see index.css) so
// light and dark share one set of class names.
// The `<alpha-value>` placeholder is mandatory. Without it Tailwind cannot
// build `bg-danger/10` or `border-warn/30`, and because the value is a valid
// colour string the build still succeeds - the utility is just silently absent
// from the stylesheet. That is how the app bar, the tab bar and every status
// badge tint ended up with no background at all.
const ramp = Object.fromEntries(
  [
    "canvas",
    "surface",
    "raised",
    "line",
    "line-strong",
    "text",
    "muted",
    "faint",
    "accent",
    "accent-text",
    "accent-fg",
    "danger",
    "danger-fg",
    "warn",
    "warn-fg",
    "ok",
    "ok-fg",
  ].map((name) => [name, `rgb(var(--c-${name}-rgb) / <alpha-value>)`]),
);

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    // Spacing is replaced rather than extended: the default 0.25rem steps make
    // it far too easy to ship a cramped layout on a 360px screen.
    spacing: {
      0: "0px",
      px: "1px",
      0.5: "0.125rem",
      1: "0.25rem",
      1.5: "0.375rem",
      2: "0.5rem",
      2.5: "0.625rem",
      3: "0.75rem",
      3.5: "0.875rem",
      4: "1rem",
      5: "1.25rem",
      6: "1.5rem",
      7: "1.75rem",
      8: "2rem",
      9: "2.25rem",
      10: "2.5rem",
      11: "2.75rem",
      12: "3rem",
      // No 5.5 and no 13. Phase 2 considered adding both, because `-translate-x-5.5`
      // silently compiled to nothing. Adding them would have re-legalised the
      // exact trap that just cost a bug: an off-scale value that looks fine and
      // produces no CSS. The caller was wrong, not the scale.
      14: "3.5rem",
      16: "4rem",
      20: "5rem",
      24: "6rem",
      32: "8rem",
      40: "10rem",
      48: "12rem",
      56: "14rem",
      64: "16rem",
      full: "100%",
    },
    extend: {
      colors: ramp,
      // Minimum comfortable touch target. Anything interactive should be at
      // least this tall on both axes.
      minHeight: {
        touch: "2.75rem",
        "touch-lg": "3rem",
      },
      minWidth: {
        touch: "2.75rem",
      },
      borderRadius: {
        sm: "0.375rem",
        DEFAULT: "0.5rem",
        md: "0.625rem",
        lg: "0.75rem",
        xl: "1rem",
        "2xl": "1.25rem",
        full: "9999px",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1rem" }],
        sm: ["0.875rem", { lineHeight: "1.25rem" }],
        base: ["1rem", { lineHeight: "1.5rem" }],
        lg: ["1.125rem", { lineHeight: "1.75rem" }],
        xl: ["1.25rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.5rem", { lineHeight: "2rem" }],
        "3xl": ["1.875rem", { lineHeight: "2.25rem" }],
        "4xl": ["2.25rem", { lineHeight: "2.5rem" }],
      },
      transitionDuration: {
        150: "150ms",
      },
      keyframes: {
        "sheet-in": {
          from: { transform: "translateY(100%)" },
          to: { transform: "translateY(0)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "rise": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "sheet-in": "sheet-in 220ms cubic-bezier(0.32, 0.72, 0, 1)",
        "fade-in": "fade-in 160ms ease-out",
        rise: "rise 200ms cubic-bezier(0.32, 0.72, 0, 1)",
      },
    },
  },
  plugins: [],
};
