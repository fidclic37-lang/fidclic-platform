/**
 * LanguageSwitcher — three-button row that flips the active language
 * for the entire platform. Persists choice in localStorage via
 * i18next-browser-languagedetector. Flipping to AR auto-sets
 * <html dir="rtl"> via the i18n.on('languageChanged') hook in lib/i18n.js.
 *
 * Used in two places:
 *   • Sidebar (compact variant, icon-only flags)
 *   • Settings → Langue de l'interface (full variant with hint)
 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { applyGoogleTranslate } from './GoogleTranslateBridge';
import { ownerAPI } from '../lib/api';

const LANGS = [
  { code: 'fr', flag: '🇫🇷', label: 'Français' },
  { code: 'en', flag: '🇬🇧', label: 'English' },
  { code: 'ar', flag: '🇸🇦', label: 'العربية' },
];

export default function LanguageSwitcher({ variant = 'full' }) {
  const { i18n, t } = useTranslation();
  const current = (i18n.resolvedLanguage || i18n.language || 'fr').slice(0, 2);

  // Re-apply the active language on mount so a hard refresh (which boots
  // the Google bridge fresh) restores the user's chosen translation.
  React.useEffect(() => {
    if (current) applyGoogleTranslate(current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const change = (code) => {
    if (code === current) return;
    try { localStorage.setItem('fidclic:lang-chosen', '1'); } catch { /* ignore */ }
    // 1) Flip our own t() strings (sidebar, page titles, etc.).
    i18n.changeLanguage(code);
    // 2) Trigger Google Translate Element to retranslate EVERY remaining
    //    DOM text node — deep form labels, modal copy, API-rendered
    //    content, error toasts. This is what makes the language picker
    //    behave like google.com/translate rather than just a header swap.
    applyGoogleTranslate(code);
    // Remembered with the account (Paramètres › Préférences), so it follows
    // the person to another device. Signed out: nothing to save.
    ownerAPI.savePreferences?.({ language: code }).catch(() => {});
  };

  if (variant === 'compact') {
    return (
      <div style={{ display: 'flex', gap: 4 }} role="group" aria-label="Language">
        {LANGS.map((lng) => {
          const active = lng.code === current;
          return (
            <button
              key={lng.code}
              type="button"
              onClick={() => change(lng.code)}
              aria-pressed={active}
              title={lng.label}
              style={{
                padding: '3px 8px',
                fontSize: 13,
                borderRadius: 6,
                border: active ? '1px solid #B85C38' : '1px solid #E9E5E0',
                background: active ? 'color-mix(in srgb, var(--flc-accent-2, #E8703A) 12%, var(--flc-card, #FFFFFF))' : 'var(--flc-card, #FFFFFF)',
                cursor: 'pointer',
                font: 'inherit',
                lineHeight: 1,
              }}
            >
              {lng.flag}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div style={{
      background: 'var(--flc-card, #FFFFFF)',
      border: '1px solid var(--flc-line, #E9E5E0)',
      borderRadius: 12,
      padding: 18,
    }}>
      <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#171412' }}>
        {t('settings.language_title')}
      </h3>
      <p style={{ margin: '4px 0 12px', fontSize: 12.5, color: '#57504A' }}>
        {t('settings.language_subtitle')}
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {LANGS.map((lng) => {
          const active = lng.code === current;
          return (
            <button
              key={lng.code}
              type="button"
              onClick={() => change(lng.code)}
              aria-pressed={active}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 8,
                padding: '8px 14px', borderRadius: 10,
                border: active ? '1px solid #B85C38' : '1px solid #E9E5E0',
                background: active ? 'color-mix(in srgb, var(--flc-accent-2, #E8703A) 12%, var(--flc-card, #FFFFFF))' : 'var(--flc-card, #FFFFFF)',
                cursor: 'pointer',
                color: '#171412', font: 'inherit', fontSize: 13.5, fontWeight: 500,
                minWidth: 120,
                justifyContent: 'flex-start',
              }}
            >
              <span style={{ fontSize: 18 }}>{lng.flag}</span>
              <span>{lng.label}</span>
              {active && <span style={{ marginLeft: 'auto', color: '#B85C38' }}>✓</span>}
            </button>
          );
        })}
      </div>
      {current === 'ar' && (
        <p style={{ marginTop: 12, fontSize: 11.5, color: 'var(--flc-accent-deep, #A04A1F)', background: 'color-mix(in srgb, var(--flc-accent-2, #E8703A) 12%, var(--flc-card, #FFFFFF))', padding: '6px 10px', borderRadius: 8 }}>
          ⚠ {t('settings.language_ar_hint')}
        </p>
      )}
    </div>
  );
}
