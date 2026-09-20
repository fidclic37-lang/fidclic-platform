/**
 * i18n bootstrap — single source of truth for translations.
 *
 * Three locales:
 *   - fr  (Default / source of truth — the platform was authored in French.)
 *   - en  (Full translation, owner-reviewed.)
 *   - ar  (Machine baseline + RTL layout flip. Needs native review before
 *          rolling out to Arabic-speaking tenants.)
 *
 * Detection order:
 *   1. localStorage 'fidelitour:lang' (user explicitly chose)
 *   2. <html lang>
 *   3. browser navigator.language
 *   4. fallback to 'fr'
 *
 * RTL: when language is 'ar', we flip <html dir="rtl"> in the
 * LanguageSwitcher's onChange so any CSS that respects [dir] mirrors
 * automatically (Tailwind logical properties + most flex layouts).
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import fr from '../locales/fr.json';
import en from '../locales/en.json';
import ar from '../locales/ar.json';

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      fr: { translation: fr },
      en: { translation: en },
      ar: { translation: ar },
    },
    fallbackLng: 'fr',
    supportedLngs: ['fr', 'en', 'ar'],
    interpolation: { escapeValue: false }, // React already escapes
    detection: {
      order: ['localStorage', 'htmlTag'],   // FR by default (html lang); the browser locale never overrides it
      lookupLocalStorage: 'fidelitour:lang',
      caches: ['localStorage'],
    },
    react: {
      useSuspense: false, // we ship resources synchronously, no need
    },
  });

// Keep <html lang> in sync with the active language. We DO NOT flip
// the document direction to RTL for Arabic — the owner explicitly
// asked that the layout stays left-to-right in all three languages.
// Only the displayed text changes.
i18n.on('languageChanged', (lng) => {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = lng;
    document.documentElement.dir = 'ltr';
  }
});

// Apply once on initial load.
if (typeof document !== 'undefined') {
  document.documentElement.lang = i18n.language || 'fr';
  document.documentElement.dir = 'ltr';
}

export default i18n;
