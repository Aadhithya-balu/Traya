/**
 * English and Tamil strings.
 *
 * Keys are namespaced by surface. `en` is the source of truth: every other
 * locale must define exactly the same key set, which `i18n/index.ts` asserts
 * at module load, so a missing translation is a startup error rather than an
 * English word leaking into a Tamil screen.
 *
 * The catalogue lives in `locales/*.json` rather than in TypeScript so that a
 * translator can edit it without touching the build, and so the two locales sit
 * side by side as diffable data instead of 480 lines apart in one file.
 *
 * Importing JSON does not cost the type safety that motivated moving it: with
 * `resolveJsonModule` the key set is inferred as a literal union, so `StringKey`
 * is still checked at compile time and `t("emergency.intro.title")` is still a
 * build error if the key is renamed. Only the *values* widen to `string`, which
 * they were anyway.
 */
import enCatalogue from "./locales/en.json";
import taCatalogue from "./locales/ta.json";

export const en = enCatalogue;

export type StringKey = keyof typeof enCatalogue;

// Annotated rather than inferred so a locale file that *loses* a key is a
// compile error, not a runtime surprise on a Tamil screen. Extra keys are still
// permitted here, so `i18n/index.ts` asserts that direction at load.
export const ta: Record<StringKey, string> = taCatalogue;