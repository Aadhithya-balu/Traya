import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { en, ta, type StringKey } from "./strings";

export const LOCALES = ["en", "ta"] as const;
export type Locale = (typeof LOCALES)[number];

const DICTIONARIES: Record<Locale, Record<StringKey, string>> = { en, ta };

// A missing translation must fail loudly at import time, not render an English
// word inside an otherwise Tamil screen.
//
// Checked in both directions. A key present in `en` and absent from `ta` is the
// failure users see, but the reverse is the one that hides: an orphan key in
// `ta` compiles cleanly, never renders, and survives every review, so the
// catalogue slowly grows a second, dead vocabulary. Neither direction is
// detectable from the key alone, so both are asserted here.
for (const locale of LOCALES) {
  const missing = (Object.keys(en) as StringKey[]).filter(
    (key) => !(key in DICTIONARIES[locale]),
  );
  const orphan = Object.keys(DICTIONARIES[locale]).filter(
    (key) => !(key in en),
  );

  if (missing.length) {
    throw new Error(
      `Locale "${locale}" is missing ${missing.length} key(s): ${missing.join(", ")}`,
    );
  }
  if (orphan.length) {
    throw new Error(
      `Locale "${locale}" defines ${orphan.length} key(s) absent from "en": ${orphan.join(", ")}`,
    );
  }
}

const STORAGE_KEY = "traya_locale";

function readStoredLocale(): Locale {
  if (typeof window === "undefined") return "en";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "ta" || stored === "en" ? stored : "en";
}

interface I18nValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: StringKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  const t = useCallback(
    (key: StringKey, vars?: Record<string, string | number>) => {
      // Fall back to English rather than rendering the raw key: a partially
      // translated screen is still readable, an untranslated key is not.
      const template = DICTIONARIES[locale][key] ?? en[key] ?? key;
      if (!vars) return template;
      return Object.entries(vars).reduce(
        (acc, [name, value]) => acc.replaceAll(`{${name}}`, String(value)),
        template,
      );
    },
    [locale],
  );

  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}

export type { StringKey };
