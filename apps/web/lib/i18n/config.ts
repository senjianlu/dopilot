import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en";
import zh from "./locales/zh";

export type AppLocale = "zh" | "en";

export const LOCALE_STORAGE_KEY = "dopilot.locale";
export const DEFAULT_LOCALE: AppLocale = "zh";

// Read the persisted locale (client only). Default stays Chinese so the static
// build and the first client render agree (no hydration mismatch); a persisted
// override is applied after mount by the I18nProvider.
export function readStoredLocale(): AppLocale {
  try {
    const value = localStorage.getItem(LOCALE_STORAGE_KEY);
    return value === "en" || value === "zh" ? value : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function persistLocale(locale: AppLocale): void {
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // ignore storage errors (e.g. private mode)
  }
}

// Single shared i18next instance. Initialized once with both locales; the
// default language is Chinese, English is the fallback. Keys are nested objects
// resolved with the default "." separator.
if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources: {
      zh: { translation: zh },
      en: { translation: en },
    },
    lng: DEFAULT_LOCALE,
    fallbackLng: "en",
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
  });
}

export default i18n;
